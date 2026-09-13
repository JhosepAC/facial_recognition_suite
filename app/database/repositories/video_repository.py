"""Data access for VideoJob and VideoDetection entities."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import VideoJob, VideoDetection


class VideoJobRepository:
    """Data access for VideoJob and VideoDetection."""

    def __init__(self, session: Session):
        """Initialize the repository.

        Args:
            session: Active SQLAlchemy session.
        """
        self.session = session

    def add_job(self, job: VideoJob) -> VideoJob:
        """Add a new video job.

        Args:
            job: VideoJob to persist.

        Returns:
            The persisted job.
        """
        self.session.add(job)
        self.session.flush()
        return job

    def get_job(self, job_id: int) -> VideoJob | None:
        """Get a video job by ID.

        Args:
            job_id: Job identifier.

        Returns:
            VideoJob or None if not found.
        """
        return self.session.get(VideoJob, job_id)

    def list_jobs(self, limit: int = 100) -> Sequence[VideoJob]:
        """List recent video jobs ordered by creation date.

        Args:
            limit: Maximum number of results.

        Returns:
            Sequence of VideoJob objects.
        """
        stmt = select(VideoJob).order_by(VideoJob.fecha_creacion.desc()).limit(limit)
        return self.session.execute(stmt).scalars().all()

    def delete_job(self, job_id: int) -> bool:
        """Delete a video job by ID.

        Args:
            job_id: Job identifier.

        Returns:
            True if deleted, False if not found.
        """
        job = self.get_job(job_id)
        if job is None:
            return False
        self.session.delete(job)
        return True

    def add_detection(self, detection: VideoDetection) -> VideoDetection:
        """Add a video detection.

        Args:
            detection: VideoDetection to persist.

        Returns:
            The persisted detection.
        """
        self.session.add(detection)
        self.session.flush()
        return detection

    def list_detections(self, job_id: int) -> Sequence[VideoDetection]:
        """List detections for a job ordered by frame number.

        Args:
            job_id: Parent job identifier.

        Returns:
            Sequence of VideoDetection objects.
        """
        stmt = (
            select(VideoDetection)
            .where(VideoDetection.video_job_id == job_id)
            .order_by(VideoDetection.frame_number)
        )
        return self.session.execute(stmt).scalars().all()

    def count_detections(self, job_id: int) -> int:
        """Count detections for a job.

        Args:
            job_id: Parent job identifier.

        Returns:
            Number of detections.
        """
        return (
            self.session.query(VideoDetection)
            .filter(VideoDetection.video_job_id == job_id)
            .count()
        )
