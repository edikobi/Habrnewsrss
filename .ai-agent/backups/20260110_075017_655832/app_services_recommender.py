import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, not_

from app.database import ContentItem, User, UserProgress, Tag, DifficultyLevel, get_db_session, SessionLocal
from app.config import settings

logger = logging.getLogger(__name__)

class ContentRecommender:
    """Recommends content based on user history and interests."""

    def __init__(self, db_session: Session = None):
        self.db_session = db_session or SessionLocal()

    def get_recommendations(self, user_id: int, max_recommendations: int = 5) -> List[ContentItem]:
        """Generate personalized recommendations."""
        user = self.db_session.query(User).get(user_id)
        if not user:
            return []

        completed_items = [p.content for p in user.progress if p.completed and p.content]
        completed_ids = [c.id for c in completed_items]
        completed_tags = list(set(t.name for c in completed_items for t in c.tags))

        # Strategies
        next_level = self._get_next_level_content(user_id, completed_tags)
        similar = self._get_similar_content(user_id, [c.id for c in completed_items if c.id])
        interests = self._get_content_based_on_interests(user_id)

        # Combine and filter
        all_recs = next_level + similar + interests
        unique_recs = []
        seen_ids = set(completed_ids)
        
        for item in all_recs:
            if item.id not in seen_ids:
                unique_recs.append(item)
                seen_ids.add(item.id)

        return unique_recs[:max_recommendations]

    def _get_next_level_content(self, user_id: int, completed_tags: List[str]) -> List[ContentItem]:
        """Find content that progresses the user's difficulty level."""
        # Simplified: find intermediate content for tags where user finished beginner
        return self.db_session.query(ContentItem).join(ContentItem.tags).filter(
            Tag.name.in_(completed_tags),
            ContentItem.difficulty != DifficultyLevel.BEGINNER
        ).limit(10).all()

    def _get_similar_content(self, user_id: int, liked_content_ids: List[int]) -> List[ContentItem]:
        """Find content similar to what user has already completed."""
        if not liked_content_ids:
            return []
        
        tags = self.db_session.query(Tag).join(Tag.content_items).filter(
            ContentItem.id.in_(liked_content_ids)
        ).all()
        tag_names = [t.name for t in tags]
        
        return self.db_session.query(ContentItem).join(ContentItem.tags).filter(
            Tag.name.in_(tag_names)
        ).limit(10).all()

    def _get_content_based_on_interests(self, user_id: int) -> List[ContentItem]:
        """Find content matching user's explicit interests."""
        user = self.db_session.query(User).get(user_id)
        interest_tags = [i.tag_name for i in user.interests]
        
        return self.db_session.query(ContentItem).join(ContentItem.tags).filter(
            Tag.name.in_(interest_tags)
        ).order_by(ContentItem.added_at.desc()).limit(10).all()