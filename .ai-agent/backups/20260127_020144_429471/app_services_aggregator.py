from app.database import (
    ContentItem, Tag, User, UserSettings, UserInterest, UserProgress,
)
from app.database import (
    ContentItem, Tag, User, UserSettings, UserInterest, UserProgress, 
)
from app.database import (
    ContentItem, Tag, get_db_session, SessionLocal,
    User, UserInterest, UserProgress, FavoriteContent
)
from app.database import ContentItem, Tag, get_db_session, SessionLocal, User, UserInterest, UserProgress
from app.database import ContentItem, Tag, get_db_session, SessionLocal, User, UserInterest, UserProgress, FavoriteContent
from app.database import SearchQuery
from datetime import datetime, timedelta
from datetime import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from sqlalchemy import or_
from sqlalchemy import or_, and_
from typing import Dict, List, Optional, Any
from typing import List, Dict, Any, Optional
from typing import List, Dict, Any, Optional, Tuple
from typing import List, Dict, Optional, Any
from typing import List, Dict, Optional, Any, Tuple
from typing import Optional
from typing import Tuple
from typing import Tuple, List, Dict, Any, Optional
import smtplib

import logging
import datetime
from collections import defaultdict
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Any, Tuple

from sqlalchemy import or_, and_, desc
from sqlalchemy.orm import Session

from app.database import (
    ContentItem, Tag, User, UserSettings, UserInterest, UserProgress,
    FavoriteContent, SearchQuery, get_db_session, SessionLocal
)
from app.sources.youtube import YouTubeSource
from app.sources.habr import HabrSource
from app.sources.coursera import CourseraSource
from app.config import settings

logger = logging.getLogger(__name__)

