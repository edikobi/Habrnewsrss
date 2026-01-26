from app.database import init_database, engine
from colorama import init, Fore, Back, Style
import importlib
import subprocess
import argparse
from app.services.aggregator import ContentAggregator
from app.database import SessionLocal, UserSettings

#!/usr/bin/env python3
"""
Агрегатор образовательного контента
Агрегирует контент из YouTube, Habr, Coursera и предоставляет
персонализированный учебный опыт.
"""

import sys
import logging
from pathlib import Path

from app.cli.commands import cli
from app.database import init_database
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Основная точка входа для приложения."""
    # Parse custom app arguments (--app-*) before Click takes over
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--app-set-digest-hour', type=int, metavar='HOUR',
                        help='Set article loading hour for users (0-23)')
    parser.add_argument('--app-user-id', type=int, metavar='ID',
                        help='User ID for targeted configuration')
    parser.add_argument('--app-skip-check', action='store_true',
                        help='Skip missed update check on startup')

    # Filter out --app-* arguments before Click sees them
    original_argv = sys.argv.copy()
    app_args = []
    filtered_argv = []
    i = 0
    while i < len(original_argv):
        arg = original_argv[i]
        if arg.startswith('--app-'):
            app_args.append(arg)
            # Remove the argument and its value if applicable
            if i + 1 < len(original_argv) and not original_argv[i + 1].startswith('-'):
                app_args.append(original_argv[i + 1])
                i += 1
        else:
            filtered_argv.append(arg)
        i += 1
    sys.argv = filtered_argv

    # Parse the filtered app arguments
    parsed_args, _ = parser.parse_known_args(app_args)

    try:
        # Ensure all tables exist (safe if already created)
        init_database()

        # Configure digest hour if requested
        if parsed_args.app_set_digest_hour is not None:
            hour = parsed_args.app_set_digest_hour
            if 0 <= hour <= 23:
                session = SessionLocal()
                try:
                    query = session.query(UserSettings)
                    if parsed_args.app_user_id:
                        query = query.filter_by(user_id=parsed_args.app_user_id)

                    for settings in query.all():
                        settings.digest_hour = hour
                        logger.info(f"Set digest hour to {hour}:00 for user {settings.user_id}")

                    session.commit()
                    logger.info(f"Digest hour configuration applied")
                except Exception as e:
                    logger.error(f"Error configuring digest hour: {e}")
                    session.rollback()
                finally:
                    session.close()
            else:
                logger.error(f"Invalid hour {hour}. Must be 0-23.")

        # Check for missed content updates unless skipped
        if not parsed_args.app_skip_check:
            try:
                aggregator = ContentAggregator()
                results = aggregator.check_and_update_content_for_all_users()
                if results:
                    total = sum(results.values())
                    logger.info(f"Automated update: added {total} items for {len(results)} users")
                else:
                    logger.info("No missed updates detected")
            except Exception as e:
                logger.error(f"Error checking for missed updates: {e}")

        cli()
    except KeyboardInterrupt:
        print("\nДо свидания!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Ошибка приложения: {e}")
        sys.exit(1)




if __name__ == "__main__":
    main()