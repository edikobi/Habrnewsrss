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
    
    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()