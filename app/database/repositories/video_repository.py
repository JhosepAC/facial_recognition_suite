from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import VideoJob, VideoDetection


class VideoJobRepository:
    """Acceso a datos de VideoJob y VideoDetection."""

    def __init__(self, session: Session):
        self.session = session

    # --- VideoJob -------------------------------------------------- #
    def add_job(self, job: VideoJob) -> VideoJob:
        self.session.add(job)
        self.session.flush()
        return job

    def get_job(self, job_id: int) -> VideoJob | None:
        return self.session.get(VideoJob, job_id)

    def list_jobs(self, limit: int = 100) -> Sequence[VideoJob]:
        stmt = select(VideoJob).order_by(VideoJob.fecha_creacion.desc()).limit(limit)
        return self.session.execute(stmt).scalars().all()

    def delete_job(self, job_id: int) -> bool:
        job = self.get_job(job_id)
        if job is None:
            return False
        self.session.delete(job)
        return True

    # --- VideoDetection ---------------------------------------------- #
    def add_detection(self, detection: VideoDetection) -> VideoDetection:
        self.session.add(detection)
        self.session.flush()
        return detection

    def list_detections(self, job_id: int) -> Sequence[VideoDetection]:
        stmt = (
            select(VideoDetection)
            .where(VideoDetection.video_job_id == job_id)
            .order_by(VideoDetection.frame_number)
        )
        return self.session.execute(stmt).scalars().all()

    def count_detections(self, job_id: int) -> int:
        return (
            self.session.query(VideoDetection)
            .filter(VideoDetection.video_job_id == job_id)
            .count()
        )
