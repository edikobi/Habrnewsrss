from typing import Dict, List, Optional, Any
from typing import List, Dict, Any, Optional
from typing import Tuple
from typing import Tuple, List, Dict, Any, Optional

import datetime
import logging
import smtplib
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import ContentItem, Tag, get_db_session, SessionLocal, User, UserInterest, UserProgress
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

    def aggregate_by_keywords(self, keywords: List[str], max_per_source: int = 20) -> List[ContentItem]:
        """Fetch content from all sources for given keywords."""
        results = []
        for source in self.sources:
            items = source.fetch_content(keywords, max_per_source)
            results.extend(items)
        
        # Deduplicate
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
        for item in content_items:
            # Check for duplicates by source_id and platform
            exists = self.db_session.query(ContentItem).filter_by(
                source_id=item.source_id, 
                platform=item.platform
            ).first()

            if not exists:
                # Handle tags: find existing or add new
                new_tags = []
                for tag in (item.tags or []):
                    try:
                        db_tag = self.db_session.query(Tag).filter_by(name=tag.name).first()
                        if not db_tag:
                            db_tag = Tag(name=tag.name)
                            self.db_session.add(db_tag)
                        new_tags.append(db_tag)
                    except Exception as e:
                        logger.error(f"Error processing tag {tag.name}: {e}")
                        continue

                item.tags = new_tags
                self.db_session.add(item)
                saved_count += 1

        try:
            self.db_session.commit()
        except Exception as e:
            self.db_session.rollback()
            logger.error(f"Error committing transaction in save_content_items: {e}")
            # Return saved_count even on commit error as items were added to session
            return saved_count

        return saved_count

    def get_daily_digest(self, user_id: int, max_items: int = 10) -> List[ContentItem]:
        """Get personalized daily digest for user."""
        user = self.db_session.query(User).get(user_id)
        if not user:
            return []
            
        keywords = [interest.tag_name for interest in user.interests]
        if not keywords:
            return []
            
        # Get content matching keywords
        content = self.db_session.query(ContentItem).join(ContentItem.tags).filter(
            Tag.name.in_(keywords)
        ).all()
        
        # Filter out completed
        completed_ids = [p.content_id for p in user.progress if p.completed]
        digest = [item for item in content if item.id not in completed_ids]
        
        # Sort by relevance (number of matching tags)
        digest.sort(key=lambda x: len([t for t in x.tags if t.name in keywords]), reverse=True)
        
        return digest[:max_items]

    def update_content_for_user(self, user_id: int) -> int:
        """Fetch and save new content based on user interests."""
        user = self.db_session.query(User).get(user_id)
        if not user:
            return 0
        
        keywords = [interest.tag_name for interest in user.interests]
        if not keywords:
            return 0
            
        items = self.aggregate_by_keywords(keywords)
        return self.save_content_items(items)

    def search_content(self, keywords: List[str], source_filter: Optional[str] = None, difficulty_filter: Optional[str] = None, max_results: int = 50) -> List[ContentItem]:
        """Search content items by keywords with optional source and difficulty filters."""
        try:
            query = self.db_session.query(ContentItem)

            # Apply keyword search
            if keywords:
                keyword_conditions = []
                for keyword in keywords:
                    keyword_lower = keyword.lower()
                    keyword_conditions.append(
                        or_(
                            ContentItem.title.ilike(f'%{keyword_lower}%'),
                            ContentItem.description.ilike(f'%{keyword_lower}%')
                        )
                    )
                if keyword_conditions:
                    query = query.filter(or_(*keyword_conditions))

            # Apply source filter
            if source_filter and source_filter.lower() != 'all':
                query = query.filter(ContentItem.platform == source_filter.lower())

            # Apply difficulty filter
            if difficulty_filter and difficulty_filter.lower() != 'all':
                query = query.filter(ContentItem.difficulty == difficulty_filter.lower())

            # Order by published date (newest first)
            query = query.order_by(ContentItem.published_at.desc())

            # Limit results
            return query.limit(max_results).all()

        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def search_live(self, keywords: List[str], source_name: str = "habr", max_results: int = 50) -> List[ContentItem]:
        """Search content in real-time from specified source without saving to database."""
        try:
            source = next((s for s in self.sources if s.platform == source_name), None)
            if not source:
                return []

            if hasattr(source, 'search_live'):
                return source.search_live(keywords, max_results, self.db_session)
            return []
        except Exception as e:
            logger.error(f"Live search error: {e}")
            return []

    def save_selected_items(self, items: List[ContentItem], source_name: str = "habr") -> int:
        """Save selected content items from real-time search to database."""
        try:
            source = next((s for s in self.sources if s.platform == source_name), None)
            if not source:
                return 0

            if hasattr(source, 'save_selected_items'):
                saved = source.save_selected_items(items, self.db_session)
                return len(saved)
            return 0
        except Exception as e:
            logger.error(f"Error saving selected items: {e}")
            return 0

    def send_email_digest(self, user_id: int, items: List[ContentItem]) -> bool:
        """Send daily digest email to user with recommended content items."""
        from app.services.email_sender import EmailSender

        user = self.db_session.query(User).get(user_id)
        if not user or not user.settings or not user.settings.email_digest:
            return False

        try:
            sender = EmailSender()
            return sender.send_digest(user, items)
        except Exception as e:
            logger.error(f"Email digest error: {e}")
            return False

    def check_missed_digests(self) -> Dict[int, bool]:
        """Check for missed digests for all users and send them if configured."""
        from app.database import UserSettings
        results = {}

        try:
            users_with_settings = self.db_session.query(User).join(UserSettings).filter(
                UserSettings.digest_enabled == True,
                UserSettings.missed_digest_send == True
            ).all()

            now = datetime.now()
            for user in users_with_settings:
                try:
                    # Simple logic: if updated_at is more than 24h ago and it's past digest_hour
                    last_update = user.settings.updated_at
                    if now - last_update > timedelta(days=1) and now.hour >= user.settings.digest_hour:
                        items = self.get_daily_digest(user.id)
                        if items:
                            success = self.send_email_digest(user.id, items)
                            results[user.id] = success
                            user.settings.updated_at = now
                except Exception as e:
                    logger.error(f"Error checking missed digest for user {user.id}: {e}")

            self.db_session.commit()
        except Exception as e:
            logger.error(f"Global missed digest check error: {e}")

        return results

    def track_user_preference(self, user_id: int, content_id: int, action_type: str) -> bool:
        """Отслеживание действия пользователя для улучшения рекомендаций."""
        valid_actions = ['favorite', 'complete', 'view', 'skip']
        if action_type not in valid_actions:
            return False

        try:
            # Logic to update user preference weights or log interaction
            # For now, we ensure the user exists and log the intent
            user = self.db_session.query(User).get(user_id)
            if not user:
                return False

            if action_type == 'favorite':
                fav = FavoriteContent(user_id=user_id, content_id=content_id)
                self.db_session.add(fav)

            self.db_session.commit()
            return True
        except Exception as e:
            logger.error(f"Error tracking user preference: {e}")
            self.db_session.rollback()
            return False

def update_all_content() -> Dict[str, int]:
    """Update content from all sources for all users."""
    session = SessionLocal()
    aggregator = ContentAggregator(db_session=session)
    users = session.query(User).all()
    results = {}
    for user in users:
        count = aggregator.update_content_for_user(user.id)
        results[user.username] = count
    session.close()
    return results