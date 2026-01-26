import click
import datetime
import logging
from typing import Optional, List
from pathlib import Path
import json
from app.interactive import InteractiveMenu
from colorama import init, Fore, Back, Style


init(autoreset=True)

from app.database import (
    init_database, get_db_session, User, ContentItem, UserInterest, 
    UserProgress, Tag, SessionLocal, engine, Base
)
from app.services.aggregator import ContentAggregator, update_all_content
from app.services.recommender import ContentRecommender
from app.services.exporter import ProgressExporter
from app.config import settings

logger = logging.getLogger(__name__)

@click.group(invoke_without_command=True)
def cli(ctx):
    """Educational Content Aggregator CLI"""
    if ctx.invoked_subcommand is None:
        try:
            menu = InteractiveMenu()
            menu.run()
        except KeyboardInterrupt:
            click.echo("\nGoodbye!")
        except Exception as e:
            logger.error(f"Interactive mode error: {e}")


@cli.command()
@click.option('--force', is_flag=True, help='Force reinitialization')
def init_db(force: bool) -> None:
    """Initialize database."""
    if force:
        if click.confirm('This will delete all data. Continue?'):
            Base.metadata.drop_all(bind=engine)
    init_database()
    click.echo("Database ready.")

@cli.command()
@click.option('--username', required=True, help='Username')
@click.option('--email', required=True, help='Email')
@click.option('--interests', help='Comma-separated interests')
def add_user(username: str, email: str, interests: Optional[str]) -> None:
    """Add a new user."""
    session = SessionLocal()
    user = User(username=username, email=email)
    session.add(user)
    session.flush()
    
    if interests:
        for tag in interests.split(','):
            interest = UserInterest(user_id=user.id, tag_name=tag.strip())
            session.add(interest)
    
    session.commit()
    click.echo(f"User created with ID: {user.id}")
    session.close()

@cli.command()
@click.option('--user-id', type=int, help='Update for specific user')
@click.option('--keywords', help='Comma-separated keywords')
def update_content(user_id: Optional[int], keywords: Optional[str]) -> None:
    """Update content from all sources."""
    aggregator = ContentAggregator()
    if keywords:
        items = aggregator.aggregate_by_keywords(keywords.split(','))
        count = aggregator.save_content_items(items)
    elif user_id:
        count = aggregator.update_content_for_user(user_id)
    else:
        results = update_all_content()
        count = sum(results.values())
    
    click.echo(f"Added {count} new content items.")

@cli.command()
@click.option('--user-id', type=int, required=True, help='User ID')
@click.option('--max-items', default=10, help='Maximum items to show')
def daily_digest(user_id: int, max_items: int) -> None:
    """Get daily digest for user."""
    aggregator = ContentAggregator()
    digest = aggregator.get_daily_digest(user_id, max_items)
    
    if not digest:
        click.echo("No new content found for your interests.")
        return

    click.echo(f"\n--- Daily Digest for User {user_id} ---")
    for i, item in enumerate(digest, 1):
        click.echo(f"{i}. {item.title}")
        click.echo(f"   URL: {item.url}")
        click.echo(f"   Time: {item.estimated_completion_time()} mins | Platform: {item.platform}")
    
    content_idx = click.prompt("\nEnter item number to mark as completed (or 0 to skip)", type=int, default=0)
    if 0 < content_idx <= len(digest):
        item = digest[content_idx-1]
        rating = click.prompt("Rating (1-5)", type=int, default=5)
        notes = click.prompt("Notes", default="")
        
        session = SessionLocal()
        progress = UserProgress(user_id=user_id, content_id=item.id)
        progress.mark_completed(rating=rating, notes=notes)
        session.add(progress)
        session.commit()
        click.echo("Marked as completed!")

@cli.command()
@click.option('--user-id', type=int, required=True, help='User ID')
@click.option('--max', 'max_recs', default=5, help='Maximum recommendations')
def get_recommendations(user_id: int, max_recs: int) -> None:
    """Get personalized recommendations."""
    recommender = ContentRecommender()
    recs = recommender.get_recommendations(user_id, max_recs)
    
    click.echo(f"\n--- Recommendations for User {user_id} ---")
    for item in recs:
        click.echo(f"- {item.title} ({item.difficulty.value})")
        click.echo(f"  {item.url}")

@cli.command()
@click.option('--user-id', type=int, required=True, help='User ID')
@click.option('--format', 'fmt', type=click.Choice(['json', 'markdown', 'both']), default='both')
@click.option('--output-dir', default='./exports', help='Output directory')
def export_progress(user_id: int, fmt: str, output_dir: str) -> None:
    """Export user progress to resume format."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    exporter = ProgressExporter()
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if fmt in ['json', 'both']:
        path = f"{output_dir}/user_{user_id}_{ts}.json"
        exporter.export_to_json(user_id, path)
        click.echo(f"Exported JSON to {path}")
        
    if fmt in ['markdown', 'both']:
        path = f"{output_dir}/user_{user_id}_{ts}.md"
        exporter.export_to_markdown(user_id, path)
        click.echo(f"Exported Markdown to {path}")

@cli.command()
@click.option('--interval', default=24, help='Interval in hours')
def run_scheduler(interval: int) -> None:
    """Run scheduler for automated updates."""
    click.echo(f"Starting scheduler. Updating every {interval} hours...")
    import time
    try:
        while True:
            click.echo(f"[{datetime.datetime.now()}] Running update...")
            results = update_all_content()
            click.echo(f"Update complete: {results}")
            time.sleep(interval * 3600)
    except KeyboardInterrupt:
        click.echo("Scheduler stopped.")