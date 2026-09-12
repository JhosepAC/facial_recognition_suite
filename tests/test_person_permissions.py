"""
C1 — Revalidación de permisos en la capa de servicios (registro de personas).

El servicio no puede confiar solo en la interfaz: cualquier operación de
escritura sobre personas exige el permiso del rol y un actor identificado.
"""
from pathlib import Path

import pytest

from app.core.exceptions import AuthorizationError, BioVisionError
from app.database.base import Base
from app.services.admin_service import AdminService
from app.services.person_service import PersonService


@pytest.fixture()
def session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture()
def users_and_roles(session):
    admin_svc = AdminService(session)
    admin = admin_svc.create_initial_admin("admin", "ClaveSegura123", "Admin General")
    roles = {r.nombre: r for r in admin_svc.list_roles()}
    operador = admin_svc.create_user(
        "operador1", "Clave1234", roles["Operador"].id, "Juan Operador", usuario_actor="admin"
    )
    visualizador = admin_svc.create_user(
        "visualizador1", "Clave1234", roles["Visualizador"].id, "Vi Visual", usuario_actor="admin"
    )
    return admin, operador, visualizador, roles


# ------------------------------------------------------------------ #
# Operación sin actor identificado
# ------------------------------------------------------------------ #
def test_write_operation_without_actor_raises(session, users_and_roles):
    with pytest.raises(AuthorizationError):
        PersonService(session).create_person(nombre="A", apellidos="B", usuario=None)


# ------------------------------------------------------------------ #
# Crear persona
# ------------------------------------------------------------------ #
def test_visualizador_cannot_create_person(session, users_and_roles):
    with pytest.raises(AuthorizationError):
        PersonService(session).create_person(
            nombre="A", apellidos="B", usuario="visualizador1"
        )
    assert PersonService(session).count() == 0


def test_operador_can_create_person(session, users_and_roles):
    person = PersonService(session).create_person(
        nombre="A", apellidos="B", usuario="operador1"
    )
    assert person.nombre == "A"


# ------------------------------------------------------------------ #
# Actualizar persona
# ------------------------------------------------------------------ #
def test_visualizador_cannot_update_person(session, users_and_roles):
    svc = PersonService(session)
    person = svc.create_person(nombre="A", apellidos="B", usuario="admin")
    session.commit()
    with pytest.raises(AuthorizationError):
        svc.update_person(person.uuid, nombre="X", apellidos="Y", usuario="visualizador1")


def test_operador_can_update_person(session, users_and_roles):
    svc = PersonService(session)
    person = svc.create_person(nombre="A", apellidos="B", usuario="operador1")
    session.commit()
    updated = svc.update_person(person.uuid, nombre="X", apellidos="Y", usuario="operador1")
    assert updated.nombre == "X"


# ------------------------------------------------------------------ #
# Fotos
# ------------------------------------------------------------------ #
def test_visualizador_cannot_add_photo(session, users_and_roles):
    # El chequeo de permiso precede a cualquier acceso al archivo.
    with pytest.raises(AuthorizationError):
        PersonService(session).add_photo_from_path(
            "cualquier-uuid", "no-existe.jpg", usuario="visualizador1"
        )


def test_visualizador_cannot_set_primary_photo(session, users_and_roles):
    with pytest.raises(AuthorizationError):
        PersonService(session).set_primary_photo("cualquier-uuid", 1, usuario="visualizador1")


def test_visualizador_cannot_delete_photo(session, users_and_roles):
    with pytest.raises(AuthorizationError):
        PersonService(session).delete_photo("cualquier-uuid", 999, usuario="visualizador1")


# ------------------------------------------------------------------ #
# Borrado de persona (exige permisos de personas + administración)
# ------------------------------------------------------------------ #
def test_operador_cannot_delete_person(session, users_and_roles):
    svc = PersonService(session)
    person = svc.create_person(nombre="A", apellidos="B", usuario="operador1")
    session.commit()
    with pytest.raises(AuthorizationError):
        svc.delete(person.uuid, usuario="operador1")
    assert PersonService(session).count() == 1


def test_admin_can_delete_person(session, users_and_roles):
    svc = PersonService(session)
    person = svc.create_person(nombre="A", apellidos="B", usuario="admin")
    session.commit()
    assert svc.delete(person.uuid, usuario="admin") is True
    assert PersonService(session).count() == 0


