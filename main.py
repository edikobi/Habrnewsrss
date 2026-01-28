from app.database import SessionLocal, UserSettings
from app.database import init_database
from app.database import init_database, SessionLocal, UserSettings
from app.database import init_database, engine
from colorama import init, Fore, Back, Style
import importlib
import subprocess

#!/usr/bin/env python3
"""
Агрегатор образовательного контента
Агрегирует контент из YouTube, Habr, Coursera и предоставляет
персонализированный учебный опыт.
"""

import sys
import logging
import argparse
from datetime import datetime
from pathlib import Path

from colorama import Fore, Style

from app.cli.commands import cli
from app.database import (
    init_database, SessionLocal, UserSettings, 
    User, ContentItem, Tag
)
from app.services.aggregator import ContentAggregator
from app.sources.habr import HabrSource
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def _check_missed_auto_downloads() -> None:
    """Проверить и выполнить пропущенные автозагрузки для всех пользователей."""
    session = SessionLocal()
    try:
        # Найти пользователей с настроенной автозагрузкой
        users_with_auto = session.query(User).join(UserSettings).filter(
            UserSettings.auto_download_hour.isnot(None)
        ).all()
        
        if not users_with_auto:
            return
        
        now = datetime.utcnow()
        habr_source = HabrSource()
        aggregator = ContentAggregator(db_session=session)
        
        for user in users_with_auto:
            settings_obj = user.settings
            if not settings_obj or settings_obj.auto_download_hour is None:
                continue
            
            # Проверить, нужна ли загрузка
            should_download = False
            
            if settings_obj.last_auto_download is None:
                # Никогда не загружали - загрузить
                should_download = True
            else:
                # Проверить, прошёл ли назначенный час с последней загрузки
                last_download_date = settings_obj.last_auto_download.date()
                today = now.date()
                
                if last_download_date < today:
                    # Последняя загрузка была вчера или раньше
                    # Проверить, прошёл ли уже назначенный час сегодня
                    if now.hour >= settings_obj.auto_download_hour:
                        should_download = True
            
            if should_download:
                logger.info(f"Running missed auto-download for user {user.id} ({user.username})")
                
                # Получить интересы пользователя (лимит 90)
                keywords = aggregator.get_top_interests(user.id, 90)
                if not keywords:
                    logger.info(f"User {user.id} has no interests, skipping auto-download")
                    continue
                
                # Получить статьи из Habr
                articles = habr_source.fetch_content(keywords, max_results=30)
                
                if not articles:
                    logger.info(f"No articles found for user {user.id}")
                    continue
                
                # Сортировать по дате (свежие первыми)
                articles.sort(key=lambda x: x.published_at or datetime.min, reverse=True)
                
                # Сохранить только новые статьи с кэшем тегов
                saved_count = 0
                saved_titles = []
                tag_cache = {}  # Кэш для предотвращения дублирования тегов
                
                for item in articles:
                    exists = session.query(ContentItem).filter_by(
                        source_id=item.source_id, platform=item.platform
                    ).first()
                    if not exists:
                        # Обработка тегов с кэшем
                        new_tags = []
                        for tag in (item.tags or []):
                            tag_name = tag.name.lower() if tag.name else ""
                            if tag_name:
                                # Проверить кэш
                                if tag_name not in tag_cache:
                                    db_tag = session.query(Tag).filter_by(name=tag_name).first()
                                    if not db_tag:
                                        db_tag = Tag(name=tag_name)
                                        session.add(db_tag)
                                        session.flush()  # Немедленно сохранить тег в БД
                                    tag_cache[tag_name] = db_tag
                                new_tags.append(tag_cache[tag_name])
                        item.tags = new_tags
                        session.add(item)
                        saved_count += 1
                        saved_titles.append(item.title)
                
                if saved_count > 0:
                    session.commit()
                    logger.info(f"Auto-downloaded {saved_count} articles for user {user.id}")
                    
                    # Показать названия скачанных статей
                    print(f"\n{Fore.CYAN}═══ АВТОЗАГРУЗКА ДЛЯ {user.username} ═══{Style.RESET_ALL}")
                    print(f"{Fore.GREEN}Загружено {saved_count} новых статей:{Style.RESET_ALL}")
                    for title in saved_titles[:10]:
                        print(f"  • {title[:60]}{'...' if len(title) > 60 else ''}")
                    if len(saved_titles) > 10:
                        print(f"  ... и ещё {len(saved_titles) - 10} статей")
                
                # Обновить время последней загрузки
                settings_obj.last_auto_download = now
                session.commit()
                
    except Exception as e:
        logger.error(f"Error in auto-download check: {e}")
        session.rollback()
    finally:
        session.close()



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

                    for user_setting in query.all():
                        user_setting.digest_hour = hour
                        logger.info(f"Set digest hour to {hour}:00 for user {user_setting.user_id}")

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
            
            # Check for missed auto-downloads
            try:
                _check_missed_auto_downloads()
            except Exception as e:
                logger.error(f"Error checking for missed auto-downloads: {e}")

        # Call Click CLI with standalone_mode=False to handle exceptions here
        cli(standalone_mode=False)
    except KeyboardInterrupt:
        print("\nДо свидания!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Ошибка приложения: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()