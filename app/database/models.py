"""
Modelos ORM (SQLAlchemy 2.0) de FaceScan.

Diseño:
- Person: ficha biométrica de una persona registrada.
- Photo: fotografías asociadas a una persona (una persona puede tener varias).
- FaceEmbedding: vector biométrico (512-d) extraído de una foto concreta.
  Se separa de Photo para poder tener múltiples embeddings por foto/modelo
  y para poder recalcular embeddings sin perder la foto original.
- User / Role: control de acceso a la aplicación (no confundir con Person).
- RememberedSession: token de 'recordar sesión' (solo se persiste su hash SHA-256).
- AuditLog: bitácora de acciones sensibles.
- RecognitionEvent: historial de reconocimientos (imagen, video, webcam).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    String, Integer, Float, DateTime, ForeignKey, Text, LargeBinary, Boolean
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Person(Base):
    __tablename__ = "persons"

    uuid: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    nombre: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    apellidos: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    alias: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    sexo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    edad_aproximada: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha_nacimiento: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    empresa: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    departamento: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cargo: Mapped[str | None] = mapped_column(String(120), nullable=True)

    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    correo: Mapped[str | None] = mapped_column(String(150), nullable=True)
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)

    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    fecha_modificacion: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    photos: Mapped[list["Photo"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellidos}".strip()


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_uuid: Mapped[str] = mapped_column(ForeignKey("persons.uuid"), index=True)

    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    es_principal: Mapped[bool] = mapped_column(Boolean, default=False)
    calidad_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    person: Mapped["Person"] = relationship(back_populates="photos")
    embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        back_populates="photo", cascade="all, delete-orphan"
    )


class FaceEmbedding(Base):
    """
    Vector biométrico serializado (float32, 512-d por defecto — ArcFace/InsightFace).
    Se guarda como bytes crudos (LargeBinary) para eficiencia; ver app/utils/vector_utils.py
    para (de)serializar hacia/desde numpy.ndarray.
    """
    __tablename__ = "face_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_uuid: Mapped[str] = mapped_column(ForeignKey("persons.uuid"), index=True)
    photo_id: Mapped[int | None] = mapped_column(ForeignKey("photos.id"), nullable=True)

    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dim: Mapped[int] = mapped_column(Integer, default=512)
    model_name: Mapped[str] = mapped_column(String(60), default="buffalo_l")

    det_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    facial_attributes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON serializado de app.vision.face_attributes.FaceAttributes
    # (gafas/mascarilla/barba/bigote/sonrisa/ojos_abiertos + confianza).

    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    person: Mapped["Person"] = relationship(back_populates="embeddings")
    photo: Mapped["Photo | None"] = relationship(back_populates="embeddings")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    permisos_csv: Mapped[str] = mapped_column(Text, default="")  # lista simple separada por comas

    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    nombre_completo: Mapped[str | None] = mapped_column(String(150), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"), nullable=True)
    role: Mapped["Role | None"] = relationship(back_populates="users")

    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Segundo factor (TOTP): secreto cifrado en reposo (app.core.security/
    # encrypt_value) y flag de activación. None + False = 2FA deshabilitado.
    totp_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    usuario: Mapped[str | None] = mapped_column(String(80), nullable=True)
    accion: Mapped[str] = mapped_column(String(120), nullable=False)
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecognitionEvent(Base):
    """Historial de reconocimientos: imagen estática, video o webcam en vivo."""
    __tablename__ = "recognition_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    origen: Mapped[str] = mapped_column(String(20))  # "imagen" | "video" | "webcam"
    person_uuid: Mapped[str | None] = mapped_column(ForeignKey("persons.uuid"), nullable=True)
    confianza: Mapped[float | None] = mapped_column(Float, nullable=True)
    distancia: Mapped[float | None] = mapped_column(Float, nullable=True)
    det_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    imagen_evidencia_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    usuario: Mapped[str | None] = mapped_column(String(80), nullable=True)

    person: Mapped["Person | None"] = relationship()


class VideoJob(Base):
    """Un trabajo de análisis sobre un archivo de video concreto."""
    __tablename__ = "video_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    nombre_archivo: Mapped[str] = mapped_column(String(255), nullable=False)

    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    duracion_seg: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frames_procesados: Mapped[int] = mapped_column(Integer, default=0)

    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    # "pendiente" | "procesando" | "completado" | "error" | "cancelado"
    mensaje_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    usuario: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    fecha_finalizacion: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    detections: Mapped[list["VideoDetection"]] = relationship(
        back_populates="video_job", cascade="all, delete-orphan"
    )

    @property
    def progreso_pct(self) -> float:
        if not self.total_frames:
            return 0.0
        return round(min(100.0, (self.frames_procesados / self.total_frames) * 100), 1)


class VideoDetection(Base):
    """Un rostro detectado (y opcionalmente reconocido) en un frame muestreado de un video."""
    __tablename__ = "video_detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_job_id: Mapped[int] = mapped_column(ForeignKey("video_jobs.id"), index=True)

    frame_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    timestamp_seg: Mapped[float] = mapped_column(Float, nullable=False)

    person_uuid: Mapped[str | None] = mapped_column(ForeignKey("persons.uuid"), nullable=True)
    confianza: Mapped[float | None] = mapped_column(Float, nullable=True)
    distancia: Mapped[float | None] = mapped_column(Float, nullable=True)
    det_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    facial_attributes: Mapped[str | None] = mapped_column(Text, nullable=True)

    bbox_x1: Mapped[float] = mapped_column(Float)
    bbox_y1: Mapped[float] = mapped_column(Float)
    bbox_x2: Mapped[float] = mapped_column(Float)
    bbox_y2: Mapped[float] = mapped_column(Float)

    evidencia_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    video_job: Mapped["VideoJob"] = relationship(back_populates="detections")
    person: Mapped["Person | None"] = relationship()

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.bbox_x1, self.bbox_y1, self.bbox_x2, self.bbox_y2)

    @property
    def timestamp_fmt(self) -> str:
        m, s = divmod(int(self.timestamp_seg), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class SecureSetting(Base):
    """
    Configuración sensible cifrada en reposo (ver app/core/security.py).
    El valor jamás se guarda en texto plano; solo se descifra en memoria
    cuando se solicita explícitamente.
    """
    __tablename__ = "secure_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)

    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    fecha_modificacion: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class UserPreference(Base):
    """Preferencias de interfaz por usuario (p. ej. idioma en/es)."""
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(5), default="en")

    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    fecha_modificacion: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped["User"] = relationship()


class RememberedSession(Base):
    """
    Token de 'recordar sesión'. Nunca se guarda el token crudo, solo su hash
    SHA-256. Expira según ``settings.security.remember_credentials_days``
    (0 = sin expiración). Un usuario tiene a lo sumo un token activo.
    """
    __tablename__ = "remembered_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()
