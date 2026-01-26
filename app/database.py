from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime,
    Boolean, Float, ForeignKey, Table, Enum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session
from sqlalchemy.sql import func
import datetime
import logging
from typing import List, Optional
from enum import Enum as PyEnum

from app.config import settings

logger = logging.getLogger(__name__)
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, 
)
import sqlite3

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime,
    Boolean, Float, ForeignKey, Table, Enum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session
from sqlalchemy.sql import func
import datetime
import logging
from typing import List, Optional
from enum import Enum as PyEnum

from app.config import settings

logger = logging.getLogger(__name__)

def get_sqlite_column_type(column_type) -> str:
    """Convert SQLAlchemy column type to SQLite type string."""
    if isinstance(column_type, (Integer, Boolean)):
        return 'INTEGER'
    if isinstance(column_type, Float):
        return 'REAL'
    if isinstance(column_type, (String, Text, Enum)):
        return 'TEXT'
    if isinstance(column_type, DateTime):
        return 'DATETIME'
    return 'TEXT'

Base = declarative_base()
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class ContentType(PyEnum):
    """Types of educational content."""
    YOUTUBE_VIDEO = "youtube_video"
    HABR_ARTICLE = "habr_article"
    COURSERA_COURSE = "coursera_course"

class DifficultyLevel(PyEnum):
    """Difficulty levels for content."""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"

content_tags = Table(
    'content_tags',
    Base.metadata,
    Column('content_id', Integer, ForeignKey('content_items.id')),
    Column('tag_id', Integer, ForeignKey('tags.id'))
)

class Tag(Base):
    """Tag for categorizing content."""
    __tablename__ = 'tags'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    
    content_items = relationship("ContentItem", secondary=content_tags, back_populates="tags")

    def __init__(self, name: str, description: Optional[str] = None):
        """Initialize tag with name normalization to lowercase."""
        self.name = name.lower() if name else ""
        self.description = description

    def __repr__(self) -> str:
        return f"<Tag(name='{self.name}')>"

class ContentItem(Base):
    """Educational content item from any source."""
    __tablename__ = 'content_items'

    id = Column(Integer, primary_key=True)
    source_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    full_text = Column(Text, nullable=True)
    url = Column(String, nullable=False)
    content_type = Column(Enum(ContentType))
    platform = Column(String)
    difficulty = Column(Enum(DifficultyLevel))
    duration_minutes = Column(Integer, nullable=True)
    published_at = Column(DateTime)
    added_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    tags = relationship("Tag", secondary=content_tags, back_populates="content_items")
    user_progress = relationship("UserProgress", back_populates="content")
    favorited_by = relationship("FavoriteContent", back_populates="content")

    def __init__(self, source_id, title, description, full_text=None, url=None, content_type=None, platform=None, 
                 difficulty=DifficultyLevel.INTERMEDIATE, duration_minutes=None, 
                 published_at=None, added_at=None, updated_at=None, tags=None):
        """Initialize content item with metadata and timestamps."""
        self.source_id = source_id
        self.title = title
        self.description = description
        self.full_text = full_text
        self.url = url
        self.content_type = content_type
        self.platform = platform
        self.difficulty = difficulty
        self.duration_minutes = duration_minutes
        self.published_at = published_at or datetime.datetime.utcnow()
        self.added_at = added_at or datetime.datetime.utcnow()
        self.updated_at = updated_at or datetime.datetime.utcnow()
        self.tags = tags or []

    def __repr__(self) -> str:
        return f"<ContentItem(title='{self.title[:50]}...', type={self.content_type.value if self.content_type else 'None'})>"

    def estimated_completion_time(self) -> int:
        """Calculate estimated completion time in minutes."""
        if self.duration_minutes is not None:
            return self.duration_minutes
        if self.content_type == ContentType.YOUTUBE_VIDEO:
            return 15
        if self.content_type == ContentType.HABR_ARTICLE:
            return 10
        if self.content_type == ContentType.COURSERA_COURSE:
            return 120
        return 30

class User(Base):
    """Application user with interests and progress."""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    interests = relationship("UserInterest", back_populates="user")
    progress = relationship("UserProgress", back_populates="user")
    settings = relationship("UserSettings", uselist=False, back_populates="user")
    favorites = relationship("FavoriteContent", back_populates="user")
    search_queries = relationship("SearchQuery", back_populates="user")

    def __init__(self, username: str, email: str):
        self.username = username
        self.email = email
        self.created_at = datetime.datetime.utcnow()

    def __repr__(self) -> str:
        return f"<User(username='{self.username}')>"

    def completed_content_count(self) -> int:
        """Count completed content items."""
        return sum(1 for p in self.progress if p.completed)

    def total_study_time(self) -> int:
        """Sum estimated completion time for all completed content."""
        return sum(p.content.estimated_completion_time() for p in self.progress if p.completed and p.content)

    def ensure_settings(self, session: Session) -> 'UserSettings':
        """Ensure user has UserSettings record, creating if missing."""
        try:
            if self.settings is not None:
                return self.settings
            settings = session.query(UserSettings).filter_by(user_id=self.id).first()
            if not settings:
                settings = UserSettings(user_id=self.id, email_digest=self.email)
                session.add(settings)
                session.flush()
            self.settings = settings
            return settings
        except Exception as e:
            logger.warning(f"Error ensuring settings for user {self.id}: {e}")
            raise

