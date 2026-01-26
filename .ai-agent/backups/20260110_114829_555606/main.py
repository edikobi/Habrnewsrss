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
    try:
        # Авто-инициализация БД, если она не существует
        db_path = settings.database_url.replace("sqlite:///", "")
        if not Path(db_path).exists():
            logger.info("База данных не найдена. Инициализация...")
            init_database()

        cli()
    except KeyboardInterrupt:
        print("\nДо свидания!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Ошибка приложения: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()