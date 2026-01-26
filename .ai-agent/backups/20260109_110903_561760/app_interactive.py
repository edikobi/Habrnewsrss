"""Interactive menu for content aggregation system."""
import click
import datetime
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path
from colorama import init, Fore, Back, Style
from sqlalchemy import func

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

    def _ensure_demo_data(self) -> None:
        """Ensure at least one demo user exists and has some content."""
        try:
            user_count = self.session.query(User).count()
            if user_count == 0:
                user = User(username="demo", email="demo@example.com")
                self.session.add(user)
                self.session.flush()

                for tag_name in ["python", "programming", "artificial intelligence"]:
                    interest = UserInterest(user_id=user.id, tag_name=tag_name)
                    self.session.add(interest)

                self.session.commit()
                print(Fore.GREEN + f"✓ Created demo user with ID: {user.id}")

            content_count = self.session.query(ContentItem).count()
            if content_count == 0 and self.sources["habr"]["enabled"]:
                items = self.sources["habr"]["instance"].fetch_content(["python"], 5)
                self.aggregator.save_content_items(items)
                print(Fore.GREEN + f"✓ Added {len(items)} demo content items from Habr")
        except Exception as e:
            print(Fore.YELLOW + f"⚠ Demo data seeding skipped: {e}")

    def run(self) -> None:
        """Main interactive loop."""
        init(autoreset=True)
        self._ensure_demo_data()

        print(Fore.CYAN + "\n" + "="*50)
        print(Fore.CYAN + "EDUCATIONAL CONTENT AGGREGATOR - INTERACTIVE MODE")
        print(Fore.CYAN + "="*50)

        try:
            while True:
                choice = self.show_main_menu()
                if choice == 7:
                    print(Fore.CYAN + "\nGoodbye!")
                    break
        except KeyboardInterrupt:
            print(Fore.CYAN + "\n\nGoodbye!")
        finally:
            self.session.close()

    def show_main_menu(self) -> int:
        """Display main menu options and process user choice."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "MAIN MENU")
        print(Fore.CYAN + "─"*40)
        print(f"{Fore.YELLOW}1.{Fore.WHITE} View content and news")
        print(f"{Fore.YELLOW}2.{Fore.WHITE} Manage sources")
        print(f"{Fore.YELLOW}3.{Fore.WHITE} Search content")
        print(f"{Fore.YELLOW}4.{Fore.WHITE} Get recommendations")
        print(f"{Fore.YELLOW}5.{Fore.WHITE} Configure settings")
        print(f"{Fore.YELLOW}6.{Fore.WHITE} View statistics")
        print(f"{Fore.YELLOW}7.{Fore.WHITE} Exit")
        print(Fore.CYAN + "─"*40)

        while True:
            try:
                choice = int(input(Fore.YELLOW + "\nEnter your choice (1-7): "))
                if 1 <= choice <= 7:
                    break
                print(Fore.RED + "Please enter a number between 1 and 7.")
            except ValueError:
                print(Fore.RED + "Please enter a valid number.")

        if choice == 1:
            self.view_content()
        elif choice == 2:
            self.manage_sources()
        elif choice == 3:
            self.search_content()
        elif choice == 4:
            self.get_recommendations_interactive()
        elif choice == 5:
            self.configure_settings()
        elif choice == 6:
            self.show_statistics()

        return choice

    def view_content(self) -> None:
        """Browse and search content."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "VIEW CONTENT")
        print(Fore.CYAN + "─"*40)

        user_id_input = input(Fore.YELLOW + "Enter user ID for personalized digest (or press Enter for all content): ")

        if user_id_input.strip():
            try:
                user_id = int(user_id_input)
                user = self.session.query(User).get(user_id)
                if not user:
                    print(Fore.RED + f"User with ID {user_id} not found.")
                    return

                print(Fore.WHITE + f"\nGenerating daily digest for user: {Fore.GREEN}{user.username}")
                digest = self.aggregator.get_daily_digest(user_id, max_items=10)

                if not digest:
                    print(Fore.YELLOW + "No content found for your interests.")
                    return

                print(Fore.GREEN + f"\nFound {len(digest)} items:")
                for i, item in enumerate(digest, 1):
                    print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")
                    print(f"   Platform: {Fore.CYAN}{item.platform}{Fore.WHITE} | Difficulty: {Fore.CYAN}{item.difficulty}")
                    print(f"   URL: {Fore.BLUE}{item.url}")
                    print()

                mark_choice = input(Fore.YELLOW + "Enter item number to mark as completed (or 0 to skip): ")
                if mark_choice.isdigit():
                    item_idx = int(mark_choice)
                    if 0 < item_idx <= len(digest):
                        item = digest[item_idx-1]
                        rating = input(Fore.YELLOW + "Rating (1-5, default 5): ")
                        rating = int(rating) if rating.isdigit() else 5
                        notes = input(Fore.YELLOW + "Notes (optional): ")

                        progress = UserProgress(user_id=user_id, content_id=item.id)
                        progress.mark_completed(rating=rating, notes=notes)
                        self.session.add(progress)
                        self.session.commit()
                        print(Fore.GREEN + "Item marked as completed!")

            except ValueError:
                print(Fore.RED + "Invalid user ID.")
        else:
            print(Fore.WHITE + "\nRecent content from all sources:")
            items = self.session.query(ContentItem).order_by(ContentItem.published_at.desc()).limit(20).all()

            for i, item in enumerate(items, 1):
                print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")
                print(f"   Platform: {Fore.CYAN}{item.platform}{Fore.WHITE} | Published: {item.published_at}")
                print(f"   URL: {Fore.BLUE}{item.url}")
                print()

    def manage_sources(self) -> None:
        """Enable/disable and configure sources."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "MANAGE SOURCES")
        print(Fore.CYAN + "─"*40)

        while True:
            print(Fore.WHITE + "\nCurrent source status:")
            for source_name, source_info in self.sources.items():
                status = f"{Fore.GREEN}ENABLED" if source_info["enabled"] else f"{Fore.RED}DISABLED"
                print(f"  {Fore.WHITE}{source_name.upper():10} : {status}")

            print(Fore.WHITE + "\nOptions:")
            print(f"{Fore.YELLOW}1.{Fore.WHITE} Enable/disable source")
            print(f"{Fore.YELLOW}2.{Fore.WHITE} Configure API keys")
            print(f"{Fore.YELLOW}3.{Fore.WHITE} Set content limits")
            print(f"{Fore.YELLOW}4.{Fore.WHITE} Test source connection")
            print(f"{Fore.YELLOW}5.{Fore.WHITE} Return to main menu")

            try:
                choice = int(input(Fore.YELLOW + "\nEnter choice (1-5): "))
                if choice == 5:
                    break

                if choice == 1:
                    source_name = input(Fore.YELLOW + "Enter source name (youtube/habr/coursera): ").lower()
                    if source_name in self.sources:
                        current = self.sources[source_name]["enabled"]
                        self.sources[source_name]["enabled"] = not current
                        status = f"{Fore.GREEN}enabled" if not current else f"{Fore.RED}disabled"
                        print(Fore.GREEN + f"{source_name} has been {status}.")
                    else:
                        print(Fore.RED + "Invalid source name.")

                elif choice == 2:
                    source_name = input(Fore.YELLOW + "Enter source name (youtube/coursera): ").lower()
                    if source_name in ["youtube", "coursera"]:
                        api_key = input(Fore.YELLOW + f"Enter {source_name} API key (press Enter to keep current): ")
                        if api_key:
                            print(Fore.GREEN + f"API key for {source_name} would be saved to configuration.")
                            print(Fore.YELLOW + "Note: Restart required for changes to take effect.")
                    else:
                        print(Fore.RED + "API key configuration only available for YouTube and Coursera.")

                elif choice == 3:
                    source_name = input(Fore.YELLOW + "Enter source name (youtube/habr/coursera): ").lower()
                    if source_name in self.sources:
                        try:
                            limit = int(input(Fore.YELLOW + f"Enter max results for {source_name} (current: {getattr(settings, f'{source_name}_max_results', 50)}): "))
                            if limit > 0:
                                print(Fore.GREEN + f"Limit for {source_name} would be set to {limit}.")
                                print(Fore.YELLOW + "Note: Changes apply to next content update.")
                            else:
                                print(Fore.RED + "Limit must be positive.")
                        except ValueError:
                            print(Fore.RED + "Please enter a valid number.")
                    else:
                        print(Fore.RED + "Invalid source name.")

                elif choice == 4:
                    source_name = input(Fore.YELLOW + "Enter source name to test (youtube/habr/coursera): ").lower()
                    if source_name in self.sources:
                        if self.sources[source_name]["enabled"]:
                            print(Fore.WHITE + f"Testing {source_name} connection...")
                            try:
                                source = self.sources[source_name]["instance"]
                                test_items = source.fetch_content(["python"], 1)
                                if test_items:
                                    print(Fore.GREEN + f"✓ {source_name} connection successful. Found {len(test_items)} test items.")
                                else:
                                    print(Fore.YELLOW + f"⚠ {source_name} connected but returned no results.")
                            except Exception as e:
                                print(Fore.RED + f"✗ {source_name} connection failed: {e}")
                        else:
                            print(Fore.RED + f"{source_name} is disabled. Enable it first.")
                    else:
                        print(Fore.RED + "Invalid source name.")

            except ValueError:
                print(Fore.RED + "Please enter a valid number.")

    def search_content(self) -> None:
        """Interactive search across all sources."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "SEARCH CONTENT")
        print(Fore.CYAN + "─"*40)

        keywords_input = input(Fore.YELLOW + "Enter search keywords (comma-separated): ")
        keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]

        if not keywords:
            print(Fore.RED + "No keywords provided.")
            return

        print(Fore.WHITE + "\nAvailable sources: youtube, habr, coursera, all")
        source_filter = input(Fore.YELLOW + "Filter by source (default: all): ").lower() or "all"

        print(Fore.WHITE + "\nDifficulty levels: beginner, intermediate, advanced, all")
        difficulty_filter = input(Fore.YELLOW + "Filter by difficulty (default: all): ").lower() or "all"

        try:
            max_results = int(input(Fore.YELLOW + "Maximum results (default: 50): ") or "50")
        except ValueError:
            max_results = 50

        print(Fore.WHITE + f"\nSearching for: {Fore.GREEN}{', '.join(keywords)}")
        if source_filter != "all":
            print(Fore.WHITE + f"Source filter: {Fore.CYAN}{source_filter}")
        if difficulty_filter != "all":
            print(Fore.WHITE + f"Difficulty filter: {Fore.CYAN}{difficulty_filter}")

        results = self.aggregator.search_content(keywords, source_filter, difficulty_filter, max_results)

        print(Fore.GREEN + f"\nFound {len(results)} results:")
        for i, item in enumerate(results, 1):
            print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")
            print(f"   Platform: {Fore.CYAN}{item.platform}{Fore.WHITE} | Difficulty: {Fore.CYAN}{item.difficulty}")
            print(f"   Published: {item.published_at}")
            print(f"   URL: {Fore.BLUE}{item.url}")
            if item.description and len(item.description) > 100:
                print(f"   Description: {Fore.WHITE}{item.description[:100]}...")
            print()

    def get_recommendations_interactive(self) -> None:
        """Interactive menu for getting personalized recommendations."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "GET RECOMMENDATIONS")
        print(Fore.CYAN + "─"*40)

        try:
            user_id_input = input(Fore.YELLOW + "Enter user ID: ")
            user_id = int(user_id_input)
            user = self.session.query(User).get(user_id)
            if not user:
                print(Fore.RED + "User not found.")
                return

            max_recs_input = input(Fore.YELLOW + "Max recommendations (default 5): ")
            max_recs = int(max_recs_input) if max_recs_input.isdigit() else 5

            recs = self.recommender.get_recommendations(user_id, max_recs)

            if not recs:
                print(Fore.YELLOW + "No recommendations found. Try adding more interests or completing content.")
                return

            print(Fore.GREEN + f"\nTop {len(recs)} recommendations for {user.username}:")
            for i, item in enumerate(recs, 1):
                print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")
                print(f"   Platform: {Fore.CYAN}{item.platform}{Fore.WHITE} | Difficulty: {Fore.CYAN}{item.difficulty}")
                print(f"   URL: {Fore.BLUE}{item.url}")
                print()

            mark_choice = input(Fore.YELLOW + "Enter item number to mark as completed (or 0 to skip): ")
            if mark_choice.isdigit():
                item_idx = int(mark_choice)
                if 0 < item_idx <= len(recs):
                    item = recs[item_idx-1]
                    rating = input(Fore.YELLOW + "Rating (1-5, default 5): ")
                    rating = int(rating) if rating.isdigit() else 5
                    notes = input(Fore.YELLOW + "Notes (optional): ")

                    progress = UserProgress(user_id=user_id, content_id=item.id)
                    progress.mark_completed(rating=rating, notes=notes)
                    self.session.add(progress)
                    self.session.commit()
                    print(Fore.GREEN + "Item marked as completed!")

        except ValueError:
            print(Fore.RED + "Invalid input.")
        except Exception as e:
            print(Fore.RED + f"Error: {e}")

    def configure_settings(self) -> None:
        """Update application settings."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "CONFIGURE SETTINGS")
        print(Fore.CYAN + "─"*40)

        print(Fore.WHITE + "\nCurrent settings:")
        print(f"{Fore.YELLOW}1.{Fore.WHITE} Daily digest hour: {Fore.GREEN}{settings.daily_digest_hour}:00")
        print(f"{Fore.YELLOW}2.{Fore.WHITE} Content update interval: {Fore.GREEN}{settings.content_update_interval_hours} hours")
        print(f"{Fore.YELLOW}3.{Fore.WHITE} Max recommendations per day: {Fore.GREEN}{settings.max_recommendations_per_day}")
        print(f"{Fore.YELLOW}4.{Fore.WHITE} Database location: {Fore.GREEN}{settings.database_url}")
        print(f"{Fore.YELLOW}5.{Fore.WHITE} Interactive pagination size: {Fore.GREEN}{getattr(settings, 'interactive_pagination_size', 10)}")
        print(f"{Fore.YELLOW}6.{Fore.WHITE} Show previews in interactive mode: {Fore.GREEN}{getattr(settings, 'interactive_show_previews', True)}")

        print(Fore.YELLOW + "\nEnter setting number to modify (or 0 to return): ")
        try:
            choice = int(input(Fore.YELLOW + "Choice: "))
            if choice == 0:
                return

            if choice == 1:
                new_hour = int(input(Fore.YELLOW + "New daily digest hour (0-23): "))
                if 0 <= new_hour <= 23:
                    print(Fore.GREEN + f"Daily digest hour would be set to {new_hour}:00")
                else:
                    print(Fore.RED + "Hour must be between 0 and 23.")

            elif choice == 2:
                new_interval = int(input(Fore.YELLOW + "New update interval (hours, 1-168): "))
                if 1 <= new_interval <= 168:
                    print(Fore.GREEN + f"Update interval would be set to {new_interval} hours")
                else:
                    print(Fore.RED + "Interval must be between 1 and 168 hours (1 week).")

            elif choice == 3:
                new_max = int(input(Fore.YELLOW + "New max recommendations (1-50): "))
                if 1 <= new_max <= 50:
                    print(Fore.GREEN + f"Max recommendations would be set to {new_max}")
                else:
                    print(Fore.RED + "Must be between 1 and 50.")

            elif choice == 4:
                new_db = input(Fore.YELLOW + "New database path (e.g., sqlite:///new.db): ")
                if new_db.startswith("sqlite:///"):
                    print(Fore.GREEN + f"Database location would be set to {new_db}")
                else:
                    print(Fore.RED + "Database URL must start with 'sqlite:///'")

            elif choice == 5:
                new_size = int(input(Fore.YELLOW + "New pagination size (5-50): "))
                if 5 <= new_size <= 50:
                    print(Fore.GREEN + f"Pagination size would be set to {new_size}")
                else:
                    print(Fore.RED + "Must be between 5 and 50.")

            elif choice == 6:
                new_setting = input(Fore.YELLOW + "Show previews? (yes/no): ").lower()
                if new_setting in ["yes", "no"]:
                    value = new_setting == "yes"
                    print(Fore.GREEN + f"Show previews would be set to {value}")
                else:
                    print(Fore.RED + "Please enter 'yes' or 'no'.")

            else:
                print(Fore.RED + "Invalid choice.")

            print(Fore.YELLOW + "\nNote: Some settings require application restart to take effect.")

        except ValueError:
            print(Fore.RED + "Please enter a valid number.")

    def show_statistics(self) -> None:
        """Display usage statistics."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "STATISTICS")
        print(Fore.CYAN + "─"*40)

        # Content statistics
        total_items = self.session.query(ContentItem).count()
        youtube_items = self.session.query(ContentItem).filter_by(platform="youtube").count()
        habr_items = self.session.query(ContentItem).filter_by(platform="habr").count()
        coursera_items = self.session.query(ContentItem).filter_by(platform="coursera").count()

        print(Fore.CYAN + "\nContent Statistics:")
        print(f"  {Fore.WHITE}Total items: {Fore.GREEN}{total_items}")
        print(f"  {Fore.WHITE}YouTube: {Fore.GREEN}{youtube_items}")
        print(f"  {Fore.WHITE}Habr: {Fore.GREEN}{habr_items}")
        print(f"  {Fore.WHITE}Coursera: {Fore.GREEN}{coursera_items}")

        # User statistics
        total_users = self.session.query(User).count()
        active_users = self.session.query(UserProgress).distinct(UserProgress.user_id).count()

        print(Fore.CYAN + "\nUser Statistics:")
        print(f"  {Fore.WHITE}Total users: {Fore.GREEN}{total_users}")
        print(f"  {Fore.WHITE}Active users (with progress): {Fore.GREEN}{active_users}")

        # Completion statistics
        total_completed = self.session.query(UserProgress).filter_by(completed=True).count()
        avg_rating = self.session.query(func.avg(UserProgress.rating)).filter(UserProgress.rating.isnot(None)).scalar()

        print(Fore.CYAN + "\nCompletion Statistics:")
        print(f"  {Fore.WHITE}Total completed items: {Fore.GREEN}{total_completed}")
        if avg_rating:
            print(f"  {Fore.WHITE}Average rating: {Fore.GREEN}{avg_rating:.1f}/5")

        # Tag statistics
        popular_tags = self.session.query(Tag.name).join(ContentItem.tags).group_by(Tag.name).order_by(
            func.count(ContentItem.id).desc()
        ).limit(5).all()

        if popular_tags:
            print(Fore.CYAN + "\nMost Popular Tags:")
            for tag in popular_tags:
                count = self.session.query(ContentItem).join(ContentItem.tags).filter(Tag.name == tag[0]).count()
                print(f"  {Fore.WHITE}{tag[0]}: {Fore.GREEN}{count} items")

        # System health
        db_path = settings.database_url.replace("sqlite:///", "")
        if Path(db_path).exists():
            size_mb = Path(db_path).stat().st_size / (1024 * 1024)
            print(Fore.CYAN + "\nSystem Health:")
            print(f"  {Fore.WHITE}Database size: {Fore.GREEN}{size_mb:.2f} MB")
            print(f"  {Fore.WHITE}Last update: {Fore.GREEN}{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
