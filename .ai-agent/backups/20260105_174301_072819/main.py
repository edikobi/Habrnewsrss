#!/usr/bin/env python3
"""
Educational Content Aggregator
Aggregates content from YouTube, Habr, Coursera and provides
personalized learning experience.
"""

import sys
import logging
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.cli.commands import cli
from app.database import init_database, engine
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main() -> None:
    """Main entry point for the application."""
    try:
        # Auto-init DB if it doesn't exist
        db_path = settings.database_url.replace("sqlite:///", "")
        if not Path(db_path).exists():
            logger.info("Database not found. Initializing...")
            init_database()

        click_banner = """
        =========================================
        EDUCATIONAL CONTENT AGGREGATOR
        =========================================
        """
        print(click_banner)
        cli()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()