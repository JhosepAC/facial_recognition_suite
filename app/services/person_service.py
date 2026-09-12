"""
Capa de servicio: orquesta PersonRepository + RecognitionService + almacenamiento
de archivos. La GUI solo debe hablar con esta clase, nunca con los repositorios
o el motor de visión directamente (separación estricta GUI <-> lógica).
"""
from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import cv2
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthorizationError, BioVisionError
from app.core.logger import audit_logger, logger
from app.core.permissions import PERM_ADMIN, PERM_PERSONAS
from app.database.models import Person, Photo, RecognitionEvent, VideoDetection
from app.database.repositories.person_repository import PersonRepository
from app.recognition.recognition_service import RecognitionService
from app.services.auth_service import AuthService
from app.services.export_service import slugify
from app.services.statistics_service import primary_embedding_attrs
from app.vision.face_attributes import ATTR_FIELDS

THUMBNAIL_SIZE = (256, 256)


def _matches_attribute_filter(attrs_obj, required_present: list[str],
                              required_absent: list[str]) -> bool:
    """True si un análisis facial cumple los criterios de atributos pedidos.

    Sin análisis facial registrado, la persona nunca supera el filtro
    (no hay evidencia para confirmar presencia/ausencia).
    """
    if attrs_obj is None:
        return False
    present = {f for f in ATTR_FIELDS if bool(getattr(attrs_obj, f))}
    return (all(f in present for f in required_present)
            and all(f not in present for f in required_absent))


def _matches_color_filter(attrs_obj, color_ojos: str | None,
                          color_pelo: str | None) -> bool:
    """True si el análisis facial coincide con los colores pedidos (si los hay)."""
    if attrs_obj is None:
        return color_ojos is None and color_pelo is None
    if color_ojos and getattr(attrs_obj, "color_ojos", None) != color_ojos:
        return False
    if color_pelo and getattr(attrs_obj, "color_pelo", None) != color_pelo:
        return False
    return True


def _require_permissions(session: Session, usuario: str | None, *permissions: str) -> None:
    """Exige que el usuario autenticado tenga TODOS los permisos indicados.

    Todas las operaciones de escritura sobre el registro de personas requieren
    un actor identificado; un ``usuario`` nulo se rechaza siempre.
    """
    if usuario is None:
        raise AuthorizationError("Operación denegada: falta el usuario autenticado.")
    auth = AuthService(session)
    actor = auth.repo.get_by_username(usuario)
    for perm in permissions:
        auth.require_permission(actor, perm)


def _validate_person_fields(*, edad_aproximada: int | None, correo: str | None) -> None:
    """Validación básica de datos personales antes de crear/actualizar."""
    if edad_aproximada is not None and edad_aproximada < 0:
        raise ValueError("La edad aproximada no puede ser negativa.")
    if correo and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", correo):
        raise ValueError("El correo no tiene un formato válido.")


