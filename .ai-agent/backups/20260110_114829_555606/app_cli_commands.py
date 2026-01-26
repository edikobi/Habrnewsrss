from app.database import (
    init_database, get_db_session, User, ContentItem, UserInterest, 
    UserProgress, Tag, SessionLocal, engine, Base
)

import click
import datetime
import logging
from typing import Optional, List
from pathlib import Path
import json

from app.database import (
    init_database, get_db_session, User, ContentItem, UserInterest, 
    UserProgress, Tag, UserSettings, FavoriteContent, SessionLocal, engine, Base
)
from app.services.aggregator import ContentAggregator, update_all_content
from app.services.recommender import ContentRecommender
from app.services.exporter import ProgressExporter
from app.services.email_sender import EmailSender
from app.config import settings
from app.interactive import InteractiveMenu
from colorama import init, Fore, Back, Style


init(autoreset=True)
logger = logging.getLogger(__name__)

@click.group(invoke_without_command=True)
def cli(ctx=None):
    """CLI агрегатора образовательного контента"""
    # Если контекст не передан, пытаемся получить текущий
    if ctx is None:
        try:
            ctx = click.get_current_context()
        except RuntimeError:
            # Нет активного контекста Click, создаем заглушку
            class DummyContext:
                invoked_subcommand = None
            ctx = DummyContext()

    if ctx.invoked_subcommand is None:
        try:
            menu = InteractiveMenu()
            menu.run()
        except KeyboardInterrupt:
            click.echo("\nДо свидания!")
        except Exception as e:
            logger.error(f"Ошибка интерактивного режима: {e}")



@cli.command()
@click.option('--force', is_flag=True, help='Принудительная повторная инициализация')
def init_db(force: bool) -> None:
    """Инициализировать базу данных."""
    if force:
        if click.confirm('Это удалит все данные. Продолжить?'):
            Base.metadata.drop_all(bind=engine)
    init_database()
    click.echo("База данных готова.")

def add_user(username: Optional[str] = None, email: Optional[str] = None, interests: Optional[str] = None, data: Optional[str] = None) -> None:
    """Добавить нового пользователя."""
    if data:
        parts = data.split(',')
        if len(parts) < 2:
            click.echo("Invalid format: expected 'username,email[,interests]'", err=True)
            return
        username = parts[0].strip()
        email = parts[1].strip()
        interests = parts[2].strip() if len(parts) > 2 else None

    if not username or not email:
        click.echo("Username and email are required.", err=True)
        return

    session = SessionLocal()

    # Check for duplicates
    existing_user = session.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()

    if existing_user:
        click.echo("User with this username/email already exists", err=True)
        session.close()
        return

    user = User(username=username, email=email)
    session.add(user)
    session.flush()

    if interests:
        for tag in interests.split(','):
            interest = UserInterest(user_id=user.id, tag_name=tag.strip())
            session.add(interest)

    # Create default user settings
    user_settings = UserSettings(user_id=user.id, email_digest=email)
    session.add(user_settings)

    session.commit()
    click.echo(f"Пользователь создан с ID: {user.id}")
    session.close()



@cli.command()
@click.option('--user-id', type=int, help='Обновить для конкретного пользователя')
@click.option('--keywords', help='Ключевые слова через запятую')
def update_content(user_id: Optional[int], keywords: Optional[str]) -> None:
    """Обновить контент из всех источников."""
    aggregator = ContentAggregator()
    if keywords:
        items = aggregator.aggregate_by_keywords(keywords.split(','))
        count = aggregator.save_content_items(items)
    elif user_id:
        count = aggregator.update_content_for_user(user_id)
    else:
        results = update_all_content()
        count = sum(results.values())
    
    click.echo(f"Добавлено {count} новых элементов контента.")

