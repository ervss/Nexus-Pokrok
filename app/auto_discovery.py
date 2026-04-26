"""
Auto-discovery service for continuous video content monitoring and import.
Implements intelligent filtering, quality scoring, and automated imports.
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.database import get_db, DiscoveryProfile, DiscoveryNotification, Video, DiscoveredVideo
from app.search_engine import ExternalSearchEngine
from app.services import VIPVideoProcessor

logger = logging.getLogger(__name__)


class AutoDiscoveryWorker:
    """
    Manages automated video discovery based on user-defined profiles.
    """

    def __init__(self):
        """Initialize the auto-discovery worker."""
        self.running_profiles = set()  # Track currently running profile IDs

    async def run_profile(self, profile_id: int, db: Session):
        """
        Execute a single discovery profile.

        Args:
            profile_id: ID of the discovery profile to run
            db: Database session
        """
        # Prevent concurrent runs of the same profile
        if profile_id in self.running_profiles:
            logger.warning(f"Profile {profile_id} is already running, skipping")
            return

        self.running_profiles.add(profile_id)

        try:
            # Load profile
            profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()

            if not profile:
                logger.error(f"Discovery profile {profile_id} not found")
                return

            if not profile.enabled:
                logger.info(f"Profile '{profile.name}' is disabled, skipping")
                return

            logger.info(f"Running discovery profile: {profile.name}")

            # Execute search
            results = await self._search_with_profile(profile)

            # Filter results based on profile criteria
            filtered_results = self._filter_results(results, profile)

            logger.info(f"Profile '{profile.name}': Found {len(results)} results, {len(filtered_results)} after filtering")

            # Update profile statistics
            profile.last_run = datetime.utcnow()
            profile.total_runs += 1
            profile.total_found += len(filtered_results)

            # Save discovered videos to review table
            if filtered_results:
                self._save_discovered_videos(filtered_results, profile, db)

            # Import or notify
            if profile.auto_import and filtered_results:
                imported_count = await self._import_videos(filtered_results, profile, db)
                profile.total_imported += imported_count

                # Create notification
                self._create_notification(
                    db,
                    profile,
                    "import_complete",
                    f"Auto-imported {imported_count} videos",
                    imported_count
                )

            elif filtered_results:
                # Notify only mode
                self._create_notification(
                    db,
                    profile,
                    "new_matches",
                    f"Found {len(filtered_results)} new matches",
                    len(filtered_results)
                )

            db.commit()
            logger.info(f"Profile '{profile.name}' completed successfully")

        except Exception as e:
            logger.error(f"Error running profile {profile_id}: {e}", exc_info=True)

            # Create error notification
            try:
                profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()
                if profile:
                    self._create_notification(
                        db,
                        profile,
                        "error",
                        f"Error: {str(e)}",
                        0
                    )
                    db.commit()
            except Exception as notify_error:
                logger.error(f"Failed to create error notification: {notify_error}")

        finally:
            self.running_profiles.discard(profile_id)

    async def _search_with_profile(self, profile: DiscoveryProfile) -> List[Dict[str, Any]]:
        """
        Perform search using profile settings.

        Args:
            profile: Discovery profile with search parameters

        Returns:
            List of search results
        """
        keywords = profile.keywords.strip()
        if not keywords:
            logger.warning(f"Profile '{profile.name}' has no keywords, skipping search")
            return []

        try:
            engine = ExternalSearchEngine()
            raw_sources = profile.sources or []
            if isinstance(raw_sources, list) and raw_sources:
                results = await engine.search_sources(keywords, raw_sources)
            else:
                results = await engine.search(keywords)

            # Limit results for filtering
            return results[:profile.max_results * 3]

        except Exception as e:
            logger.error(f"Search failed for profile '{profile.name}': {e}")
            return []

    def _filter_results(self, results: List[Dict[str, Any]], profile: DiscoveryProfile) -> List[Dict[str, Any]]:
        """
        Filter search results based on profile criteria.

        Args:
            results: Raw search results
            profile: Discovery profile with filter settings

        Returns:
            Filtered results list
        """
        filtered = []

        # Parse exclude keywords
        exclude_keywords = [kw.strip().lower() for kw in profile.exclude_keywords.split(',') if kw.strip()]

        for result in results:
            # Check exclude keywords
            title_lower = result.get('title', '').lower()
            if any(exclude in title_lower for exclude in exclude_keywords):
                continue

            # Check duration filters
            duration = result.get('duration', 0)
            if profile.min_duration and duration < profile.min_duration:
                continue
            if profile.max_duration and duration > profile.max_duration:
                continue

            # Check quality filters (if metadata available)
            height = result.get('height', 0)
            if profile.min_height and height > 0 and height < profile.min_height:
                continue
            if profile.max_height and height > 0 and height > profile.max_height:
                continue

            # Check aspect ratio (if specified)
            if profile.aspect_ratio and profile.aspect_ratio != "any":
                result_aspect = self._calculate_aspect_ratio(result.get('width', 0), result.get('height', 0))
                if result_aspect and result_aspect != profile.aspect_ratio:
                    continue

            # Check for duplicates in database
            if self._is_duplicate(result):
                continue

            filtered.append(result)

            # Respect max_results limit
            if len(filtered) >= profile.max_results:
                break

        return filtered

    def _calculate_aspect_ratio(self, width: int, height: int) -> Optional[str]:
        """
        Calculate aspect ratio from dimensions.

        Args:
            width: Video width
            height: Video height

        Returns:
            Aspect ratio string (e.g., "16:9") or None
        """
        if not width or not height:
            return None

        ratio = width / height

        # Common aspect ratios with tolerance
        if 1.7 <= ratio <= 1.8:
            return "16:9"
        elif 0.55 <= ratio <= 0.58:
            return "9:16"
        elif 1.3 <= ratio <= 1.35:
            return "4:3"
        elif 0.95 <= ratio <= 1.05:
            return "1:1"

        return None

    def _is_duplicate(self, result: Dict[str, Any]) -> bool:
        """
        Check if video URL already exists in database.

        Args:
            result: Search result dict

        Returns:
            True if duplicate exists
        """
        # This is a basic check; more sophisticated duplicate detection can be added
        url = result.get('url')
        if not url:
            return False

        try:
            from app.database import SessionLocal
            db = SessionLocal()
            try:
                existing = db.query(Video).filter(Video.url == url).first()
                return existing is not None
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error checking duplicate: {e}")
            return False

    async def _import_videos(self, results: List[Dict[str, Any]], profile: DiscoveryProfile, db: Session) -> int:
        """
        Import filtered videos into the database.

        Args:
            results: Filtered search results
            profile: Discovery profile
            db: Database session

        Returns:
            Number of successfully imported videos
        """
        imported_count = 0
        batch_name = f"{profile.batch_prefix}-{profile.name}-{datetime.utcnow().strftime('%Y%m%d')}"

        for result in results:
            try:
                # Create video entry
                video = Video(
                    title=result.get('title', 'Untitled'),
                    url=result.get('url'),
                    source_url=result.get('source_url', result.get('url')),
                    thumbnail_path=result.get('thumbnail', ''),
                    duration=result.get('duration', 0),
                    width=result.get('width', 0),
                    height=result.get('height', 0),
                    batch_name=batch_name,
                    storage_type='remote',
                    status='pending'
                )

                db.add(video)
                db.flush()  # Get video.id

                # Queue for background processing (thumbnail generation, etc.)
                # This will be handled by the existing processing system
                asyncio.create_task(self._process_video_async(video.id))

                imported_count += 1

            except Exception as e:
                logger.error(f"Failed to import video '{result.get('title')}': {e}")
                continue

        return imported_count

    async def _process_video_async(self, video_id: int):
        """
        Asynchronously process a video (thumbnails, metadata extraction).

        Args:
            video_id: Video database ID
        """
        try:
            # Use existing video processing service in a thread to avoid blocking
            processor = VIPVideoProcessor()
            await asyncio.to_thread(processor.process_single_video, video_id)
        except Exception as e:
            logger.error(f"Failed to process video {video_id}: {e}")

    def _save_discovered_videos(
        self,
        results: List[Dict[str, Any]],
        profile: DiscoveryProfile,
        db: Session
    ):
        """
        Save discovered videos to the review table.

        Args:
            results: Filtered search results
            profile: Discovery profile
            db: Database session
        """
        try:
            for result in results:
                # Check if already saved
                existing = db.query(DiscoveredVideo).filter(
                    DiscoveredVideo.profile_id == profile.id,
                    DiscoveredVideo.url == result.get('url')
                ).first()

                if not existing:
                    discovered = DiscoveredVideo(
                        profile_id=profile.id,
                        profile_name=profile.name,
                        title=result.get('title', 'Untitled'),
                        url=result.get('url'),
                        source_url=result.get('source_url', result.get('url')),
                        thumbnail=result.get('thumbnail', ''),
                        duration=result.get('duration', 0),
                        width=result.get('width', 0),
                        height=result.get('height', 0),
                        source=result.get('source', 'Unknown'),
                        imported=False
                    )
                    db.add(discovered)

            logger.info(f"Saved {len(results)} discovered videos for profile '{profile.name}'")
        except Exception as e:
            logger.error(f"Failed to save discovered videos: {e}")

    def _create_notification(
        self,
        db: Session,
        profile: DiscoveryProfile,
        notification_type: str,
        message: str,
        video_count: int
    ):
        """
        Create a discovery notification.

        Args:
            db: Database session
            profile: Discovery profile
            notification_type: Type of notification
            message: Notification message
            video_count: Number of videos involved
        """
        try:
            notification = DiscoveryNotification(
                profile_id=profile.id,
                profile_name=profile.name,
                notification_type=notification_type,
                message=message,
                video_count=video_count,
                read=False
            )
            db.add(notification)
        except Exception as e:
            logger.error(f"Failed to create notification: {e}")


# Global worker instance
_worker: Optional[AutoDiscoveryWorker] = None


def get_worker() -> AutoDiscoveryWorker:
    """
    Get the global auto-discovery worker instance.

    Returns:
        AutoDiscoveryWorker instance
    """
    global _worker
    if _worker is None:
        _worker = AutoDiscoveryWorker()
    return _worker


async def run_discovery_profile(profile_id: int):
    """
    Run a discovery profile by ID.
    This is the entry point for scheduled jobs.

    Args:
        profile_id: ID of the discovery profile to run
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        worker = get_worker()
        await worker.run_profile(profile_id, db)
    finally:
        db.close()
