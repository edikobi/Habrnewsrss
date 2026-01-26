import abc
import datetime
from typing import List, Dict, Any, Optional
from app.database import ContentItem, Tag, ContentType, DifficultyLevel
from app.config import settings

class ContentSource(abc.ABC):
    """Abstract base class for content sources."""

    def __init__(self, name: str, platform: str, content_type: ContentType):
        self.name = name
        self.platform = platform
        self.content_type = content_type

    @abc.abstractmethod
    def fetch_content(self, keywords: List[str], max_results: int) -> List[ContentItem]:
        """Fetch content from source based on keywords."""
        pass

    @abc.abstractmethod
    def fetch_full_text(self, url: str) -> str:
        """Fetch full text content from URL."""
        pass

    def _create_content_item(self, source_data: Dict[str, Any], tags: List[Tag]) -> ContentItem:
        """Create a ContentItem instance from raw source data."""
        source_id = str(source_data.get('id'))
        title = source_data.get('title', 'No Title')
        description = source_data.get('description', '')
        full_text = source_data.get('full_text')
        url = source_data.get('url', '')
        published_at = source_data.get('published_at', datetime.datetime.utcnow())
        difficulty = source_data.get('difficulty', DifficultyLevel.INTERMEDIATE)
        duration_minutes = source_data.get('duration_minutes')

        return ContentItem(
            source_id=source_id,
            title=title,
            description=description,
            full_text=full_text,
            url=url,
            content_type=self.content_type,
            platform=self.platform,
            difficulty=difficulty,
            duration_minutes=duration_minutes,
            published_at=published_at,
            tags=tags
        )