@cli.command()
@click.option('--user-id', type=int, required=True, help='ID пользователя')
@click.option('--max-items', default=10, help='Максимальное количество элементов для показа')
def daily_digest(user_id: int, max_items: int) -> None:
    """Получить ежедневную подборку для пользователя."""
    aggregator = ContentAggregator()
    digest = aggregator.get_daily_digest(user_id, max_items)
    
    if not digest:
        click.echo("Новый контент по вашим интересам не найден.")
        return

    click.echo(f"\n--- Ежедневная подборка для пользователя {user_id} ---")
    for i, item in enumerate(digest, 1):
        click.echo(f"{i}. {item.title}")
        click.echo(f"   URL: {item.url}")
        click.echo(f"   Время: {item.estimated_completion_time()} мин | Платформа: {item.platform}")
    
    content_idx = click.prompt("\nВведите номер элемента для отметки как завершенного (или 0 для пропуска)", type=int, default=0)
    if 0 < content_idx <= len(digest):
        item = digest[content_idx-1]
        rating = click.prompt("Оценка (1-5)", type=int, default=5)
        notes = click.prompt("Заметки", default="")
        
        session = SessionLocal()
        progress = UserProgress(user_id=user_id, content_id=item.id)
        progress.mark_completed(rating=rating, notes=notes)
        session.add(progress)
        session.commit()
        click.echo("Отмечено как завершенное!")

@cli.command()
@click.option('--user-id', type=int, required=True, help='ID пользователя')
@click.option('--max', 'max_recs', default=5, help='Максимальное количество рекомендаций')
def get_recommendations(user_id: int, max_recs: int) -> None:
    """Получить персональные рекомендации."""
    recommender = ContentRecommender()
    recs = recommender.get_recommendations(user_id, max_recs)
    
    click.echo(f"\n--- Рекомендации для пользователя {user_id} ---")
    for item in recs:
        click.echo(f"- {item.title} ({item.difficulty.value})")
        click.echo(f"  {item.url}")

@cli.command()
@click.option('--user-id', type=int, required=True, help='ID пользователя')
@click.option('--format', 'fmt', type=click.Choice(['json', 'markdown', 'both']), default='both')
@click.option('--output-dir', default='./exports', help='Выходная директория')
def export_progress(user_id: int, fmt: str, output_dir: str) -> None:
    """Экспортировать прогресс пользователя в формате резюме."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    exporter = ProgressExporter()
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if fmt in ['json', 'both']:
        path = f"{output_dir}/user_{user_id}_{ts}.json"
        exporter.export_to_json(user_id, path)
        click.echo(f"Экспортировано в JSON: {path}")
        
    if fmt in ['markdown', 'both']:
        path = f"{output_dir}/user_{user_id}_{ts}.md"
        exporter.export_to_markdown(user_id, path)
        click.echo(f"Экспортировано в Markdown: {path}")

def send_digest(user_id: int, max_items: int, test: bool) -> None:
    """Отправить ежедневную подборку пользователю по email."""
    session = SessionLocal()
    user = session.query(User).filter(User.id == user_id).first()

    if not user:
        click.echo(f"Пользователь с ID {user_id} не найден.", err=True)
        session.close()
        return

    user_settings = session.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if not user_settings or not user_settings.email_digest:
        click.echo(f"У пользователя {user_id} не настроен email для рассылки.", err=True)
        session.close()
        return

    aggregator = ContentAggregator()
    digest = aggregator.get_daily_digest(user_id, max_items)

    if not digest:
        click.echo("Нет нового контента для подборки.")
        session.close()
        return

    if test:
        click.echo(f"\n--- Тестовая подборка для пользователя {user_id} ---")
        for i, item in enumerate(digest, 1):
            click.echo(f"{i}. {item.title}")
            click.echo(f"   URL: {item.url}")
        click.echo(f"\nEmail будет отправлен на: {user_settings.email_digest}")
    else:
        email_sender = EmailSender()
        success = email_sender.send_digest(user, digest, email_override=user_settings.email_digest)
        if success:
            click.echo(f"Подборка отправлена на {user_settings.email_digest}")
        else:
            click.echo("Ошибка отправки email.", err=True)

    session.close()



@cli.command()
@click.option('--interval', default=24, help='Интервал в часах')
def run_scheduler(interval: int) -> None:
    """Запустить планировщик для автоматических обновлений."""
    click.echo(f"Запуск планировщика. Обновление каждые {interval} часов...")
    import time
    try:
        while True:
            click.echo(f"[{datetime.datetime.now()}] Запуск обновления...")
            results = update_all_content()
            click.echo(f"Обновление завершено: {results}")
            time.sleep(interval * 3600)
    except KeyboardInterrupt:
        click.echo("Планировщик остановлен.")