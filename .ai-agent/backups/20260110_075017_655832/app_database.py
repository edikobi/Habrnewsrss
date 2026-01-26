import datetime
from typing import List, Optional
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, 
    Boolean, Float, ForeignKey, Table, Enum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session
from sqlalchemy.sql import func
from enum import Enum as PyEnum

from app.config import settings

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

# Association table for ContentItem and Tag
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
        self.name = name
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
    url = Column(String, nullable=False)
    content_type = Column(Enum(ContentType))
    platform = Column(String)
    difficulty = Column(Enum(DifficultyLevel))
    duration_minutes = Column(Integer, nullable=True)
    published_at = Column(DateTime)
    added_at = Column(DateTime, default=func.now())
    
    tags = relationship("Tag", secondary=content_tags, back_populates="content_items")
    user_progress = relationship("UserProgress", back_populates="content")

    def __init__(self, source_id, title, description, url, content_type, platform, 
                 difficulty=DifficultyLevel.INTERMEDIATE, duration_minutes=None, 
                 published_at=None, added_at=None, tags=None):
        self.source_id = source_id
        self.title = title
        self.description = description
        self.url = url
        self.content_type = content_type
        self.platform = platform
        self.difficulty = difficulty
        self.duration_minutes = duration_minutes
        self.published_at = published_at or datetime.datetime.utcnow()
        self.added_at = added_at or datetime.datetime.utcnow()
        self.tags = tags or []

    def __repr__(self) -> str:
        return f"<ContentItem(title='{self.title[:50]}...', type={self.content_type.value})>"

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

class UserInterest(Base):
    """User's interest in specific tags or topics."""
    __tablename__ = 'user_interests'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    tag_name = Column(String, nullable=False)
    priority = Column(Integer, default=5)
    created_at = Column(DateTime, default=func.now())
    
    user = relationship("User", back_populates="interests")

    def __init__(self, user_id: int, tag_name: str, priority: int = 5):
        self.user_id = user_id
        self.tag_name = tag_name
        self.priority = priority
        self.created_at = datetime.datetime.utcnow()

    def __repr__(self) -> str:
        return f"<UserInterest(user_id={self.user_id}, tag='{self.tag_name}', priority={self.priority})>"

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

    def __repr__(self) -> str:
        return f"<UserProgress(user_id={self.user_id}, content_id={self.content_id}, completed={self.completed})>"

    def mark_completed(self, rating: Optional[int] = None, notes: Optional[str] = None):
        """Mark content as completed with optional rating and notes."""
        self.completed = True
        self.completed_at = datetime.datetime.utcnow()
        if rating is not None:
            self.rating = max(1, min(5, rating))
        if notes is not None:
            self.notes = notes

def init_database() -> None:
    """Initialize database tables."""
    try:
        Base.metadata.create_all(bind=engine)
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Error initializing database: {e}")
        raise

def get_db_session() -> Session:
    """Get database session for dependency injection."""
    session = SessionLocal()
    try:
        return session
    finally:
        session.close()