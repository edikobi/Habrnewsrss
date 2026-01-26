from app.database import (
    ContentItem, Tag, User, UserSettings, UserInterest, UserProgress,
    FavoriteContent, get_db_session, SessionLocal
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
from typing import Dict, List, Optional, Any
from typing import List, Dict, Any, Optional
from typing import List, Dict, Any, Optional, Tuple
from typing import List, Dict, Optional, Any
from typing import List, Dict, Optional, Any, Tuple
from typing import Tuple
from typing import Tuple, List, Dict, Any, Optional
import datetime
import smtplib

import logging
from collections import defaultdict
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Any, Tuple

from sqlalchemy import or_, and_
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
        """Save new content items to database with guaranteed full text loading."""
        saved_count = 0
        tag_cache = {}

        for item in content_items:
            # Check for duplicates by source_id and platform
            exists = self.db_session.query(ContentItem).filter_by(
                source_id=item.source_id, 
                platform=item.platform
            ).first()

            if exists:
                # Обновить поле updated_at у существующей записи
                exists.updated_at = datetime.utcnow()
                continue

            # Гарантировать загрузку полного текста
            if not item.full_text or item.full_text.strip() == "":
                source = next((s for s in self.sources if s.platform == item.platform), None)
                if source and hasattr(source, 'fetch_full_text'):
                    try:
                        full_text = source.fetch_full_text(item.url)
                        if full_text and full_text.strip():
                            item.full_text = full_text
                            logger.info(f"Загружен полный текст для {item.url}")
                        else:
                            logger.warning(f"Не удалось загрузить полный текст для {item.url}")
                            
                            # Fallback: если полный текст пустой, используем описание
                            if item.description and item.description.strip():
                                # Берём описание, но ограничиваем длину
                                item.full_text = item.description[:5000] + ("..." if len(item.description) > 5000 else "")
                                logger.info(f"Использовано описание как fallback для {item.url}")
                            else:
                                logger.warning(f"Не удалось получить контент для {item.url}")
                    except Exception as e:
                        logger.error(f"Ошибка загрузки полного текста для {item.url}: {e}")
                        
                        # Fallback в случае ошибки
                        if item.description and item.description.strip():
                            item.full_text = item.description[:5000] + ("..." if len(item.description) > 5000 else "")
                            logger.info(f"Использовано описание как fallback после ошибки для {item.url}")
                else:
                    logger.warning(f"Источник для платформы {item.platform} не найден или не поддерживает загрузку полного текста")
                    
                    # Fallback для неподдерживаемых источников
                    if item.description and item.description.strip():
                        item.full_text = item.description[:5000] + ("..." if len(item.description) > 5000 else "")
                        logger.info(f"Использовано описание как fallback для {item.url}")

            # Обработка тегов
            new_tags = []
            for tag in (item.tags or []):
                try:
                    # Normalize tag name to lowercase for consistency
                    tag_name = tag.name.lower() if tag.name else ""
                    if tag_name in tag_cache:
                        db_tag = tag_cache[tag_name]
                    else:
                        db_tag = self.db_session.query(Tag).filter_by(name=tag_name).first()
                        if not db_tag:
                            db_tag = Tag(name=tag_name)
                            self.db_session.add(db_tag)
                        tag_cache[tag_name] = db_tag
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
            return saved_count

        return saved_count

    def get_daily_digest(self, user_id: int, max_items: int = 15) -> List[ContentItem]:
        """Get personalized daily digest for user with fallback to fresh content."""
        try:
            user = self.db_session.query(User).get(user_id)

            if user:
                user.ensure_settings(self.db_session)
            if not user:
                return []

            keywords = [interest.tag_name.lower() for interest in user.interests]

            # Get content matching keywords or fallback if no interests
            if not keywords:
                return self.get_fallback_content(max_items)

            # Build a filter that matches ANY interest tag (case‑insensitive, partial)
            tag_filters = or_(*[Tag.name.ilike(f"%{kw}%") for kw in keywords])
            content = self.db_session.query(ContentItem).join(ContentItem.tags).filter(
                tag_filters
            ).order_by(ContentItem.published_at.desc()).all()

            # Filter out completed
            completed_ids = [p.content_id for p in user.progress if p.completed]
            digest = [item for item in content if item.id not in completed_ids]

            # If no matching content found, use fallback
            if not digest:
                return self.get_fallback_content(max_items)

            # Sort by relevance (number of matching tags)
            digest.sort(key=lambda x: len([t for t in x.tags if t.name.lower() in keywords]), reverse=True)

            return digest[:max_items]
        except Exception as e:
            logger.error(f"Error generating daily digest: {e}")
            return []

    def get_fallback_content(self, max_items: int = 15) -> List[ContentItem]:
        """Get fresh content as fallback when no interest-based content is available."""
        try:
            return self.db_session.query(ContentItem).order_by(
                ContentItem.published_at.desc()
            ).limit(max_items).all()
        except Exception as e:
            logger.error(f"Error getting fallback content: {e}")
            return []

    def update_content_for_user(self, user_id: int) -> int:
        """Fetch and save new content based on user interests with fallback search."""
        user = self.db_session.query(User).get(user_id)
        if not user:
            return 0

        keywords = [interest.tag_name for interest in user.interests]
        if not keywords:
            return 0

        # Увеличиваем лимит для получения большего количества статей
        items = self.aggregate_by_keywords(keywords, max_per_source=100)

        # Фильтруем только статьи, которых ещё нет в базе
        filtered_items = []
        for item in items:
            exists = self.db_session.query(ContentItem).filter_by(
                source_id=item.source_id,
                platform=item.platform
            ).first()
            if not exists:
                filtered_items.append(item)

        count = self.save_content_items(filtered_items)

        # Резервный поиск: если новых статей нет, ищем более старые, но еще не загруженные
        if count == 0:
            try:
                logger.info(f"Новых статей не найдено для пользователя {user_id}. Запуск резервного поиска старых статей...")
                
                # Увеличиваем лимит для получения большего количества статей (включая старые)
                backup_items = self.aggregate_by_keywords(keywords, max_per_source=200)
                
                # Фильтруем только статьи, которых ещё нет в базе
                backup_filtered = []
                for item in backup_items:
                    exists = self.db_session.query(ContentItem).filter_by(
                        source_id=item.source_id,
                        platform=item.platform
                    ).first()
                    if not exists:
                        backup_filtered.append(item)
                        if len(backup_filtered) >= 10:  # Ограничиваем 10 старыми статьями
                            break
                
                if backup_filtered:
                    backup_count = self.save_content_items(backup_filtered)
                    count += backup_count
                    logger.info(f"Загружено {backup_count} старых статей из резервного поиска для пользователя {user_id}")
            except Exception as e:
                logger.error(f"Ошибка резервного поиска для пользователя {user_id}: {e}")

        return count

    def search_content(self, keywords: List[str], source_filter: Optional[str] = None, difficulty_filter: Optional[str] = None, max_results: int = None) -> List[ContentItem]:
        """Search content items by keywords in title, description, and tags."""
        try:
            if max_results is None:
                max_results = settings.search_max_results

            query = self.db_session.query(ContentItem).distinct()

            if keywords:
                keyword_conditions = []
                for keyword in keywords:
                    keyword_lower = f"%{keyword.lower()}%"
                    keyword_conditions.append(
                        or_(
                            ContentItem.title.ilike(keyword_lower),
                            ContentItem.description.ilike(keyword_lower),
                            Tag.name.ilike(keyword_lower)
                        )
                    )
                if keyword_conditions:
                    query = query.outerjoin(ContentItem.tags).filter(or_(*keyword_conditions))

            if source_filter and source_filter.lower() != 'all':
                query = query.filter(ContentItem.platform == source_filter.lower())

            if difficulty_filter and difficulty_filter.lower() != 'all':
                query = query.filter(ContentItem.difficulty == difficulty_filter.lower())

            query = query.order_by(ContentItem.published_at.desc())
            return query.limit(max_results).all()
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def search_live(self, keywords: List[str], source_name: str = "habr", max_results: int = 50) -> List[ContentItem]:
        """Search content in real-time from specified source."""
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

    def save_selected_items(self, items: List[ContentItem], source_name: str = "habr") -> List[ContentItem]:
        """Save selected content items from real-time search to database and return saved objects."""
        try:
            source = next((s for s in self.sources if s.platform == source_name), None)
            if not source:
                return []
            if hasattr(source, 'save_selected_items'):
                saved = source.save_selected_items(items, self.db_session)
                
                # Если статьи не были сохранены (уже существуют), вернуть существующие статьи
                if not saved:
                    existing_items = []
                    for item in items:
                        existing = self.db_session.query(ContentItem).filter_by(
                            source_id=item.source_id,
                            platform=item.platform
                        ).first()
                        if existing:
                            existing_items.append(existing)
                    return existing_items
                
                return saved  # Возвращаем список объектов, а не количество
            return []
        except Exception as e:
            logger.error(f"Error saving selected items: {e}")
            return []

    def send_email_digest(self, user_id: int, items: List[ContentItem]) -> bool:
        """Send daily digest email to user."""
        from app.services.email_sender import EmailSender
        user = self.db_session.query(User).get(user_id)
        if user:
            user.ensure_settings(self.db_session)
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
        results = {}
        try:
            users_with_settings = self.db_session.query(User).join(UserSettings).filter(
                UserSettings.digest_enabled == True,
                UserSettings.missed_digest_send == True
            ).all()
            now = datetime.now()
            for user in users_with_settings:
                try:
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

    def _should_update_content(self, settings_obj: UserSettings, now: datetime) -> bool:
        """Определяет, нужно ли выполнить обновление контента для пользователя."""
        try:
            if not settings_obj.auto_update_content or not settings_obj.digest_enabled:
                return False

            last_update = settings_obj.last_content_update
            if last_update is None:
                return True

            # Вычисление запланированного времени на основе digest_hour
            scheduled_today = datetime.combine(last_update.date(), time(hour=settings_obj.digest_hour, minute=0))

            if last_update.time() >= time(hour=settings_obj.digest_hour, minute=0):
                scheduled_time = scheduled_today + timedelta(days=1)
            else:
                scheduled_time = scheduled_today

            if now >= scheduled_time:
                return True

            # Проверка интервала обновления
            interval_hours = settings.content_update_interval_hours
            next_by_interval = last_update + timedelta(hours=interval_hours)

            if now >= next_by_interval:
                return True

            return False
        except Exception as e:
            logger.error(f"Error in _should_update_content: {e}")
            return False

    def track_user_preference(self, user_id: int, content_id: int, action_type: str) -> bool:
        """Отслеживание действия пользователя для улучшения рекомендаций."""
        valid_actions = ['favorite', 'complete', 'view', 'skip']
        if action_type not in valid_actions:
            return False
        try:
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

    def track_search_query(self, user_id: int, query: str) -> bool:
            """Сохранить поисковый запрос пользователя для анализа интересов."""
            if not user_id or user_id <= 0 or not query or not query.strip():
                return False

            try:
                search_query = SearchQuery(user_id=user_id, query=query)
                self.db_session.add(search_query)
                self.db_session.commit()
                return True
            except Exception as e:
                logger.error(f"Error tracking search query: {e}")
                self.db_session.rollback()
                return False

    def check_and_update_content_for_all_users(self) -> Dict[int, int]:
        """Check for users needing content updates and update them individually with per-user commits."""
        now = datetime.now()
        users = self.db_session.query(User).join(UserSettings).filter(
            UserSettings.auto_update_content == True,
            UserSettings.digest_enabled == True
        ).all()
        results = {}

        for user in users:
            try:
                settings_obj = user.settings
                if self._should_update_content(settings_obj, now):
                    count = self.update_content_for_user(user.id)
                    results[user.id] = count
                    settings_obj.last_content_update = now
                    # Commit immediately after each user to ensure timestamp is saved
                    self.db_session.commit()
                    logger.info(f"Updated content for user {user.id}: {count} items")
            except Exception as e:
                logger.error(f"Error updating content for user {user.id}: {e}")
                self.db_session.rollback()
                # Continue to next user even if this one failed
                continue

        return results

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