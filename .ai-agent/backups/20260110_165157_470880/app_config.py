import os
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    """Application settings."""

    # API Keys
    youtube_api_key: str = ""
    coursera_api_key: str = ""

    # Database
    database_url: str = "sqlite:///content_aggregator.db"

    # Application settings
    daily_digest_hour: int = 9  # 9 AM
    content_update_interval_hours: int = 24
    max_recommendations_per_day: int = 5

    # Content source settings
    youtube_max_results: int = 50
    habr_max_articles: int = 30
    coursera_max_courses: int = 20

    # Source configuration
    youtube_enabled: bool = True
    habr_enabled: bool = True
    coursera_enabled: bool = True

    # Search configuration
    search_max_results: int = 100
    search_default_source: str = "all"

    # Interactive mode settings
    interactive_pagination_size: int = 10
    interactive_show_previews: bool = True

    # SMTP Email configuration
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    # Digest configuration
    digest_max_items: int = 10
    digest_retry_days: int = 3

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()