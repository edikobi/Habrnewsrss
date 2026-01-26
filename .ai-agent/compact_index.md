# Project Map (18 files, 21,437 tokens)
# Root: C:\Users\Admin\ag

## (root)/
- `main.py` (866 tok): Application entry point for CLI-based startup, database initialization, and user configuration management via Click.

## app/
- `__init__.py` (40 tok): Utility module with minimal significant logic.
- `config.py` (483 tok): Configuration management module using Pydantic and dotenv to centralize environment variables for API keys, database connections, and content sources.
- `database.py` (2971 tok): SQLAlchemy ORM models for a personalized learning platform, defining user profiles, content metadata, progress tracking, and preference management.
- `interactive.py` (1929 tok): Interactive CLI for content aggregation and recommendation, integrating with database models for user, content, and interests management.

## app\cli/
- `__init__.py` (23 tok): Utility module with minimal significant logic.
- `commands.py` (2849 tok): CLI interface for an educational content aggregator, managing user operations, content updates, and automated scheduling through database and external service integrations.

## app\core/
- `__init__.py` (6 tok): Utility module with minimal significant logic.

## app\services/
- `__init__.py` (75 tok): Utility module with minimal significant logic.
- `aggregator.py` (2598 tok): Content aggregation service for user-specific feeds, integrating with user, content, and tagging models to update personalized content streams.
- `email_sender.py` (1158 tok): Automated email dispatch system for personalized user digests and notifications, integrating SMTP with environment-based configuration and structured logging.
- `exporter.py` (1157 tok): Progress data export utility for JSON, Markdown, and DOCX generation, integrating with a database session for user and learning progress retrieval.
- `recommender.py` (2052 tok): Content-based recommendation engine leveraging user history and item metadata, integrated with core user and content management models.

## app\sources/
- `__init__.py` (76 tok): Utility module with minimal significant logic.
- `base.py` (371 tok): Abstract base class defining the interface and common logic for content source implementations, enabling standardized content ingestion across the system.
- `coursera.py` (587 tok): Data ingestion stub for Coursera API integration, requiring authentication and returning placeholder data for course retrieval.
- `habr.py` (2649 tok): Habr RSS feed ingestion pipeline using BeautifulSoup for HTML parsing and requests for content retrieval, designed for integration into a data processing or content aggregation system.
- `youtube.py` (1547 tok): YouTube video ingestion pipeline via the YouTube Data API, with database integration for content and tag storage.