class UserInterest(Base):
    """User's interest in specific tags or topics."""
    __tablename__ = 'user_interests'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    tag_name = Column(String, nullable=False)
    priority = Column(Integer, default=5)
    created_at = Column(DateTime, default=func.now())
    last_used = Column(DateTime, default=func.now(), onupdate=func.now())
    
    user = relationship("User", back_populates="interests")

    def __init__(self, user_id: int, tag_name: str, priority: int = 5, last_used: Optional[datetime.datetime] = None):
        """Initialize user interest with priority and usage tracking."""
        tag_name = tag_name.lower().strip()
        if not tag_name:
            raise ValueError("Имя тега не может быть пустым")
        if len(tag_name) > 50:
            tag_name = tag_name[:50]
            print(f"Предупреждение: тег обрезан до 50 символов: {tag_name}")
        if any(c in tag_name for c in ['&', '?', '#', '%', '+']):
            import urllib.parse
            tag_name = urllib.parse.quote(tag_name, safe='')
        self.user_id = user_id
        self.tag_name = tag_name
        self.priority = priority
        self.created_at = datetime.datetime.utcnow()
        self.last_used = last_used or datetime.datetime.utcnow()

    def __repr__(self) -> str:
        return f"<UserInterest(user_id={self.user_id}, tag='{self.tag_name}', priority={self.priority})>"

    def mark_used(self, priority_increment: int = 1) -> None:
        """Обновить время использования и увеличить приоритет."""
        self.last_used = datetime.datetime.utcnow()
        self.priority = min(self.priority + priority_increment, 10)

class UserProgress(Base):
    """Tracks user progress on content items."""
    __tablename__ = 'user_progress'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    content_id = Column(Integer, ForeignKey('content_items.id'))
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)
    rating = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    started_at = Column(DateTime, default=func.now())
    
    user = relationship("User", back_populates="progress")
    content = relationship("ContentItem", back_populates="user_progress")

    def __init__(self, user_id: int, content_id: int):
        self.user_id = user_id
        self.content_id = content_id
        self.completed = False
        self.started_at = datetime.datetime.utcnow()

    def mark_completed(self, rating: Optional[int] = None, notes: Optional[str] = None):
        """Mark content as completed with optional rating and notes."""
        self.completed = True
        self.completed_at = datetime.datetime.utcnow()
        if rating is not None:
            self.rating = max(1, min(5, rating))
        if notes is not None:
            self.notes = notes

class UserSettings(Base):
    """User preferences for email digests and notification settings."""
    __tablename__ = 'user_settings'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True)
    email_digest = Column(String, nullable=False)
    digest_hour = Column(Integer, default=9)
    digest_enabled = Column(Boolean, default=True)
    missed_digest_send = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_content_update = Column(DateTime, nullable=True)
    auto_update_content = Column(Boolean, default=True)
    auto_download_hour = Column(Integer, nullable=True)
    last_auto_download = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="settings")

    def __init__(self, user_id: int, email_digest: str, digest_hour: int = 9, 
                 digest_enabled: bool = True, missed_digest_send: bool = True,
                 last_content_update: Optional[datetime.datetime] = None, 
                 auto_update_content: bool = True,
                 auto_download_hour: Optional[int] = None,
                 last_auto_download: Optional[datetime.datetime] = None):
        self.user_id = user_id
        self.email_digest = email_digest
        self.digest_hour = digest_hour
        self.digest_enabled = digest_enabled
        self.missed_digest_send = missed_digest_send
        self.last_content_update = last_content_update
        self.auto_update_content = auto_update_content
        self.auto_download_hour = auto_download_hour
        self.last_auto_download = last_auto_download
        self.created_at = datetime.datetime.utcnow()
        self.updated_at = datetime.datetime.utcnow()


class FavoriteContent(Base):
    """Tracks content items marked as favorite by users."""
    __tablename__ = 'favorite_content'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    content_id = Column(Integer, ForeignKey('content_items.id'))
    added_at = Column(DateTime, default=func.now())
    notes = Column(Text, nullable=True)
    
    user = relationship("User", back_populates="favorites")
    content = relationship("ContentItem", back_populates="favorited_by")

    def __init__(self, user_id: int, content_id: int, notes: Optional[str] = None):
        self.user_id = user_id
        self.content_id = content_id
        self.added_at = datetime.datetime.utcnow()
        self.notes = notes

class SearchQuery(Base):
    """Поисковые запросы пользователей для анализа интересов."""
    __tablename__ = 'search_queries'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    query = Column(String, nullable=False)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="search_queries")

    def __init__(self, user_id: int, query: str):
        self.user_id = user_id
        self.query = query.strip().lower()
        self.created_at = datetime.datetime.utcnow()

def init_database() -> None:
    """Initialize database tables with migration for missing columns."""
    try:
        Base.metadata.create_all(bind=engine)
        if engine.url.drivername == 'sqlite':
            conn = engine.raw_connection()
            cursor = conn.cursor()
            for table_name, table in Base.metadata.tables.items():
                cursor.execute(f"PRAGMA table_info({table_name})")
                existing_columns = [col[1] for col in cursor.fetchall()]
                model_columns = {column.name: column for column in table.columns}
                for column_name, column in model_columns.items():
                    if column_name not in existing_columns:
                        column_type = get_sqlite_column_type(column.type)
                        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
            conn.commit()
            cursor.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

def get_db_session() -> Session:
    """Get database session for dependency injection."""
    session = SessionLocal()
    try:
        return session
    finally:
        session.close()