class PersonService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = PersonRepository(session)
        self.recognition = RecognitionService(session)
        self.photos_dir = settings.resolve_path(settings.storage.photos_dir)
        self.thumbs_dir = settings.resolve_path(settings.storage.thumbnails_dir)
        self.photos_dir.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def create_person(self, *, nombre: str, apellidos: str, alias: str | None = None,
                       sexo: str | None = None, edad_aproximada: int | None = None,
                       empresa: str | None = None, departamento: str | None = None,
                       cargo: str | None = None, telefono: str | None = None,
                       correo: str | None = None, observaciones: str | None = None,
                       usuario: str | None = None) -> Person:
        _require_permissions(self.session, usuario, PERM_PERSONAS)
        _validate_person_fields(edad_aproximada=edad_aproximada, correo=correo)
        person = Person(
            nombre=nombre.strip(),
            apellidos=apellidos.strip(),
            alias=alias,
            sexo=sexo,
            edad_aproximada=edad_aproximada,
            empresa=empresa,
            departamento=departamento,
            cargo=cargo,
            telefono=telefono,
            correo=correo,
            observaciones=observaciones,
        )
        self.repo.add(person)
        audit_logger.info("Persona creada | uuid={} | nombre={} | usuario={}",
                           person.uuid, person.nombre_completo, usuario or "sistema")
        return person

    # ------------------------------------------------------------------ #
    def update_person(self, person_uuid: str, *, nombre: str, apellidos: str,
                      alias: str | None = None, sexo: str | None = None,
                      edad_aproximada: int | None = None, empresa: str | None = None,
                      departamento: str | None = None, cargo: str | None = None,
                      telefono: str | None = None, correo: str | None = None,
                      observaciones: str | None = None,
                      usuario: str | None = None) -> Person:
        """Actualiza los datos de una persona existente (sin duplicarla)."""
        _require_permissions(self.session, usuario, PERM_PERSONAS)
        _validate_person_fields(edad_aproximada=edad_aproximada, correo=correo)
        person = self.repo.get(person_uuid)
        if person is None:
            raise ValueError(f"Persona no encontrada: {person_uuid}")

        person.nombre = nombre.strip()
        person.apellidos = apellidos.strip()
        person.alias = alias
        person.sexo = sexo
        person.edad_aproximada = edad_aproximada
        person.empresa = empresa
        person.departamento = departamento
        person.cargo = cargo
        person.telefono = telefono
        person.correo = correo
        person.observaciones = observaciones
        self.session.flush()
        audit_logger.info("Persona actualizada | uuid={} | nombre={} | usuario={}",
                           person_uuid, person.nombre_completo, usuario or "sistema")
        return person

    # ------------------------------------------------------------------ #
    def add_photo_from_path(self, person_uuid: str, source_path: str,
                             set_as_primary: bool = False, usuario: str | None = None) -> Photo:
        """
        Copia la imagen al almacenamiento interno, genera miniatura y extrae embedding.

        Es transaccional: si la foto no produce un embedding válido, se elimina
        (filas y archivos) y se propaga el error, de modo que solo se persisten
        fotos realmente aprovechables para el reconocimiento.
        """
        _require_permissions(self.session, usuario, PERM_PERSONAS)
        person = self.repo.get(person_uuid)
        if person is None:
            raise ValueError(f"Persona no encontrada: {person_uuid}")

        src = Path(source_path)
        if not src.is_file():
            raise BioVisionError(f"El archivo de imagen no existe: {source_path}")
        ext = src.suffix.lower() or ".jpg"
        nombre_slug = slugify(f"{person.nombre} {person.apellidos}", default=person_uuid[:8])
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_name = f"{nombre_slug}_{person_uuid[:8]}_{fecha}_{uuid.uuid4().hex[:8]}{ext}"
        dest_path = self.photos_dir / dest_name
        thumb_path = self.thumbs_dir / dest_name
        shutil.copy2(src, dest_path)

        def _cleanup() -> None:
            dest_path.unlink(missing_ok=True)
            thumb_path.unlink(missing_ok=True)

        try:
            self._generate_thumbnail(dest_path, thumb_path)
        except Exception:
            _cleanup()
            raise

        photo = Photo(
            person_uuid=person_uuid,
            file_path=str(dest_path),
            thumbnail_path=str(thumb_path),
            es_principal=set_as_primary or not person.photos,
        )
        self.session.add(photo)
        self.session.flush()

        try:
            image_bgr = cv2.imread(str(dest_path))
            if image_bgr is None:
                raise ValueError(f"No se pudo leer la imagen: {dest_path}")
            embedding = self.recognition.enroll_photo(
                person_uuid, image_bgr, photo_id=photo.id, usuario=usuario
            )
        except Exception:
            self.session.delete(photo)
            _cleanup()
            raise

        photo.calidad_score = embedding.quality_score

        if set_as_primary:
            for p in person.photos:
                p.es_principal = (p.id == photo.id)

        return photo

    @staticmethod
    def _generate_thumbnail(source_path: Path, thumb_path: Path) -> None:
        with Image.open(source_path) as img:
            img = img.convert("RGB")
            img.thumbnail(THUMBNAIL_SIZE)
            img.save(thumb_path, "JPEG", quality=85)

    # ------------------------------------------------------------------ #
    def get(self, person_uuid: str) -> Person | None:
        return self.repo.get(person_uuid)

    def list_photos(self, person_uuid: str) -> list[Photo]:
        """Fotos de la persona, ordenadas: principal primero y luego por fecha."""
        person = self.repo.get(person_uuid)
        if person is None:
            return []
        return sorted(person.photos, key=lambda p: (not p.es_principal, p.fecha_creacion))

    def set_primary_photo(self, person_uuid: str, photo_id: int,
                          usuario: str | None = None) -> Photo:
        _require_permissions(self.session, usuario, PERM_PERSONAS)
        person = self.repo.get(person_uuid)
        if person is None:
            raise ValueError(f"Persona no encontrada: {person_uuid}")
        target = next((p for p in person.photos if p.id == photo_id), None)
        if target is None:
            raise ValueError(f"Foto no encontrada: {photo_id}")
        for p in person.photos:
            p.es_principal = (p.id == photo_id)
        self.session.flush()
        audit_logger.info("Foto principal actualizada | persona={} | photo_id={} | usuario={}",
                          person_uuid, photo_id, usuario or "sistema")
        return target

    def delete_photo(self, person_uuid: str, photo_id: int,
                     usuario: str | None = None) -> bool:
        """Elimina una foto de la persona: fila, embeddings y archivos físicos.

        Valida que la foto pertenezca a la persona indicada (integridad en la
        capa de servicio). El borrado es transaccional: primero se eliminan las
        filas (y se confirma) y solo después los archivos, de modo que un fallo
        de la BD nunca deja las fotos huérfanas en disco ni viceversa.
        """
        _require_permissions(self.session, usuario, PERM_PERSONAS)
        person = self.repo.get(person_uuid)
        if person is None:
            raise ValueError(f"Persona no encontrada: {person_uuid}")
        target = next((p for p in person.photos if p.id == photo_id), None)
        if target is None:
            return False
        was_primary = target.es_principal
        files = [f for f in (target.file_path, target.thumbnail_path) if f]

        self.session.delete(target)  # cascade -> embeddings
        self.session.flush()
        if was_primary:
            remaining = sorted(
                (p for p in person.photos if p.id != photo_id),
                key=lambda p: p.fecha_creacion,
            )
            if remaining:
                remaining[0].es_principal = True
            self.session.flush()
        self.session.commit()

        for path_str in files:
            try:
                Path(path_str).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("No se pudo eliminar el archivo '{}': {}", path_str, exc)

        audit_logger.info("Foto eliminada | persona={} | photo_id={} | usuario={}",
                          person_uuid, photo_id, usuario or "sistema")
        return True

    # ------------------------------------------------------------------ #
    def search(self, query: str, empresa: str | None = None,
               attrs: list[str] | None = None,
               excl_attrs: list[str] | None = None,
               color_ojos: str | None = None,
               color_pelo: str | None = None) -> list[Person]:
        """Búsqueda por texto/empresa, con filtros de análisis facial y color.

        ``attrs``: campos que DEBEN estar presentes (p. ej. ["gafas"]).
        ``excl_attrs``: campos que DEBEN estar ausentes (p. ej. ["barba"]).
        ``color_ojos``/``color_pelo``: etiqueta discreta (None = sin filtro).
        """
        persons = list(self.repo.search_text(query, empresa=empresa))
        if attrs or excl_attrs or color_ojos or color_pelo:
            persons = [
                p for p in persons
                if _matches_attribute_filter(primary_embedding_attrs(p),
                                             attrs or [], excl_attrs or [])
                and _matches_color_filter(primary_embedding_attrs(p),
                                          color_ojos, color_pelo)
            ]
        return persons

    def list_empresas(self) -> list[str]:
        return list(self.repo.list_empresas())

    def list_all(self, limit: int = 200, offset: int = 0) -> list[Person]:
        return list(self.repo.list_all(limit=limit, offset=offset))

    def count(self) -> int:
        return self.repo.count()

    def delete(self, person_uuid: str, usuario: str | None = None) -> bool:
        # Borrado destructivo e irreversible: exige, además, acceso de administración.
        _require_permissions(self.session, usuario, PERM_PERSONAS, PERM_ADMIN)
        person = self.repo.get(person_uuid)
        if person is None:
            return False

        # 1) Recopilar rutas físicas ANTES de borrar filas (cascade vacía colecciones).
        files_to_delete = []
        for photo in person.photos:
            for path_str in (photo.file_path, photo.thumbnail_path):
                if path_str:
                    files_to_delete.append(path_str)
        detections = (
            self.session.query(VideoDetection)
            .filter(VideoDetection.person_uuid == person_uuid)
            .all()
        )
        files_to_delete.extend(
            d.evidencia_path for d in detections if d.evidencia_path
        )

        # 2) Limpieza explícita de datos huérfanos (FKs OFF en SQLite): eventos de
        #    reconocimiento y detecciones de video que referencian a la persona.
        self.session.query(RecognitionEvent).filter_by(person_uuid=person_uuid).delete()
        self.session.query(VideoDetection).filter_by(person_uuid=person_uuid).delete()

        # 3) Borrar la persona (cascade: fotos y embeddings) y confirmar ANTES de
        #    tocar el disco: si la BD falla, los archivos permanecen intactos.
        deleted = self.repo.delete(person_uuid)
        self.session.commit()

        # 4) Archivos físicos después del commit (fallos de borrado solo se registran).
        for path_str in files_to_delete:
            try:
                Path(path_str).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("No se pudo eliminar el archivo '{}': {}", path_str, exc)

        audit_logger.info(
            "Persona eliminada | uuid={} | detecciones_video={} | usuario={}",
            person_uuid, len(detections), usuario or "sistema",
        )
        return deleted
