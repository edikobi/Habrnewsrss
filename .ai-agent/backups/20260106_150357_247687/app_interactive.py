"""Interactive menu for content aggregation system."""
import click
import datetime
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

from app.database import (
    get_db_session, User, ContentItem, UserInterest, 
    UserProgress, Tag, SessionLocal
)
from app.services.aggregator import ContentAggregator, update_all_content
from app.services.recommender import ContentRecommender
from app.config import settings
from app.sources.youtube import YouTubeSource
from app.sources.habr import HabrSource
from app.sources.coursera import CourseraSource

logger = logging.getLogger(__name__)


class InteractiveMenu:
    """Interactive menu for content aggregation system with source management and search."""

    def __init__(self):
        self.session = SessionLocal()
        self.aggregator = ContentAggregator(db_session=self.session)
        self.recommender = ContentRecommender(db_session=self.session)
        self.sources = {
            "youtube": {"enabled": bool(settings.youtube_api_key), "instance": YouTubeSource()},
            "habr": {"enabled": True, "instance": HabrSource()},
            "coursera": {"enabled": bool(settings.coursera_api_key), "instance": CourseraSource()},
        }

    def run(self) -> None:
        """Main interactive loop."""
        print("\n" + "="*50)
        print("EDUCATIONAL CONTENT AGGREGATOR - INTERACTIVE MODE")
        print("="*50)
        
        try:
            while True:
                choice = self.show_main_menu()
                if choice == 6:
                    print("\nGoodbye!")
                    break
        except KeyboardInterrupt:
            print("\n\nGoodbye!")
        finally:
            self.session.close()

    def show_main_menu(self) -> int:
        """Display main menu options and process user choice."""
        print("\n" + "-"*40)
        print("MAIN MENU")
        print("-"*40)
        print("1. View content and news")
        print("2. Manage sources")
        print("3. Search content")
        print("4. Configure settings")
        print("5. View statistics")
        print("6. Exit")
        print("-"*40)
        
        while True:
            try:
                choice = int(input("\nEnter your choice (1-6): "))
                if 1 <= choice <= 6:
                    break
                print("Please enter a number between 1 and 6.")
            except ValueError:
                print("Please enter a valid number.")
        
        if choice == 1:
            self.view_content()
        elif choice == 2:
            self.manage_sources()
        elif choice == 3:
            self.search_content()
        elif choice == 4:
            self.configure_settings()
        elif choice == 5:
            self.show_statistics()
        
        return choice

    def view_content(self) -> None:
        """Browse and search content."""
        print("\n" + "-"*40)
        print("VIEW CONTENT")
        print("-"*40)
        
        user_id_input = input("Enter user ID for personalized digest (or press Enter for all content): ")
        
        if user_id_input.strip():
            try:
                user_id = int(user_id_input)
                user = self.session.query(User).get(user_id)
                if not user:
                    print(f"User with ID {user_id} not found.")
                    return
                
                print(f"\nGenerating daily digest for user: {user.username}")
                digest = self.aggregator.get_daily_digest(user_id, max_items=10)
                
                if not digest:
                    print("No content found for your interests.")
                    return
                
                print(f"\nFound {len(digest)} items:")
                for i, item in enumerate(digest, 1):
                    print(f"{i}. {item.title}")
                    print(f"   Platform: {item.platform} | Difficulty: {item.difficulty}")
                    print(f"   URL: {item.url}")
                    print()
                
                # Option to mark as completed
                mark_choice = input("Enter item number to mark as completed (or 0 to skip): ")
                if mark_choice.isdigit():
                    item_idx = int(mark_choice)
                    if 0 < item_idx <= len(digest):
                        item = digest[item_idx-1]
                        rating = input("Rating (1-5, default 5): ")
                        rating = int(rating) if rating.isdigit() else 5
                        notes = input("Notes (optional): ")
                        
                        progress = UserProgress(user_id=user_id, content_id=item.id)
                        progress.mark_completed(rating=rating, notes=notes)
                        self.session.add(progress)
                        self.session.commit()
                        print("Item marked as completed!")
                        
            except ValueError:
                print("Invalid user ID.")
        else:
            # Show recent content from all sources
            print("\nRecent content from all sources:")
            items = self.session.query(ContentItem).order_by(ContentItem.published_at.desc()).limit(20).all()
            
            for i, item in enumerate(items, 1):
                print(f"{i}. {item.title}")
                print(f"   Platform: {item.platform} | Published: {item.published_at}")
                print(f"   URL: {item.url}")
                print()

    def manage_sources(self) -> None:
        """Enable/disable and configure sources."""
        print("\n" + "-"*40)
        print("MANAGE SOURCES")
        print("-"*40)
        
        while True:
            print("\nCurrent source status:")
            for source_name, source_info in self.sources.items():
                status = "ENABLED" if source_info["enabled"] else "DISABLED"
                print(f"  {source_name.upper():10} : {status}")
            
            print("\nOptions:")
            print("1. Enable/disable source")
            print("2. Configure API keys")
            print("3. Set content limits")
            print("4. Test source connection")
            print("5. Return to main menu")
            
            try:
                choice = int(input("\nEnter choice (1-5): "))
                if choice == 5:
                    break
                
                if choice == 1:
                    source_name = input("Enter source name (youtube/habr/coursera): ").lower()
                    if source_name in self.sources:
                        current = self.sources[source_name]["enabled"]
                        self.sources[source_name]["enabled"] = not current
                        status = "enabled" if not current else "disabled"
                        print(f"{source_name} has been {status}.")
                    else:
                        print("Invalid source name.")
                
                elif choice == 2:
                    source_name = input("Enter source name (youtube/coursera): ").lower()
                    if source_name in ["youtube", "coursera"]:
                        api_key = input(f"Enter {source_name} API key (press Enter to keep current): ")
                        if api_key:
                            # In a real implementation, this would save to .env
                            print(f"API key for {source_name} would be saved to configuration.")
                            print("Note: Restart required for changes to take effect.")
                    else:
                        print("API key configuration only available for YouTube and Coursera.")
                
                elif choice == 3:
                    source_name = input("Enter source name (youtube/habr/coursera): ").lower()
                    if source_name in self.sources:
                        try:
                            limit = int(input(f"Enter max results for {source_name} (current: {getattr(settings, f'{source_name}_max_results', 50)}): "))
                            if limit > 0:
                                print(f"Limit for {source_name} would be set to {limit}.")
                                print("Note: Changes apply to next content update.")
                            else:
                                print("Limit must be positive.")
                        except ValueError:
                            print("Please enter a valid number.")
                    else:
                        print("Invalid source name.")
                
                elif choice == 4:
                    source_name = input("Enter source name to test (youtube/habr/coursera): ").lower()
                    if source_name in self.sources:
                        if self.sources[source_name]["enabled"]:
                            print(f"Testing {source_name} connection...")
                            try:
                                source = self.sources[source_name]["instance"]
                                test_items = source.fetch_content(["python"], 1)
                                if test_items:
                                    print(f"✓ {source_name} connection successful. Found {len(test_items)} test items.")
                                else:
                                    print(f"⚠ {source_name} connected but returned no results.")
                            except Exception as e:
                                print(f"✗ {source_name} connection failed: {e}")
                        else:
                            print(f"{source_name} is disabled. Enable it first.")
                    else:
                        print("Invalid source name.")
                
            except ValueError:
                print("Please enter a valid number.")

    def search_content(self) -> None:
        """Interactive search across all sources."""
        print("\n" + "-"*40)
        print("SEARCH CONTENT")
        print("-"*40)
        
        keywords_input = input("Enter search keywords (comma-separated): ")
        keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
        
        if not keywords:
            print("No keywords provided.")
            return
        
        print("\nAvailable sources: youtube, habr, coursera, all")
        source_filter = input("Filter by source (default: all): ").lower() or "all"
        
        print("\nDifficulty levels: beginner, intermediate, advanced, all")
        difficulty_filter = input("Filter by difficulty (default: all): ").lower() or "all"
        
        try:
            max_results = int(input("Maximum results (default: 50): ") or "50")
        except ValueError:
            max_results = 50
        
        print(f"\nSearching for: {', '.join(keywords)}")
        if source_filter != "all":
            print(f"Source filter: {source_filter}")
        if difficulty_filter != "all":
            print(f"Difficulty filter: {difficulty_filter}")
        
        results = self.aggregator.search_content(keywords, source_filter, difficulty_filter, max_results)
        
        print(f"\nFound {len(results)} results:")
        for i, item in enumerate(results, 1):
            print(f"{i}. {item.title}")
            print(f"   Platform: {item.platform} | Difficulty: {item.difficulty}")
            print(f"   Published: {item.published_at}")
            print(f"   URL: {item.url}")
            if item.description and len(item.description) > 100:
                print(f"   Description: {item.description[:100]}...")
            print()

    def configure_settings(self) -> None:
        """Update application settings."""
        print("\n" + "-"*40)
        print("CONFIGURE SETTINGS")
        print("-"*40)
        
        print("\nCurrent settings:")
        print(f"1. Daily digest hour: {settings.daily_digest_hour}:00")
        print(f"2. Content update interval: {settings.content_update_interval_hours} hours")
        print(f"3. Max recommendations per day: {settings.max_recommendations_per_day}")
        print(f"4. Database location: {settings.database_url}")
        print(f"5. Interactive pagination size: {getattr(settings, 'interactive_pagination_size', 10)}")
        print(f"6. Show previews in interactive mode: {getattr(settings, 'interactive_show_previews', True)}")
        
        print("\nEnter setting number to modify (or 0 to return): ")
        try:
            choice = int(input("Choice: "))
            if choice == 0:
                return
            
            if choice == 1:
                new_hour = int(input("New daily digest hour (0-23): "))
                if 0 <= new_hour <= 23:
                    print(f"Daily digest hour would be set to {new_hour}:00")
                else:
                    print("Hour must be between 0 and 23.")
            
            elif choice == 2:
                new_interval = int(input("New update interval (hours, 1-168): "))
                if 1 <= new_interval <= 168:
                    print(f"Update interval would be set to {new_interval} hours")
                else:
                    print("Interval must be between 1 and 168 hours (1 week).")
            
            elif choice == 3:
                new_max = int(input("New max recommendations (1-50): "))
                if 1 <= new_max <= 50:
                    print(f"Max recommendations would be set to {new_max}")
                else:
                    print("Must be between 1 and 50.")
            
            elif choice == 4:
                new_db = input("New database path (e.g., sqlite:///new.db): ")
                if new_db.startswith("sqlite:///"):
                    print(f"Database location would be set to {new_db}")
                else:
                    print("Database URL must start with 'sqlite:///'")
            
            elif choice == 5:
                new_size = int(input("New pagination size (5-50): "))
                if 5 <= new_size <= 50:
                    print(f"Pagination size would be set to {new_size}")
                else:
                    print("Must be between 5 and 50.")
            
            elif choice == 6:
                new_setting = input("Show previews? (yes/no): ").lower()
                if new_setting in ["yes", "no"]:
                    value = new_setting == "yes"
                    print(f"Show previews would be set to {value}")
                else:
                    print("Please enter 'yes' or 'no'.")
            
            else:
                print("Invalid choice.")
            
            print("\nNote: Some settings require application restart to take effect.")
            
        except ValueError:
            print("Please enter a valid number.")

    def show_statistics(self) -> None:
        """Display usage statistics."""
        print("\n" + "-"*40)
        print("STATISTICS")
        print("-"*40)
        
        # Content statistics
        total_items = self.session.query(ContentItem).count()
        youtube_items = self.session.query(ContentItem).filter_by(platform="youtube").count()
        habr_items = self.session.query(ContentItem).filter_by(platform="habr").count()
        coursera_items = self.session.query(ContentItem).filter_by(platform="coursera").count()
        
        print(f"\nContent Statistics:")
        print(f"  Total items: {total_items}")
        print(f"  YouTube: {youtube_items}")
        print(f"  Habr: {habr_items}")
        print(f"  Coursera: {coursera_items}")
        
        # User statistics
        total_users = self.session.query(User).count()
        active_users = self.session.query(UserProgress).distinct(UserProgress.user_id).count()
        
        print(f"\nUser Statistics:")
        print(f"  Total users: {total_users}")
        print(f"  Active users (with progress): {active_users}")
        
        # Completion statistics
        total_completed = self.session.query(UserProgress).filter_by(completed=True).count()
        avg_rating = self.session.query(UserProgress.rating).filter(UserProgress.rating.isnot(None)).scalar()
        
        print(f"\nCompletion Statistics:")
        print(f"  Total completed items: {total_completed}")
        if avg_rating:
            print(f"  Average rating: {avg_rating:.1f}/5")
        
        # Tag statistics
        popular_tags = self.session.query(Tag.name).join(ContentItem.tags).group_by(Tag.name).order_by(
            db.func.count(ContentItem.id).desc()
        ).limit(5).all()
        
        if popular_tags:
            print(f"\nMost Popular Tags:")
            for tag in popular_tags:
                count = self.session.query(ContentItem).join(ContentItem.tags).filter(Tag.name == tag[0]).count()
                print(f"  {tag[0]}: {count} items")
        
        # System health
        db_path = settings.database_url.replace("sqlite:///", "")
        if Path(db_path).exists():
            size_mb = Path(db_path).stat().st_size / (1024 * 1024)
            print(f"\nSystem Health:")
            print(f"  Database size: {size_mb:.2f} MB")
            print(f"  Last update: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")