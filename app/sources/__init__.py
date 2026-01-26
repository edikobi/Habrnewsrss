"""
Content sources for educational platforms.
"""

from app.sources.base import ContentSource
from app.sources.youtube import YouTubeSource
from app.sources.habr import HabrSource
from app.sources.coursera import CourseraSource

__all__ = [
    'ContentSource',
    'YouTubeSource',
    'HabrSource',
    'CourseraSource',
]