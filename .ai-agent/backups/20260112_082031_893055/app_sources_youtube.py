import datetime
import re
from typing import List, Dict, Any, Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging

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

