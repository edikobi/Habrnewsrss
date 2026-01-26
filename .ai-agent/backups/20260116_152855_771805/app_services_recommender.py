from app.database import ContentItem, User, UserProgress, Tag, DifficultyLevel, get_db_session, SessionLocal
from app.database import FavoriteContent
from sqlalchemy import and_, or_, not_
from sqlalchemy import desc

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, not_, desc

from app.database import ContentItem, User, UserProgress, Tag, DifficultyLevel, FavoriteContent, get_db_session, SessionLocal
from app.config import settings

logger = logging.getLogger(__name__)

class ContentRecommender:
    """Recommends content based on user history and interests."""

    def __init__(self, db_session: Session = None):
        self.db_session = db_session or SessionLocal()

    def get_recommendations(self, user_id: int, max_recommendations: int = 5) -> List[ContentItem]:
        """Generate personalized recommendations using weighted scoring and time decay."""
        user = self.db_session.query(User).get(user_id)
        if not user:
            return []

        # Get user preference weights
        weights = self.get_user_preference_weights(user_id)
        
        # Get completed items to filter them out
        completed_items = [p.content for p in user.progress if p.completed and p.content]
        completed_ids = {c.id for c in completed_items}
        completed_tags = list(set(t.name for c in completed_items for t in c.tags))

        # Extract favorite content tags
        favorites = self.db_session.query(FavoriteContent).filter_by(user_id=user_id).all()
        favorite_items = [fc.content for fc in favorites if fc.content]
        try:
            favorite_tags = list(set(t.name for c in favorite_items for t in c.tags))
        except AttributeError:
            favorite_tags = []

        # Strategies
        strategies = {
            'next_level': (self._get_next_level_content(user_id, completed_tags), weights.get('completed', 1.2)),
            'similar': (self._get_similar_content(user_id, [c.id for c in completed_items if c.id]), weights.get('similar', 1.0)),
            'interests': (self._get_content_based_on_interests(user_id), weights.get('interests', 1.5)),
            'favorites': (self._get_content_based_on_favorites(user_id, favorite_tags), weights.get('favorites', 2.0))
        }

        # Scoring
        scored_items = {}  # item_id -> (item, score, match_count)
        now = datetime.utcnow()

        for strat_name, (items, weight) in strategies.items():
            for item in items:
                if item.id in completed_ids:
                    continue
                
                if item.id not in scored_items:
                    # Base score calculation with time decay
                    days_old = (now - item.published_at).days if item.published_at else 30
                    time_decay = 0.95 ** (days_old / 7)
                    base_score = 1.0 * time_decay
                    scored_items[item.id] = [item, base_score * weight, 1]
                else:
                    scored_items[item.id][1] += 1.0 * weight
                    scored_items[item.id][2] += 1  # Increment match count

        # Apply multi-strategy bonus
        for item_data in scored_items.values():
            if item_data[2] > 1:  # Matched by multiple strategies
                item_data[1] *= 1.5

        # Sort by score and return
        sorted_items = sorted(scored_items.values(), key=lambda x: x[1], reverse=True)
        return [item[0] for item in sorted_items[:max_recommendations]]

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

    def _get_content_based_on_favorites(self, user_id: int, favorite_tags: List[str]) -> List[ContentItem]:
        """Find content matching tags from user's favorite items."""
        if not favorite_tags:
            return []

        completed_ids = self.db_session.query(UserProgress.content_id).filter(
            UserProgress.user_id == user_id,
            UserProgress.completed == True
        ).all()
        completed_ids = [r[0] for r in completed_ids]

        return self.db_session.query(ContentItem).join(ContentItem.tags).filter(
            Tag.name.in_(favorite_tags),
            not_(ContentItem.id.in_(completed_ids))
        ).limit(10).all()

    def get_interest_suggestions(self, user_id: int, max_suggestions: int = 10) -> List[str]:
        """Предложить интересы на основе избранного и завершенного контента пользователя."""
        try:
            user = self.db_session.query(User).get(user_id)
            if not user:
                return []

            # Get tags from favorites
            favorites = self.db_session.query(FavoriteContent).filter_by(user_id=user_id).all()
            fav_tags = []
            for f in favorites:
                if f.content:
                    fav_tags.extend([t.name for t in f.content.tags])

            # Get tags from completed
            completed = self.db_session.query(UserProgress).filter_by(user_id=user_id, completed=True).all()
            comp_tags = []
            for p in completed:
                if p.content:
                    comp_tags.extend([t.name for t in p.content.tags])

            # Analyze frequency
            all_tags = fav_tags + comp_tags
            tag_counts = {}
            for t in all_tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1

            # Filter out existing interests
            existing_interests = {i.tag_name for i in user.interests}
            suggestions = [t for t, c in sorted(tag_counts.items(), key=lambda x: x[1], reverse=True) 
                           if t not in existing_interests]

            return suggestions[:max_suggestions]
        except Exception as e:
            logger.error(f"Error getting interest suggestions: {e}")
            return []

    def get_user_preference_weights(self, user_id: int) -> Dict[str, float]:
        """Получить веса предпочтений пользователя для алгоритма рекомендаций."""
        defaults = {'interests': 1.5, 'favorites': 2.0, 'completed': 1.2, 'similar': 1.0}
        try:
            user = self.db_session.query(User).get(user_id)
            if not user:
                return defaults

            fav_count = self.db_session.query(FavoriteContent).filter_by(user_id=user_id).count()
            comp_count = self.db_session.query(UserProgress).filter_by(user_id=user_id, completed=True).count()

            # Adaptive logic
            if fav_count > 5:
                defaults['favorites'] = 2.5
            if comp_count > 10:
                defaults['completed'] = 1.5

            # Recent activity bonus
            recent_favs = self.db_session.query(FavoriteContent).filter(
                FavoriteContent.user_id == user_id,
                FavoriteContent.added_at > datetime.utcnow() - timedelta(days=7)
            ).count()
            if recent_favs > 2:
                defaults['favorites'] = 3.0

            return defaults
        except Exception as e:
            logger.error(f"Error getting preference weights: {e}")
            return defaults