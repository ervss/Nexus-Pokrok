"""
Background task scheduler for automated discovery and maintenance.
Uses APScheduler for flexible job scheduling with cron and interval support.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    Manages background tasks for auto-discovery, health checks, and maintenance.
    """

    def __init__(self):
        """Initialize the scheduler with async executor."""
        jobstores = {
            'default': MemoryJobStore()
        }
        executors = {
            'default': AsyncIOExecutor()
        }
        job_defaults = {
            'coalesce': True,  # Combine multiple missed runs into one
            'max_instances': 1,  # Only one instance of each job at a time
            'misfire_grace_time': 3600  # Jobs can be up to 1 hour late
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone='UTC'
        )

        self._running = False
        self._jobs: Dict[str, Dict[str, Any]] = {}  # Track job metadata

    def start(self):
        """Start the scheduler."""
        if not self._running:
            self.scheduler.start()
            self._running = True
            logger.info("Task scheduler started")

    def shutdown(self, wait: bool = True):
        """
        Shutdown the scheduler.

        Args:
            wait: If True, wait for all jobs to complete before shutting down
        """
        if self._running:
            self.scheduler.shutdown(wait=wait)
            self._running = False
            logger.info("Task scheduler shutdown")

    def add_interval_job(
        self,
        func: Callable,
        job_id: str,
        seconds: int,
        description: str = "",
        args: tuple = (),
        kwargs: dict = None,
        start_now: bool = False
    ):
        """
        Add a job that runs at regular intervals.

        Args:
            func: Async function to execute
            job_id: Unique identifier for the job
            seconds: Interval in seconds
            description: Human-readable description
            args: Positional arguments for the function
            kwargs: Keyword arguments for the function
            start_now: If True, run immediately then schedule
        """
        if kwargs is None:
            kwargs = {}

        try:
            # Remove existing job if present
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

            trigger = IntervalTrigger(seconds=seconds)

            self.scheduler.add_job(
                func,
                trigger=trigger,
                id=job_id,
                args=args,
                kwargs=kwargs,
                replace_existing=True
            )

            # Track job metadata
            self._jobs[job_id] = {
                'type': 'interval',
                'description': description,
                'interval_seconds': seconds,
                'added_at': datetime.utcnow(),
                'last_run': None,
                'run_count': 0
            }

            logger.info(f"Added interval job '{job_id}': {description} (every {seconds}s)")

            # Optionally run immediately
            if start_now:
                asyncio.create_task(self._run_job_now(func, args, kwargs, job_id))

        except Exception as e:
            logger.error(f"Failed to add interval job '{job_id}': {e}")
            raise

    def add_cron_job(
        self,
        func: Callable,
        job_id: str,
        cron_expression: str,
        description: str = "",
        args: tuple = (),
        kwargs: dict = None
    ):
        """
        Add a job with cron-style scheduling.

        Args:
            func: Async function to execute
            job_id: Unique identifier for the job
            cron_expression: Cron expression (e.g., "0 2 * * *" for 2 AM daily)
            description: Human-readable description
            args: Positional arguments for the function
            kwargs: Keyword arguments for the function
        """
        if kwargs is None:
            kwargs = {}

        try:
            # Remove existing job if present
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

            # Parse cron expression
            parts = cron_expression.split()
            if len(parts) != 5:
                raise ValueError("Cron expression must have 5 parts: minute hour day month day_of_week")

            minute, hour, day, month, day_of_week = parts

            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone='UTC'
            )

            self.scheduler.add_job(
                func,
                trigger=trigger,
                id=job_id,
                args=args,
                kwargs=kwargs,
                replace_existing=True
            )

            # Track job metadata
            self._jobs[job_id] = {
                'type': 'cron',
                'description': description,
                'cron_expression': cron_expression,
                'added_at': datetime.utcnow(),
                'last_run': None,
                'run_count': 0
            }

            logger.info(f"Added cron job '{job_id}': {description} (cron: {cron_expression})")

        except Exception as e:
            logger.error(f"Failed to add cron job '{job_id}': {e}")
            raise

    def remove_job(self, job_id: str):
        """
        Remove a scheduled job.

        Args:
            job_id: Job identifier to remove
        """
        try:
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                if job_id in self._jobs:
                    del self._jobs[job_id]
                logger.info(f"Removed job '{job_id}'")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to remove job '{job_id}': {e}")
            return False

    def pause_job(self, job_id: str):
        """Pause a job without removing it."""
        try:
            if self.scheduler.get_job(job_id):
                self.scheduler.pause_job(job_id)
                logger.info(f"Paused job '{job_id}'")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to pause job '{job_id}': {e}")
            return False

    def resume_job(self, job_id: str):
        """Resume a paused job."""
        try:
            if self.scheduler.get_job(job_id):
                self.scheduler.resume_job(job_id)
                logger.info(f"Resumed job '{job_id}'")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to resume job '{job_id}': {e}")
            return False

    async def run_job_now(self, job_id: str):
        """
        Manually trigger a job to run immediately.

        Args:
            job_id: Job identifier to run
        """
        job = self.scheduler.get_job(job_id)
        if not job:
            logger.error(f"Job '{job_id}' not found")
            return False

        try:
            # Run the job's function with its configured args
            await job.func(*job.args, **job.kwargs)
            self._update_job_stats(job_id)
            logger.info(f"Manually executed job '{job_id}'")
            return True
        except Exception as e:
            logger.error(f"Failed to manually run job '{job_id}': {e}")
            return False

    def get_jobs(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all scheduled jobs with their metadata.

        Returns:
            Dictionary of job_id -> job metadata
        """
        jobs_status = {}

        for job_id, metadata in self._jobs.items():
            job = self.scheduler.get_job(job_id)
            if job:
                jobs_status[job_id] = {
                    **metadata,
                    'next_run': job.next_run_time,
                    'pending': job.next_run_time is not None
                }
            else:
                jobs_status[job_id] = {
                    **metadata,
                    'next_run': None,
                    'pending': False
                }

        return jobs_status

    def _update_job_stats(self, job_id: str):
        """Update job execution statistics."""
        if job_id in self._jobs:
            self._jobs[job_id]['last_run'] = datetime.utcnow()
            self._jobs[job_id]['run_count'] = self._jobs[job_id].get('run_count', 0) + 1

    async def _run_job_now(self, func: Callable, args: tuple, kwargs: dict, job_id: str):
        """Helper to run a job immediately."""
        try:
            await func(*args, **kwargs)
            self._update_job_stats(job_id)
        except Exception as e:
            logger.error(f"Error running job '{job_id}' immediately: {e}")


# Global scheduler instance
_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    """
    Get the global scheduler instance, creating it if necessary.

    Returns:
        TaskScheduler instance
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler


def init_scheduler():
    """Initialize and start the global scheduler."""
    scheduler = get_scheduler()
    if not scheduler._running:
        scheduler.start()
    return scheduler


def shutdown_scheduler(wait: bool = True):
    """Shutdown the global scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=wait)
        _scheduler = None
