import datetime
import re
from typing import List, Dict, Any, Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging
from sqlalchemy.orm import Session

from app.sources.base import ContentSource
from app.database import ContentItem, Tag, ContentType, DifficultyLevel
from app.config import settings

class YouTubeSource(ContentSource):
    """YouTube content source using YouTube Data API."""

    API_SERVICE_NAME = "youtube"
    API_VERSION = "v3"

    def __init__(self):
        super().__init__(name="YouTube", platform="youtube", content_type=ContentType.YOUTUBE_VIDEO)
        self._client = None

    def _get_client(self):
        """Lazily create YouTube API client if API key is available."""
        logger = logging.getLogger(__name__)
        if self._client is not None:
            return self._client

        if not settings.youtube_api_key:
            logger.warning("YouTube API key not configured. YouTube source will be disabled.")
            return None

        try:
            self._client = build(self.API_SERVICE_NAME, self.API_VERSION,
                                developerKey=settings.youtube_api_key)
            return self._client
        except Exception as e:
            logger.error(f"Failed to create YouTube client: {e}")
            return None

    def fetch_content(self, keywords: List[str], max_results: int = 50) -> List[ContentItem]:
        """Fetch videos from YouTube based on keywords."""
        logger = logging.getLogger(__name__)
        client = self._get_client()
        if client is None:
            return []

        try:
            query = " OR ".join(keywords)
            search_response = client.search().list(
                part="snippet",
                q=query,
                maxResults=max_results,
                type="video",
                order="relevance"
            ).execute()

            video_ids = [item['id']['videoId'] for item in search_response.get('items', [])]
            if not video_ids:
                return []

            details_response = client.videos().list(
                part="contentDetails,snippet,statistics",
                id=",".join(video_ids)
            ).execute()

            content_items = []
            for item in details_response.get('items', []):
                snippet = item['snippet']
                content_details = item['contentDetails']

                title = snippet['title']
                description = snippet['description']

                tags = [Tag(name=kw) for kw in keywords if kw.lower() in title.lower() or kw.lower() in description.lower()]

                duration = self._estimate_duration(content_details['duration'])
                difficulty = self._extract_difficulty(title, description)

                source_data = {
                    'id': item['id'],
                    'title': title,
                    'description': description,
                    'full_text': description,  # Use description as full text for YouTube
                    'url': f"https://www.youtube.com/watch?v={item['id']}",
                    'published_at': datetime.datetime.strptime(snippet['publishedAt'], '%Y-%m-%dT%H:%M:%SZ'),
                    'difficulty': difficulty,
                    'duration_minutes': duration
                }
                content_items.append(self._create_content_item(source_data, tags))

            return content_items

        except HttpError as e:
            logger.error(f"YouTube API error: {e}")
            return []

    def _extract_difficulty(self, title: str, description: str) -> DifficultyLevel:
        """Estimate difficulty from title and description."""
        text = (title + " " + description).lower()
        if any(kw in text for kw in ["beginner", "basics", "introduction", "fundamentals", "start"]):
            return DifficultyLevel.BEGINNER
        if any(kw in text for kw in ["advanced", "expert", "master", "deep dive", "complex"]):
            return DifficultyLevel.ADVANCED
        return DifficultyLevel.INTERMEDIATE

    def _estimate_duration(self, duration_iso: str) -> Optional[int]:
        """Parse ISO 8601 duration string to minutes."""
        pattern = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')
        match = pattern.match(duration_iso)
        if not match:
            return None
        hours, minutes, seconds = match.groups()
        total_minutes = (int(hours or 0) * 60) + int(minutes or 0) + (1 if int(seconds or 0) > 30 else 0)
        return total_minutes

    def fetch_full_text(self, url: str) -> str:
        """Fetch full text content from YouTube video.

        For YouTube, attempts to get video captions/transcript.
        Falls back to video description if captions not available.
        """
        logger = logging.getLogger(__name__)
        try:
            # Extract video ID from URL
            video_id = url.split('v=')[-1].split('&')[0]
            client = self._get_client()
            if not client:
                return ""

            # First try to get video description
            response = client.videos().list(
                part="snippet",
                id=video_id
            ).execute()

            if not response.get('items'):
                return ""

            description = response['items'][0]['snippet']['description']

            # Try to get captions/transcript (if available)
            try:
                captions_response = client.captions().list(
                    part="snippet",
                    videoId=video_id
                ).execute()

                if captions_response.get('items'):
                    # For now, return description with note about captions availability
                    # In production, you would download and parse the caption track
                    logger.info(f"Captions available for video {video_id}, using description as full text")
            except Exception as caption_error:
                logger.debug(f"No captions available for video {video_id}: {caption_error}")

            return description

        except Exception as e:
            logger.error(f"Error fetching YouTube full text: {e}")
            return ""

    def save_selected_items(self, items: List[ContentItem], session: Session) -> List[ContentItem]:
        """Save selected YouTube ContentItem objects to database, handling duplicate detection and full text loading."""
        logger = logging.getLogger(__name__)
        saved_items = []
        tag_cache = {}
        try:
            for item in items:
                # Check for duplicates by source_id and platform
                exists = session.query(ContentItem).filter_by(
                    source_id=item.source_id, 
                    platform=self.platform
                ).first()

                if not exists:
                    # Ensure full text exists
                    if not item.full_text:
                        item.full_text = self.fetch_full_text(item.url)

                    new_tags = []
                    for tag in (item.tags or []):
                        tag_name = tag.name.lower() if tag.name else ""
                        if tag_name in tag_cache:
                            db_tag = tag_cache[tag_name]
                        else:
                            db_tag = session.query(Tag).filter_by(name=tag_name).first()
                            if not db_tag:
                                db_tag = Tag(name=tag_name)
                                session.add(db_tag)
                            tag_cache[tag_name] = db_tag
                        new_tags.append(db_tag)

                    item.tags = new_tags
                    session.add(item)
                    saved_items.append(item)

            session.commit()
            return saved_items
        except Exception as e:
            session.rollback()
            logger.error(f"Error saving YouTube items: {e}")
            return []

