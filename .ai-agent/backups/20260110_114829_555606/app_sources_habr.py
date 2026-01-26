from typing import List, Dict, Any

import datetime
import feedparser
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.sources.base import ContentSource
from app.database import ContentItem, Tag, ContentType, DifficultyLevel
from app.config import settings

class HabrSource(ContentSource):
    """Habr RSS feed content source."""
    
    RSS_URL = "https://habr.com/ru/rss/all/all/"

    def __init__(self):
        super().__init__(name="Habr", platform="habr", content_type=ContentType.HABR_ARTICLE)

    def fetch_content(self, keywords: List[str], max_results: int = 30) -> List[ContentItem]:
        """Fetch articles from Habr RSS."""
        try:
            feed = feedparser.parse(self.RSS_URL)
            content_items = []
            
            for entry in feed.entries:
                title = entry.title
                summary = entry.summary
                
                if not any(kw.lower() in title.lower() or kw.lower() in summary.lower() for kw in keywords):
                    continue
                
                tags = self._extract_tags(entry)
                description = self._clean_html(summary)
                
                # Estimate difficulty
                difficulty = DifficultyLevel.INTERMEDIATE
                if any(kw in title.lower() for kw in ["основы", "введение", "новичков"]):
                    difficulty = DifficultyLevel.BEGINNER
                elif any(kw in title.lower() for kw in ["сложные", "архитектура", "внутреннее устройство"]):
                    difficulty = DifficultyLevel.ADVANCED

                source_data = {
                    'id': entry.id,
                    'title': title,
                    'description': description,
                    'url': entry.link,
                    'published_at': datetime.datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') else None,
                    'difficulty': difficulty,
                    'duration_minutes': 10 # Default for articles
                }
                
                content_items.append(self._create_content_item(source_data, tags))
                if len(content_items) >= max_results:
                    break
                    
            return content_items
        except Exception as e:
            print(f"Habr RSS error: {e}")
            return []

    def search_live(self, keywords: List[str], max_results: int = 30, session: Optional[Session] = None) -> List[ContentItem]:
        """Search Habr articles in real-time via RSS and return ContentItem objects without saving to database."""
        try:
            articles = self.fetch_content(keywords, max_results)
            if not session:
                return articles

            filtered_articles = []
            for item in articles:
                exists = session.query(ContentItem).filter_by(
                    source_id=item.source_id,
                    platform=self.platform
                ).first()
                if not exists:
                    filtered_articles.append(item)
            return filtered_articles
        except Exception as e:
            print(f"Habr live search error: {e}")
            return []

    def save_selected_items(self, items: List[ContentItem], session: Session) -> List[ContentItem]:
        """Save selected ContentItem objects to database, handling duplicate detection."""
        saved_items = []
        try:
            for item in items:
                exists = session.query(ContentItem).filter_by(
                    source_id=item.source_id,
                    platform=self.platform
                ).first()

                if not exists:
                    new_tags = []
                    for tag in (item.tags or []):
                        db_tag = session.query(Tag).filter_by(name=tag.name).first()
                        if not db_tag:
                            db_tag = Tag(name=tag.name)
                            session.add(db_tag)
                        new_tags.append(db_tag)
                    item.tags = new_tags
                    session.add(item)
                    saved_items.append(item)

            session.commit()
            return saved_items
        except Exception as e:
            session.rollback()
            print(f"Error saving Habr items: {e}")
            return []

    def _extract_tags(self, entry: Dict[str, Any]) -> List[Tag]:
        """Extract tags from RSS entry."""
        tag_names = set()
        if hasattr(entry, 'tags'):
            for t in entry.tags:
                tag_names.add(t.term)
        return [Tag(name=name) for name in tag_names]

    def _clean_html(self, html: str) -> str:
        """Remove HTML tags and truncate text."""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=' ')
        return text[:500] + "..." if len(text) > 500 else text