class ContentAggregator:
    """Aggregates content from all available sources."""

    def __init__(self, sources: List[Any] = None, db_session: Session = None):
        """Initialize aggregator with sources and database session."""
        self.sources = sources or self._get_available_sources()
        self.db_session = db_session or SessionLocal()

    def _get_available_sources(self) -> List[Any]:
        """Return list of enabled content sources based on configuration."""
        sources = []
        if settings.youtube_enabled and settings.youtube_api_key:
            sources.append(YouTubeSource())
        if settings.habr_enabled:
            sources.append(HabrSource())
        if settings.coursera_enabled and settings.coursera_api_key:
            sources.append(CourseraSource())
        return sources

    def get_top_interests(self, user_id: int, limit: int = 95) -> List[str]:
        """Получить топ интересов пользователя с учетом приоритета и времени использования."""
        try:
            interests = self.db_session.query(UserInterest).filter_by(
                user_id=user_id
            ).all()
            
            if not interests:
                return []
            
            now = datetime.utcnow()
            scored_interests = []
            
            for interest in interests:
                days_unused = (now - interest.last_used).days
                decay_factor = 0.9 ** (days_unused / 30)
                adjusted_priority = interest.priority * decay_factor
                
                scored_interests.append({
                    'tag_name': interest.tag_name,
                    'adjusted_priority': adjusted_priority
                })
            
            scored_interests.sort(key=lambda x: x['adjusted_priority'], reverse=True)
            top_tags = [item['tag_name'] for item in scored_interests[:limit]]
            return top_tags
            
        except Exception as e:
            logger.error(f"Ошибка получения топ интересов для пользователя {user_id}: {e}")
            fallback = self.db_session.query(UserInterest).filter_by(user_id=user_id).all()
            return [i.tag_name for i in fallback[:limit]]

    def _trim_interests_to_limit(self, user_id: int, limit: int = 95) -> None:
        """Автоматически обрезать интересы пользователя до указанного лимита."""
        try:
            all_interests = self.db_session.query(UserInterest).filter_by(user_id=user_id).all()
            if len(all_interests) <= limit:
                return

            now = datetime.utcnow()
            scored = []
            for interest in all_interests:
                days_unused = (now - interest.last_used).days
                decay_factor = 0.9 ** (days_unused / 30)
                adjusted_priority = interest.priority * decay_factor
                scored.append((interest, adjusted_priority))

            scored.sort(key=lambda x: x[1], reverse=True)
            to_delete = scored[limit:]
            if to_delete:
                for interest, _ in to_delete:
                    self.db_session.delete(interest)
                self.db_session.commit()
        except Exception as e:
            logger.error(f"Ошибка при обрезке интересов пользователя {user_id}: {e}")
            self.db_session.rollback()

    def aggregate_by_keywords(self, keywords: List[str], max_per_source: int = 20) -> List[ContentItem]:
        """Fetch content from all sources for given keywords."""
        keywords = [kw.strip().lower() for kw in keywords if kw and kw.strip()]

        if len(keywords) > 95:
                    logger.warning(f"Keywords list trimmed to 95 items (was {len(keywords)}). Habr API limit is 100.")
                    keywords = keywords[:95]
        if not keywords:
            return []
        
        results = []
        for source in self.sources:
            try:
                items = source.fetch_content(keywords, max_per_source)
                results.extend(items)
            except Exception as e:
                logger.error(f"Ошибка при запросе к источнику {source.__class__.__name__}: {e}")
        
        seen = set()
        unique_results = []
        for item in results:
            key = (item.source_id, item.platform)
            if key not in seen:
                seen.add(key)
                unique_results.append(item)
        return unique_results

    def save_content_items(self, content_items: List[ContentItem]) -> int:
        """Save new content items to database."""
        saved_count = 0
        tag_cache = {}
        for item in content_items:
            exists = self.db_session.query(ContentItem).filter_by(
                source_id=item.source_id, platform=item.platform
            ).first()
            if exists:
                continue

            new_tags = []
            for tag in (item.tags or []):
                tag_name = tag.name.lower() if tag.name else ""
                if tag_name not in tag_cache:
                    db_tag = self.db_session.query(Tag).filter_by(name=tag_name).first()
                    if not db_tag:
                        db_tag = Tag(name=tag_name)
                        self.db_session.add(db_tag)
                    tag_cache[tag_name] = db_tag
                new_tags.append(tag_cache[tag_name])
            item.tags = new_tags
            self.db_session.add(item)
            saved_count += 1
        self.db_session.commit()
        return saved_count

    def get_daily_digest(self, user_id: int, max_items: int = 15) -> List[ContentItem]:
        """Get personalized daily digest for user."""
        keywords = self.get_top_interests(user_id, 95)
        if not keywords:
            return self.db_session.query(ContentItem).order_by(ContentItem.published_at.desc()).limit(max_items).all()
        tag_filters = or_(*[Tag.name.ilike(f"%{kw}%") for kw in keywords])
        return self.db_session.query(ContentItem).join(ContentItem.tags).filter(tag_filters).order_by(ContentItem.published_at.desc()).limit(max_items).all()

    def update_content_for_user(self, user_id: int) -> int:
        """Fetch and save new content based on user interests."""
        keywords = self.get_top_interests(user_id, 95)
        if not keywords:
            return 0
        items = self.aggregate_by_keywords(keywords, max_per_source=50)
        return self.save_content_items(items)

    def search_content(self, keywords: List[str], max_results: int = 50) -> List[ContentItem]:
        """Search content items by keywords."""
        query = self.db_session.query(ContentItem).distinct()
        if keywords:
            conditions = [or_(ContentItem.title.ilike(f"%{k}%"), ContentItem.description.ilike(f"%{k}%"), Tag.name.ilike(f"%{k}%")) for k in keywords]
            query = query.outerjoin(ContentItem.tags).filter(or_(*conditions))
        return query.order_by(ContentItem.published_at.desc()).limit(max_results).all()

    def search_live(self, keywords: List[str], source_name: str = "habr", max_results: int = 50) -> List[ContentItem]:
        """Search content in real-time from specified source."""

        if len(keywords) > 95:
                    logger.warning(f"Live search keywords trimmed to 95 items (was {len(keywords)}).")
                    keywords = keywords[:95]
        source = next((s for s in self.sources if s.platform == source_name), None)
        if source and hasattr(source, 'fetch_content'):
            return source.fetch_content(keywords, max_results)
        return []

    def save_selected_items(self, items: List[ContentItem], source_name: str = "habr", user_id: Optional[int] = None) -> List[ContentItem]:
        """Save selected content items and update user interests."""
        saved = []
        for item in items:
            exists = self.db_session.query(ContentItem).filter_by(source_id=item.source_id, platform=item.platform).first()
            if not exists:
                self.db_session.add(item)
                saved.append(item)
            else:
                saved.append(exists)
        self.db_session.commit()
        if user_id:
            self.add_user_interests_from_content(user_id, saved)
        return saved

    def track_search_query(self, user_id: int, query: str) -> bool:
        """Сохранить поисковый запрос и обновить интересы."""
        try:
            sq = SearchQuery(user_id=user_id, query=query)
            self.db_session.add(sq)
            self.db_session.commit()
            keywords = [w.lower().strip() for w in query.split() if len(w) >= 3]
            for kw in keywords:
                interest = self.db_session.query(UserInterest).filter_by(user_id=user_id, tag_name=kw).first()
                if interest:
                    interest.mark_used(2)
                else:
                    self.db_session.add(UserInterest(user_id=user_id, tag_name=kw, priority=6))
            self.db_session.commit()
            self._trim_interests_to_limit(user_id, 95)
            return True
        except Exception:
            self.db_session.rollback()
            return False

    def add_user_interests_from_content(self, user_id: int, content_items: List[ContentItem]) -> None:
        """Обновить интересы на основе тегов статей."""
        for item in content_items:
            for tag in item.tags:
                interest = self.db_session.query(UserInterest).filter_by(user_id=user_id, tag_name=tag.name.lower()).first()
                if interest:
                    interest.mark_used(1)
                else:
                    self.db_session.add(UserInterest(user_id=user_id, tag_name=tag.name.lower(), priority=5))
        self.db_session.commit()
        self._trim_interests_to_limit(user_id, 95)

    def check_and_update_content_for_all_users(self) -> Dict[int, int]:
        """Update content for all users with auto-update enabled."""
        users = self.db_session.query(User).join(UserSettings).filter(UserSettings.auto_update_content == True).all()
        return {u.id: self.update_content_for_user(u.id) for u in users}

    def check_missed_digests(self) -> Dict[int, bool]:
        """Placeholder for missed digest check."""
        return {}

def update_all_content() -> Dict[str, int]:
    """Update content for all users."""
    session = SessionLocal()
    aggregator = ContentAggregator(db_session=session)
    results = {u.username: aggregator.update_content_for_user(u.id) for u in session.query(User).all()}
    session.close()
    return results