# ------------------------------------------------------------------ #
# Fase 3 (B8): validación básica de campos
# ------------------------------------------------------------------ #
def test_create_person_negative_age_raises(session, users_and_roles):
    svc = PersonService(session)
    with pytest.raises(ValueError):
        svc.create_person(nombre="A", apellidos="B", edad_aproximada=-5, usuario="admin")


def test_create_person_invalid_email_raises(session, users_and_roles):
    svc = PersonService(session)
    with pytest.raises(ValueError):
        svc.create_person(nombre="A", apellidos="B", correo="no-es-un-correo", usuario="admin")


def test_update_person_validates_fields(session, users_and_roles):
    svc = PersonService(session)
    person = svc.create_person(nombre="A", apellidos="B", usuario="admin")
    session.commit()
    with pytest.raises(ValueError):
        svc.update_person(person.uuid, nombre="A", apellidos="B",
                          edad_aproximada=-1, usuario="admin")


# ------------------------------------------------------------------ #
# Fase 3 (B4): add_photo_from_path valida el archivo origen
# ------------------------------------------------------------------ #
def test_add_photo_missing_file_raises(session, users_and_roles):
    svc = PersonService(session)
    person = svc.create_person(nombre="A", apellidos="B", usuario="admin")
    session.commit()
    with pytest.raises(BioVisionError):
        svc.add_photo_from_path(person.uuid, "no-existe.jpg", usuario="admin")


# ------------------------------------------------------------------ #
# Fase 3 (A3): delete_photo exige que la foto pertenezca a la persona
# ------------------------------------------------------------------ #
def test_delete_photo_rejects_photo_of_other_person(session, users_and_roles, tmp_path):
    from app.database.models import Photo

    svc = PersonService(session)
    persona_a = svc.create_person(nombre="Ana", apellidos="A", usuario="admin")
    persona_b = svc.create_person(nombre="Bet", apellidos="B", usuario="admin")
    session.commit()

    photo_file = tmp_path / "foto.jpg"
    photo_file.write_bytes(b"data")
    thumb_file = tmp_path / "foto_thumb.jpg"
    thumb_file.write_bytes(b"data")

    photo = Photo(person_uuid=persona_a.uuid, file_path=str(photo_file),
                  thumbnail_path=str(thumb_file), es_principal=True)
    session.add(photo)
    session.commit()

    # La foto pertenece a A: borrarla desde B debe rechazarse y no tocar archivos.
    assert svc.delete_photo(persona_b.uuid, photo.id, usuario="admin") is False
    assert photo_file.exists() and thumb_file.exists()

    # Borrarla desde A sí procede (y elimina los archivos tras confirmar la BD).
    assert svc.delete_photo(persona_a.uuid, photo.id, usuario="admin") is True
    assert not photo_file.exists() and not thumb_file.exists()


# ------------------------------------------------------------------ #
# Fase 3 (A5): borrar una persona limpia eventos y detecciones huérfanos
# ------------------------------------------------------------------ #
def test_delete_person_cleans_recognition_events_and_detections(session, users_and_roles):
    from app.database.models import RecognitionEvent, VideoDetection, VideoJob

    svc = PersonService(session)
    person = svc.create_person(nombre="A", apellidos="B", usuario="admin")
    session.commit()

    job = VideoJob(file_path="v.mp4", nombre_archivo="v.mp4", estado="completado")
    session.add(job)
    session.commit()
    session.add(RecognitionEvent(origen="webcam", person_uuid=person.uuid, confianza=90.0))
    session.add(VideoDetection(video_job_id=job.id, frame_number=1, timestamp_seg=0.0,
                               person_uuid=person.uuid, bbox_x1=0, bbox_y1=0, bbox_x2=10, bbox_y2=10))
    session.commit()
    assert session.query(RecognitionEvent).count() == 1
    assert session.query(VideoDetection).count() == 1

    assert svc.delete(person.uuid, usuario="admin") is True
    session.commit()
    assert session.query(RecognitionEvent).count() == 0
    assert session.query(VideoDetection).count() == 0
    assert session.query(VideoJob).count() == 1  # el job de video se conserva