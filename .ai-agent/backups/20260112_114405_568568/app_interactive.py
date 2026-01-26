from app.database import (
    get_db_session, User, ContentItem, UserInterest, 
    UserProgress, Tag, SessionLocal
)
from app.database import UserSettings, FavoriteContent

import datetime
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from sqlalchemy import func
import click
from colorama import init, Fore, Back, Style

from app.database import (
    get_db_session, User, ContentItem, UserInterest, 
    UserProgress, Tag, SessionLocal, UserSettings, FavoriteContent
)
from app.services.aggregator import ContentAggregator, update_all_content
from app.services.recommender import ContentRecommender
from app.services.email_sender import EmailSender
from app.config import settings
from app.sources.youtube import YouTubeSource
from app.sources.habr import HabrSource
from app.sources.coursera import CourseraSource

logger = logging.getLogger(__name__)


class InteractiveMenu:
    """Интерактивное меню для системы агрегации контента с управлением источниками и поиском."""

    def __init__(self):
        self.session = SessionLocal()
        self.aggregator = ContentAggregator(db_session=self.session)
        self.recommender = ContentRecommender(db_session=self.session)
        self.email_sender = EmailSender()
        self.sources = {
            "youtube": {"enabled": bool(settings.youtube_api_key), "instance": YouTubeSource()},
            "habr": {"enabled": True, "instance": HabrSource()},
            "coursera": {"enabled": bool(settings.coursera_api_key), "instance": CourseraSource()},
        }
        self.current_user_id: Optional[int] = None

        # Load saved user ID if available
        try:
            saved_id = self._load_current_user_id()
            if saved_id is not None:
                self.current_user_id = saved_id
        except Exception as e:
            logger.warning(f"Failed to load saved user ID: {e}")

    def _get_current_user_file_path(self) -> Path:
        """Get path to .current_user file in project root directory."""
        return Path.cwd() / '.current_user'

    def _load_current_user_id(self) -> Optional[int]:
        """Load current user ID from .current_user file if it exists and contains valid integer."""
        try:
            path = self._get_current_user_file_path()
            if path.exists():
                content = path.read_text(encoding='utf-8').strip()
                if content and content.isdigit():
                    return int(content)
            return None
        except Exception as e:
            logger.warning(f"Failed to load current user ID: {e}")
            return None

    def _save_current_user_id(self, user_id: Optional[int]) -> None:
        """Save current user ID to .current_user file. If user_id is None, delete the file."""
        try:
            path = self._get_current_user_file_path()
            if user_id is None or user_id <= 0:
                path.unlink(missing_ok=True)
                return
            path.write_text(str(user_id), encoding='utf-8')
        except Exception as e:
            logger.warning(f"Failed to save current user ID: {e}")

    def _ensure_demo_data(self) -> None:
        """Обеспечить наличие демо-пользователя и контента."""
        try:
            user_count = self.session.query(User).count()
            if user_count == 0:
                user = User(username="demo", email="demo@example.com")
                self.session.add(user)
                self.session.flush()

                # Create default settings
                settings_obj = UserSettings(user_id=user.id, email_digest=user.email)
                self.session.add(settings_obj)

                for tag_name in ["python", "programming", "artificial intelligence"]:
                    interest = UserInterest(user_id=user.id, tag_name=tag_name)
                    self.session.add(interest)

                self.session.commit()
                print(Fore.GREEN + f"✓ Создан демо-пользователь с ID: {user.id}")

            content_count = self.session.query(ContentItem).count()
            if content_count == 0 and self.sources["habr"]["enabled"]:
                items = self.sources["habr"]["instance"].fetch_content(["python"], 5)
                self.aggregator.save_content_items(items)
                print(Fore.GREEN + f"✓ Добавлено {len(items)} демо-элементов контента из Habr")
        except Exception as e:
            print(Fore.YELLOW + f"⚠ Создание демо-данных пропущено: {e}")

    def add_new_user_interactive(self) -> None:
        """Interactively add a new user with username and email, creating default settings."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "ДОБАВЛЕНИЕ НОВОГО ПОЛЬЗОВАТЕЛЯ")
        print(Fore.CYAN + "─"*40)

        username = input(Fore.YELLOW + "Введите имя пользователя: ").strip()
        if not username:
            print(Fore.RED + "Имя пользователя не может быть пустым.")
            return

        email = input(Fore.YELLOW + "Введите email: ").strip()
        if not email or "@" not in email:
            print(Fore.RED + "Некорректный email.")
            return

        try:
            existing = self.session.query(User).filter(
                (User.username == username) | (User.email == email)
            ).first()

            if existing:
                print(Fore.RED + "Пользователь с таким именем или email уже существует.")
                return

            user = User(username=username, email=email)
            self.session.add(user)
            self.session.flush()

            settings_obj = UserSettings(user_id=user.id, email_digest=email)
            self.session.add(settings_obj)

            self.session.commit()
            self.current_user_id = user.id

            # Save selection to file
            try:
                self._save_current_user_id(user.id)
            except Exception as e:
                logger.warning(f"Failed to save user selection: {e}")
            print(Fore.GREEN + f"✓ Пользователь создан! ID: {user.id}")
            print(Fore.YELLOW + "Теперь вы можете настроить интересы в меню настроек.")
        except Exception as e:
            self.session.rollback()
            print(Fore.RED + f"Ошибка при создании пользователя: {e}")

    def run(self) -> None:
            """Основной интерактивный цикл."""
            init(autoreset=True)
            self._ensure_demo_data()

            # Проверка пропущенных обновлений контента при запуске
            try:
                click.echo(Fore.CYAN + "Проверка пропущенных обновлений контента...")
                aggregator = ContentAggregator()
                results = aggregator.check_and_update_content_for_all_users()
                if results:
                    total = sum(results.values())
                    click.echo(Fore.GREEN + f"✓ Добавлено {total} пропущенных статей в базу данных")
                    for user_id, count in results.items():
                        if count > 0:
                            click.echo(Fore.GREEN + f"  Пользователь {user_id}: {count} элементов")
                else:
                    click.echo(Fore.YELLOW + "✓ Нет пропущенных обновлений контента")
            except Exception as e:
                logger.error(f"Ошибка проверки пропущенных обновлений контента: {e}")
                click.echo(Fore.RED + f"⚠ Ошибка проверки обновлений: {e}")

            # Check for missed digests on startup
            try:
                missed = self.aggregator.check_missed_digests()
                if any(missed.values()):
                    print(Fore.GREEN + "✓ Отправлены пропущенные подборки на email")
            except Exception as e:
                logger.error(f"Error checking missed digests: {e}")

            # Try to restore last user from saved file (already done in __init__)
            # If still no user selected and there are users, optionally select first user
            try:
                if self.current_user_id is None:
                    users = self.session.query(User).all()
                    if users and len(users) == 1:
                        self.current_user_id = users[0].id
                        print(Fore.YELLOW + f"Автоматически выбран пользователь: {users[0].username}")
            except Exception as e:
                logger.error(f"Error restoring user: {e}")

            print(Fore.CYAN + "\n" + "="*50)
            print(Fore.CYAN + "АГРЕГАТОР ОБРАЗОВАТЕЛЬНОГО КОНТЕНТА - ИНТЕРАКТИВНЫЙ РЕЖИМ")
            print(Fore.CYAN + "="*50)

            try:
                while True:
                    choice = self.show_main_menu()
                    if choice == 8:
                        print(Fore.CYAN + "\nДо свидания!")
                        break
            except KeyboardInterrupt:
                print(Fore.CYAN + "\n\nДо свидания!")
            finally:
                self.session.close()

    def show_main_menu(self) -> int:
            """Показать главное меню и обработать выбор пользователя."""
            print(Fore.CYAN + "\n" + "═"*40)
            print(Fore.CYAN + "ГЛАВНОЕ МЕНЮ")
            print(Fore.CYAN + "─"*40)

            if self.current_user_id:
                user = self.session.query(User).get(self.current_user_id)
                if user:
                    print(f"{Fore.GREEN}Текущий пользователь: {user.username} (ID: {user.id})")

            print(f"{Fore.YELLOW}1.{Fore.WHITE} Просмотр контента и новостей")
            print(f"{Fore.YELLOW}2.{Fore.WHITE} Управление источниками")
            print(f"{Fore.YELLOW}3.{Fore.WHITE} Поиск контента")
            print(f"{Fore.YELLOW}4.{Fore.WHITE} Получить рекомендации")
            print(f"{Fore.YELLOW}5.{Fore.WHITE} Настройки пользователя")
            print(f"{Fore.YELLOW}6.{Fore.WHITE} Просмотр статистики")
            print(f"{Fore.YELLOW}7.{Fore.WHITE} Просмотр всех статей из БД")
            print(f"{Fore.YELLOW}8.{Fore.WHITE} Выход")
            print(Fore.CYAN + "─"*40)

            while True:
                try:
                    choice = int(input(Fore.YELLOW + "\nВведите ваш выбор (1-8): "))
                    if 1 <= choice <= 8:
                        break
                    print(Fore.RED + "Пожалуйста, введите число от 1 до 8.")
                except ValueError:
                    print(Fore.RED + "Пожалуйста, введите корректное число.")

            if choice == 1:
                self.view_content()
            elif choice == 2:
                self.manage_sources()
            elif choice == 3:
                self.search_content()
            elif choice == 4:
                self.get_recommendations_interactive()
            elif choice == 5:
                self.configure_user_settings()
            elif choice == 6:
                self.show_statistics()
            elif choice == 7:
                self.view_all_content_from_db()

            return choice

    def view_content(self) -> None:
        """Просмотр и поиск контента с возможностью добавления в избранное."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "ПРОСМОТР КОНТЕНТА")
        print(Fore.CYAN + "─"*40)

        # If no current user, ask for user ID
        if not self.current_user_id:
            users = self.session.query(User).all()
            if users:
                print(Fore.CYAN + "\nВыберите пользователя:")
                for u in users:
                    print(f"ID: {u.id} | {u.username}")
                uid = input(Fore.YELLOW + "Введите ID или нажмите Enter для пропуска: ")
                if uid.isdigit():
                    self.current_user_id = int(uid)
                else:
                    print(Fore.YELLOW + "Поиск без пользователя...")

        user_id = self.current_user_id

        if user_id:
            try:
                user = self.session.query(User).get(user_id)
                if not user:
                    print(Fore.RED + f"Пользователь с ID {user_id} не найден.")
                    return

                print(Fore.WHITE + f"\nГенерация ежедневной подборки для пользователя: {Fore.GREEN}{user.username}")
                digest = self.aggregator.get_daily_digest(user_id, max_items=15)

                if not digest:
                    print(Fore.YELLOW + "Контент не найден.")
                    return

                print(Fore.GREEN + f"\nНайдено {len(digest)} элементов:")
                for i, item in enumerate(digest, 1):
                    pub_date = item.published_at.strftime('%Y-%m-%d %H:%M') if item.published_at else "Неизвестно"
                    add_date = item.added_at.strftime('%Y-%m-%d %H:%M') if item.added_at else "Неизвестно"
                    print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")
                    print(f"   Платформа: {Fore.CYAN}{item.platform}{Fore.WHITE} | Сложность: {Fore.CYAN}{item.difficulty}")
                    print(f"   Опубликовано: {pub_date} | Добавлено: {add_date}")
                    print(f"   URL: {Fore.BLUE}{item.url}")
                    print()

                choice = input(Fore.YELLOW + "Введите номер для деталей/отметки или 0 для выхода: ")
                if choice.isdigit() and 0 < int(choice) <= len(digest):
                    self.view_content_details(digest[int(choice)-1].id)

            except Exception as e:
                print(Fore.RED + f"Ошибка: {e}")
        else:
            print(Fore.WHITE + "\nНедавний контент из всех источников:")
            items = self.session.query(ContentItem).order_by(ContentItem.published_at.desc()).limit(20).all()

            for i, item in enumerate(items, 1):
                pub_date = item.published_at.strftime('%Y-%m-%d %H:%M') if item.published_at else "Неизвестно"
                add_date = item.added_at.strftime('%Y-%m-%d %H:%M') if item.added_at else "Неизвестно"
                print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")
                print(f"   Платформа: {Fore.CYAN}{item.platform}{Fore.WHITE} | Опубликовано: {pub_date}")
                print(f"   Добавлено: {add_date}")
                print(f"   URL: {Fore.BLUE}{item.url}")
                print()

    def view_content_details(self, content_id: int) -> None:
        """Display detailed information about a specific content item including full text or description, tags, and dates."""
        try:
            item = self.session.query(ContentItem).get(content_id)
            if not item:
                print(Fore.RED + "Контент не найден.")
                return

            print(Fore.CYAN + "\n" + "═"*40)
            print(Fore.WHITE + f"ЗАГОЛОВОК: {Fore.GREEN}{item.title}")
            print(Fore.WHITE + f"ПЛАТФОРМА: {Fore.CYAN}{item.platform}")
            print(Fore.WHITE + f"URL: {Fore.BLUE}{item.url}")
            print(Fore.WHITE + f"СЛОЖНОСТЬ: {Fore.CYAN}{item.difficulty}")

            pub_date = item.published_at.strftime('%Y-%m-%d %H:%M') if item.published_at else "Неизвестно"
            add_date = item.added_at.strftime('%Y-%m-%d %H:%M') if item.added_at else "Неизвестно"
            print(Fore.WHITE + f"ОПУБЛИКОВАНО: {pub_date}")
            print(Fore.WHITE + f"ДОБАВЛЕНО: {add_date}")

            # Display full text with smart pagination
            if item.full_text and item.full_text.strip():
                print(Fore.WHITE + "\nПОЛНЫЙ ТЕКСТ СТАТЬИ:")
                full_text_len = len(item.full_text)
                print(Fore.CYAN + f"(Длина: {full_text_len} символов)")

                try:
                    chunk_size = 2000
                    current_pos = 0

                    while current_pos < full_text_len:
                        # Show current chunk
                        chunk = item.full_text[current_pos:current_pos + chunk_size]
                        print(Fore.WHITE + chunk)
                        current_pos += chunk_size

                        # If more text remains, ask user what to do
                        if current_pos < full_text_len:
                            remaining = full_text_len - current_pos
                            print(Fore.YELLOW + f"\n[Осталось {remaining} символов]")
                            print(Fore.YELLOW + "Enter - продолжить | 'a' - показать все | 's' - пропустить: ", end='')
                            pagination_choice = input().lower().strip()

                            if pagination_choice == 'a':
                                # Show all remaining text
                                print(Fore.WHITE + item.full_text[current_pos:])
                                break
                            elif pagination_choice == 's':
                                # Skip remaining text
                                print(Fore.YELLOW + "\n[Остальной текст пропущен. Полная версия доступна по ссылке]")
                                break
                            # else: continue loop (Enter pressed)
                except KeyboardInterrupt:
                    print(Fore.YELLOW + "\n[Просмотр текста прерван]")
            else:
                print(Fore.WHITE + "\nОПИСАНИЕ:")
                print(Fore.WHITE + (item.description or "Нет описания"))

            tags = ", ".join([t.name for t in item.tags])
            print(Fore.WHITE + f"\nТЕГИ: {Fore.YELLOW}{tags}")
            print(Fore.CYAN + "─"*40)

            if self.current_user_id:
                print(f"{Fore.YELLOW}1.{Fore.WHITE} Отметить как завершенное")
                print(f"{Fore.YELLOW}2.{Fore.WHITE} Добавить в избранное")
                print(f"{Fore.YELLOW}3.{Fore.WHITE} Назад к списку")

                choice = input(Fore.YELLOW + "\nВыбор: ")
                if choice == "1":
                    rating = input(Fore.YELLOW + "Оценка (1-5, по умолчанию 5): ")
                    rating = int(rating) if rating.isdigit() else 5
                    notes = input(Fore.YELLOW + "Заметки: ")
                    progress = UserProgress(user_id=self.current_user_id, content_id=item.id)
                    progress.mark_completed(rating=rating, notes=notes)
                    self.session.add(progress)
                    self.session.commit()
                    print(Fore.GREEN + "✓ Отмечено как завершенное!")
                elif choice == "2":
                    fav = FavoriteContent(user_id=self.current_user_id, content_id=item.id)
                    self.session.add(fav)
                    self.session.commit()
                    print(Fore.GREEN + "✓ Добавлено в избранное!")
        except Exception as e:
            print(Fore.RED + f"Ошибка при просмотре деталей: {e}")

    def manage_sources(self) -> None:
        """Включить/выключить и настроить источники."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "УПРАВЛЕНИЕ ИСТОЧНИКАМИ")
        print(Fore.CYAN + "─"*40)

        while True:
            print(Fore.WHITE + "\nТекущий статус источников:")
            for source_name, source_info in self.sources.items():
                status = f"{Fore.GREEN}ВКЛЮЧЕН" if source_info["enabled"] else f"{Fore.RED}ВЫКЛЮЧЕН"
                print(f"  {Fore.WHITE}{source_name.upper():10} : {status}")

            print(Fore.WHITE + "\nОпции:")
            print(f"{Fore.YELLOW}1.{Fore.WHITE} Включить/выключить источник")
            print(f"{Fore.YELLOW}2.{Fore.WHITE} Настроить API ключи")
            print(f"{Fore.YELLOW}3.{Fore.WHITE} Установить лимиты контента")
            print(f"{Fore.YELLOW}4.{Fore.WHITE} Проверить подключение источника")
            print(f"{Fore.YELLOW}5.{Fore.WHITE} Вернуться в главное меню")

            try:
                choice = int(input(Fore.YELLOW + "\nВведите выбор (1-5): "))
                if choice == 5:
                    break

                if choice == 1:
                    source_name = input(Fore.YELLOW + "Введите название источника (youtube/habr/coursera): ").lower()
                    if source_name in self.sources:
                        current = self.sources[source_name]["enabled"]
                        self.sources[source_name]["enabled"] = not current
                        status = f"{Fore.GREEN}включен" if not current else f"{Fore.RED}выключен"
                        print(Fore.GREEN + f"{source_name} был {status}.")
                    else:
                        print(Fore.RED + "Неверное название источника.")

                elif choice == 2:
                    source_name = input(Fore.YELLOW + "Введите название источника (youtube/coursera): ").lower()
                    if source_name in ["youtube", "coursera"]:
                        api_key = input(Fore.YELLOW + f"Введите API ключ для {source_name} (нажмите Enter для сохранения текущего): ")
                        if api_key:
                            print(Fore.GREEN + f"API ключ для {source_name} будет сохранен в конфигурации.")
                            print(Fore.YELLOW + "Примечание: требуется перезапуск для применения изменений.")
                    else:
                        print(Fore.RED + "Настройка API ключей доступна только для YouTube и Coursera.")

                elif choice == 3:
                    source_name = input(Fore.YELLOW + "Введите название источника (youtube/habr/coursera): ").lower()
                    if source_name in self.sources:
                        try:
                            limit = int(input(Fore.YELLOW + f"Введите максимальное количество результатов для {source_name} (текущее: {getattr(settings, f'{source_name}_max_results', 50)}): "))
                            if limit > 0:
                                print(Fore.GREEN + f"Лимит для {source_name} будет установлен в {limit}.")
                                print(Fore.YELLOW + "Примечание: изменения применятся при следующем обновлении контента.")
                            else:
                                print(Fore.RED + "Лимит должен быть положительным.")
                        except ValueError:
                            print(Fore.RED + "Пожалуйста, введите корректное число.")
                    else:
                        print(Fore.RED + "Неверное название источника.")

                elif choice == 4:
                    source_name = input(Fore.YELLOW + "Введите название источника для теста (youtube/habr/coursera): ").lower()
                    if source_name in self.sources:
                        if self.sources[source_name]["enabled"]:
                            print(Fore.WHITE + f"Тестирование подключения {source_name}...")
                            try:
                                source = self.sources[source_name]["instance"]
                                test_items = source.fetch_content(["python"], 1)
                                if test_items:
                                    print(Fore.GREEN + f"✓ Подключение {source_name} успешно. Найдено {len(test_items)} тестовых элементов.")
                                else:
                                    print(Fore.YELLOW + f"⚠ {source_name} подключен, но не вернул результатов.")
                            except Exception as e:
                                print(Fore.RED + f"✗ Подключение {source_name} не удалось: {e}")
                        else:
                            print(Fore.RED + f"{source_name} выключен. Включите его сначала.")
                    else:
                        print(Fore.RED + "Неверное название источника.")

            except ValueError:
                print(Fore.RED + "Пожалуйста, введите корректное число.")

    def search_content(self) -> None:
        """Интерактивный поиск с возможностью сохранения и добавления в избранное."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "ПОИСК КОНТЕНТА")
        print(Fore.CYAN + "─"*40)

        keywords_input = input(Fore.YELLOW + "Введите ключевые слова для поиска (через запятую): ")
        keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]

        if not keywords:
            print(Fore.RED + "Ключевые слова не указаны.")
            return

        source_filter = input(Fore.YELLOW + "Фильтр по источнику (youtube/habr/coursera/all): ").lower() or "all"
        mode = input(Fore.YELLOW + "Искать в базе данных или в интернете? (db/internet): ").lower() or "db"

        if mode == "internet":
            results = []

            if source_filter == "all":
                # Fetch from all enabled sources
                for source_name, source_info in self.sources.items():
                    if source_info["enabled"]:
                        try:
                            source_instance = source_info["instance"]
                            items = source_instance.fetch_content(keywords, 10)
                            results.extend(items)
                            print(Fore.GREEN + f"Найдено {len(items)} результатов из {source_name}")
                        except Exception as e:
                            print(Fore.YELLOW + f"Ошибка при поиске в {source_name}: {e}")
            else:
                # Fetch from specific source
                if source_filter in self.sources and self.sources[source_filter]["enabled"]:
                    try:
                        source_instance = self.sources[source_filter]["instance"]
                        results = source_instance.fetch_content(keywords, 30)
                    except Exception as e:
                        print(Fore.RED + f"Ошибка при поиске: {e}")
                        return
                else:
                    print(Fore.RED + f"Источник {source_filter} недоступен или выключен.")
                    return

            if not results:
                print(Fore.YELLOW + "Ничего не найдено в сети.")
                return

            for i, item in enumerate(results, 1):
                print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title} [{item.platform}]")

            save_choice = input(Fore.YELLOW + "\nСохранить в БД и добавить в избранное? (номера через запятую или 0): ")
            if save_choice and save_choice != "0":
                try:
                    indices = [int(i.strip()) - 1 for i in save_choice.split(",") if i.strip().isdigit()]
                    selected = [results[i] for i in indices if 0 <= i < len(results)]

                    # Save using aggregator to ensure full text loading
                    count = self.aggregator.save_content_items(selected)

                    if self.current_user_id and count > 0:
                        # Add to favorites
                        for item in selected:
                            db_item = self.session.query(ContentItem).filter_by(
                                source_id=item.source_id, 
                                platform=item.platform
                            ).first()
                            if db_item:
                                fav = FavoriteContent(user_id=self.current_user_id, content_id=db_item.id)
                                self.session.add(fav)
                        self.session.commit()
                    print(Fore.GREEN + f"Сохранено {count} элементов в БД.")
                except Exception as e:
                    print(Fore.RED + f"Ошибка при сохранении: {e}")
        else:
            results = self.aggregator.search_content(keywords, source_filter)
            for i, item in enumerate(results, 1):
                add_date = item.added_at.strftime('%Y-%m-%d %H:%M') if item.added_at else "Неизвестно"
                print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title} ({item.platform}) | Добавлено: {add_date}")

            if self.current_user_id and results:
                fav_choice = input(Fore.YELLOW + "\nДобавить элементы в избранное? (номера через запятую или 0): ")
                if fav_choice and fav_choice != "0":
                    try:
                        indices = [int(i.strip()) - 1 for i in fav_choice.split(",") if i.strip().isdigit()]
                        for idx in indices:
                            if 0 <= idx < len(results):
                                fav = FavoriteContent(user_id=self.current_user_id, content_id=results[idx].id)
                                self.session.add(fav)
                        self.session.commit()
                        print(Fore.GREEN + f"Добавлено {len(indices)} элементов в избранное.")
                    except Exception as e:
                        print(Fore.RED + f"Ошибка: {e}")

    def view_saved_content(self) -> None:
        """Просмотр сохраненного контента пользователя (избранное и недавно добавленное)."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "СОХРАНЕННЫЙ КОНТЕНТ")
        print(Fore.CYAN + "─"*40)

        if not self.current_user_id:
            users = self.session.query(User).all()
            if users:
                print(Fore.CYAN + "\nВыберите пользователя:")
                for u in users:
                    print(f"ID: {u.id} | {u.username}")
                uid = input(Fore.YELLOW + "Введите ID или нажмите Enter для отмены: ")
                if uid.isdigit():
                    self.current_user_id = int(uid)
                else:
                    return
            else:
                print(Fore.RED + "Пользователи не найдены.")
                return

        try:
            while True:
                # Query favorites
                favorites = self.session.query(ContentItem).join(FavoriteContent).filter(
                    FavoriteContent.user_id == self.current_user_id
                ).all()

                # Query recent
                recent = self.session.query(ContentItem).order_by(ContentItem.added_at.desc()).limit(20).all()

                # Combine and deduplicate
                combined = {item.id: item for item in favorites}
                for item in recent:
                    if item.id not in combined:
                        combined[item.id] = item

                display_list = list(combined.values())
                display_list.sort(key=lambda x: x.added_at or datetime.min, reverse=True)

                print(Fore.WHITE + f"\nНайдено {len(display_list)} элементов:")
                for i, item in enumerate(display_list, 1):
                    is_fav = any(f.id == item.id for f in favorites)
                    fav_mark = f"{Fore.YELLOW}[★]{Fore.WHITE}" if is_fav else "   "
                    add_date = item.added_at.strftime('%Y-%m-%d %H:%M') if item.added_at else "Неизвестно"
                    print(f"{Fore.YELLOW}{i:2}.{fav_mark} {item.title} ({item.platform})")
                    print(f"      Добавлено: {add_date}")

                print(f"\n{Fore.YELLOW}Введите номер для деталей, 'f' для фильтра, 0 для выхода")
                choice = input(Fore.YELLOW + "Выбор: ").lower()

                if choice == '0':
                    break
                elif choice == 'f':
                    print(f"{Fore.YELLOW}1. Только избранное  2. Только недавние  3. Все")
                    f_choice = input("Фильтр: ")
                    if f_choice == '1':
                        display_list = favorites
                    elif f_choice == '2':
                        display_list = recent
                    continue
                elif choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(display_list):
                        self.view_content_details(display_list[idx].id)
                    else:
                        print(Fore.RED + "Неверный номер.")
                else:
                    print(Fore.RED + "Неверный ввод.")

        except Exception as e:
            print(Fore.RED + f"Ошибка при просмотре сохраненного контента: {e}")

    def view_all_content_from_db(self) -> None:
            """Просмотр всех статей из базы данных с пагинацией и фильтрацией."""
            print(Fore.CYAN + "\n" + "═"*40)
            print(Fore.CYAN + "ВСЕ СТАТЬИ ИЗ БАЗЫ ДАННЫХ")
            print(Fore.CYAN + "─"*40)

            page_size = 20
            current_page = 0
            platform_filter = None
            sort_by = 'added_at'  # Options: 'added_at', 'published_at', 'title'

            try:
                while True:
                    # Build query with filters
                    query = self.session.query(ContentItem)

                    if platform_filter:
                        query = query.filter(ContentItem.platform == platform_filter)

                    # Apply sorting
                    if sort_by == 'added_at':
                        query = query.order_by(ContentItem.added_at.desc())
                    elif sort_by == 'published_at':
                        query = query.order_by(ContentItem.published_at.desc())
                    elif sort_by == 'title':
                        query = query.order_by(ContentItem.title)

                    # Get total count for pagination
                    total_count = query.count()

                    if total_count == 0:
                        print(Fore.YELLOW + "Статьи не найдены в базе данных.")
                        return

                    # Calculate total pages
                    total_pages = (total_count + page_size - 1) // page_size

                    # Ensure current_page is within bounds
                    if current_page >= total_pages:
                        current_page = total_pages - 1
                    if current_page < 0:
                        current_page = 0

                    # Get items for current page
                    items = query.offset(current_page * page_size).limit(page_size).all()

                    # Display header with pagination info
                    print(Fore.WHITE + f"\nСтраница {current_page + 1} из {total_pages} | Всего статей: {total_count}")
                    if platform_filter:
                        print(Fore.CYAN + f"Фильтр: {platform_filter}")
                    print(Fore.CYAN + f"Сортировка: {sort_by}")
                    print(Fore.CYAN + "─"*40)

                    # Display items
                    for i, item in enumerate(items, 1):
                        pub_date = item.published_at.strftime('%Y-%m-%d %H:%M') if item.published_at else "Неизвестно"
                        add_date = item.added_at.strftime('%Y-%m-%d %H:%M') if item.added_at else "Неизвестно"
                        print(f"{Fore.YELLOW}{i:2}.{Fore.WHITE} {item.title} [{Fore.CYAN}{item.platform}{Fore.WHITE}]")
                        print(f"      Опубликовано: {pub_date} | Добавлено: {add_date}")

                    # Navigation options
                    print(Fore.CYAN + "\n─"*40)
                    print(Fore.YELLOW + "n - следующая страница | p - предыдущая | f - фильтр | s - сортировка")
                    print(Fore.YELLOW + "номер - просмотр деталей | 0 - выход")

                    choice = input(Fore.YELLOW + "Выбор: ").lower().strip()

                    if choice == '0':
                        break
                    elif choice == 'n':
                        if current_page < total_pages - 1:
                            current_page += 1
                        else:
                            print(Fore.RED + "Вы уже на последней странице.")
                    elif choice == 'p':
                        if current_page > 0:
                            current_page -= 1
                        else:
                            print(Fore.RED + "Вы уже на первой странице.")
                    elif choice == 'f':
                        # Filter submenu
                        print(Fore.CYAN + "\nВыберите платформу:")
                        print(f"{Fore.YELLOW}1.{Fore.WHITE} YouTube")
                        print(f"{Fore.YELLOW}2.{Fore.WHITE} Habr")
                        print(f"{Fore.YELLOW}3.{Fore.WHITE} Coursera")
                        print(f"{Fore.YELLOW}4.{Fore.WHITE} Все (без фильтра)")
                        f_choice = input(Fore.YELLOW + "Выбор: ").strip()

                        if f_choice == '1':
                            platform_filter = 'youtube'
                        elif f_choice == '2':
                            platform_filter = 'habr'
                        elif f_choice == '3':
                            platform_filter = 'coursera'
                        elif f_choice == '4':
                            platform_filter = None
                        else:
                            print(Fore.RED + "Неверный выбор, фильтр не изменен.")
                            continue

                        current_page = 0  # Reset to first page when filter changes
                        print(Fore.GREEN + f"Фильтр применен: {platform_filter or 'все платформы'}")
                    elif choice == 's':
                        # Sort submenu
                        print(Fore.CYAN + "\nВыберите сортировку:")
                        print(f"{Fore.YELLOW}1.{Fore.WHITE} По дате добавления (новые первыми)")
                        print(f"{Fore.YELLOW}2.{Fore.WHITE} По дате публикации (новые первыми)")
                        print(f"{Fore.YELLOW}3.{Fore.WHITE} По названию (А-Я)")
                        s_choice = input(Fore.YELLOW + "Выбор: ").strip()

                        if s_choice == '1':
                            sort_by = 'added_at'
                        elif s_choice == '2':
                            sort_by = 'published_at'
                        elif s_choice == '3':
                            sort_by = 'title'
                        else:
                            print(Fore.RED + "Неверный выбор, сортировка не изменена.")
                            continue

                        current_page = 0  # Reset to first page when sort changes
                        print(Fore.GREEN + f"Сортировка применена: {sort_by}")
                    elif choice.isdigit():
                        idx = int(choice) - 1
                        if 0 <= idx < len(items):
                            self.view_content_details(items[idx].id)
                        else:
                            print(Fore.RED + "Неверный номер.")
                    else:
                        print(Fore.RED + "Неверный ввод.")

            except Exception as e:
                print(Fore.RED + f"Ошибка при просмотре статей из БД: {e}")

    def get_recommendations_interactive(self) -> None:
        """Интерактивное меню для получения персонализированных рекомендаций."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "ПОЛУЧЕНИЕ РЕКОМЕНДАЦИЙ")
        print(Fore.CYAN + "─"*40)

        # Ensure we have a current user
        if not self.current_user_id:
            users = self.session.query(User).all()
            if users:
                print(Fore.CYAN + "\nВыберите пользователя:")
                for u in users:
                    print(f"ID: {u.id} | {u.username}")
                uid = input(Fore.YELLOW + "Введите ID или нажмите Enter для отмены: ")
                if uid.isdigit():
                    self.current_user_id = int(uid)
                else:
                    print(Fore.YELLOW + "Отменено.")
                    return
        
        if not self.current_user_id:
            print(Fore.RED + "Пользователь не выбран.")
            return

        try:
            user = self.session.query(User).get(self.current_user_id)
            if not user:
                print(Fore.RED + "Пользователь не найден.")
                return

            max_recs_input = input(Fore.YELLOW + "Максимум рекомендаций (по умолчанию 5): ")
            max_recs = int(max_recs_input) if max_recs_input.isdigit() else 5

            recs = self.recommender.get_recommendations(self.current_user_id, max_recs)

            if not recs:
                print(Fore.YELLOW + "Рекомендации не найдены. Попробуйте добавить больше интересов или завершить контент.")
                return

            print(Fore.GREEN + f"\nТоп {len(recs)} рекомендаций для {user.username}:")
            for i, item in enumerate(recs, 1):
                print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")
                print(f"   Платформа: {Fore.CYAN}{item.platform}{Fore.WHITE} | Сложность: {Fore.CYAN}{item.difficulty}")
                print(f"   URL: {Fore.BLUE}{item.url}")
                print()

            mark_choice = input(Fore.YELLOW + "Введите номер элемента для отметки как завершенного (или 0 для пропуска): ")
            if mark_choice.isdigit():
                item_idx = int(mark_choice)
                if 0 < item_idx <= len(recs):
                    item = recs[item_idx-1]
                    rating = input(Fore.YELLOW + "Оценка (1-5, по умолчанию 5): ")
                    rating = int(rating) if rating.isdigit() else 5
                    notes = input(Fore.YELLOW + "Заметки (опционально): ")

                    progress = UserProgress(user_id=self.current_user_id, content_id=item.id)
                    progress.mark_completed(rating=rating, notes=notes)
                    
                    fav_q = input(Fore.YELLOW + "Добавить в избранное? (y/n): ").lower()
                    if fav_q == 'y':
                        fav = FavoriteContent(user_id=self.current_user_id, content_id=item.id)
                        self.session.add(fav)
                    
                    self.session.add(progress)
                    self.session.commit()
                    print(Fore.GREEN + "Элемент отмечен как завершенный!")

        except ValueError:
            print(Fore.RED + "Неверный ввод.")
        except Exception as e:
            print(Fore.RED + f"Ошибка: {e}")

    def configure_user_settings(self) -> None:
        """Комплексное меню настроек пользователя и приложения."""
        while True:
            print(Fore.CYAN + "\n" + "═"*40)
            print(Fore.CYAN + "НАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ")
            print(Fore.CYAN + "─"*40)

            if self.current_user_id:
                user = self.session.query(User).get(self.current_user_id)
                if user:
                    print(f"{Fore.GREEN}Текущий пользователь: {user.username} (ID: {user.id})")

            print(f"{Fore.YELLOW}0.{Fore.WHITE} Добавить нового пользователя")
            print(f"{Fore.YELLOW}1.{Fore.WHITE} Выбор пользователя")
            print(f"{Fore.YELLOW}2.{Fore.WHITE} Настройки email-рассылки")
            print(f"{Fore.YELLOW}3.{Fore.WHITE} Управление интересами и темами")
            print(f"{Fore.YELLOW}4.{Fore.WHITE} Настройки алгоритма рекомендаций")
            print(f"{Fore.YELLOW}5.{Fore.WHITE} Тест email-рассылки")
            print(f"{Fore.YELLOW}6.{Fore.WHITE} Вернуться в главное меню")

            try:
                choice = input(Fore.YELLOW + "\nВыбор: ")
                if choice == "6":
                    break

                if choice == "0":
                    self.add_new_user_interactive()
                    continue

                if choice == "1":
                    users = self.session.query(User).all()
                    print(Fore.CYAN + "\nСписок пользователей:")
                    for u in users:
                        current_mark = " (ТЕКУЩИЙ)" if u.id == self.current_user_id else ""
                        print(f"ID: {u.id} | {u.username} | {u.email}{current_mark}")

                    uid = input(Fore.YELLOW + "Введите ID для выбора или Enter для отмены: ")
                    if uid.isdigit():
                        user = self.session.query(User).get(int(uid))
                        if user:
                            self.current_user_id = user.id

                            # Save selection to file
                            try:
                                self._save_current_user_id(user.id)
                            except Exception as e:
                                logger.warning(f"Failed to save user selection: {e}")
                            print(Fore.GREEN + f"Выбран пользователь: {user.username}")
                        else:
                            print(Fore.RED + "Пользователь не найден.")

                elif choice == "2":
                    self.configure_email_settings()

                elif choice == "3":
                    self.manage_interests_enhanced()

                elif choice == "4":
                    if not self.current_user_id:
                        print(Fore.RED + "Сначала выберите пользователя.")
                        continue
                    weights = self.recommender.get_user_preference_weights(self.current_user_id)
                    print(Fore.CYAN + "\nТекущие веса алгоритма:")
                    for k, v in weights.items():
                        print(f"  {k}: {v}")
                    print(Fore.YELLOW + "Веса рассчитываются автоматически на основе вашей активности.")

                elif choice == "5":
                    self.send_test_digest()

            except Exception as e:
                print(Fore.RED + f"Ошибка: {e}")

    def configure_email_settings(self) -> None:
        """Настройка email-рассылки для текущего пользователя."""
        if not self.current_user_id:
            print(Fore.RED + "Пользователь не выбран.")
            return

        while True:
            user = self.session.query(User).get(self.current_user_id)
            settings_obj = user.settings
            if not settings_obj:
                settings_obj = UserSettings(user_id=user.id, email_digest=user.email)
                self.session.add(settings_obj)
                self.session.commit()

            print(Fore.CYAN + "\nНАСТРОЙКИ EMAIL")
            print(f"1. Email: {settings_obj.email_digest}")
            print(f"2. Час рассылки: {settings_obj.digest_hour}:00")
            print(f"3. Статус: {'Включена' if settings_obj.digest_enabled else 'Выключена'}")
            print(f"4. Отправлять пропущенные: {'Да' if settings_obj.missed_digest_send else 'Нет'}")
            print(f"5. Автоматическое обновление контента: {'Включено' if settings_obj.auto_update_content else 'Выключено'}")
            print("6. Протестировать (отправить сейчас)")
            print("7. Назад")

            choice = input(Fore.YELLOW + "Выбор: ")
            if choice == "7":
                break

            try:
                if choice == "1":
                    email = input("Новый email: ")
                    if "@" in email:
                        settings_obj.email_digest = email
                        print(Fore.GREEN + "Email обновлен.")
                elif choice == "2":
                    hour = int(input("Час (0-23): "))
                    if 0 <= hour <= 23:
                        settings_obj.digest_hour = hour
                        print(Fore.GREEN + f"Час рассылки установлен на {hour}:00.")
                elif choice == "3":
                    settings_obj.digest_enabled = not settings_obj.digest_enabled
                    status = "включена" if settings_obj.digest_enabled else "выключена"
                    print(Fore.GREEN + f"Рассылка {status}.")
                elif choice == "4":
                    settings_obj.missed_digest_send = not settings_obj.missed_digest_send
                    status = "включена" if settings_obj.missed_digest_send else "выключена"
                    print(Fore.GREEN + f"Отправка пропущенных рассылок {status}.")
                elif choice == "5":
                    settings_obj.auto_update_content = not settings_obj.auto_update_content
                    status = "включено" if settings_obj.auto_update_content else "выключено"
                    print(Fore.GREEN + f"Автоматическое обновление контента {status}.")
                elif choice == "6":
                    self.send_test_digest()
                
                self.session.commit()
            except ValueError:
                print(Fore.RED + "Неверный ввод.")
            except Exception as e:
                print(Fore.RED + f"Ошибка: {e}")

    def manage_interests_enhanced(self) -> None:
        """Расширенное управление интересами с предложениями на основе избранного контента."""
        if not self.current_user_id:
            print(Fore.RED + "Пользователь не выбран.")
            return

        while True:
            user = self.session.query(User).get(self.current_user_id)
            print(Fore.CYAN + f"\nИНТЕРЕСЫ ПОЛЬЗОВАТЕЛЯ {user.username.upper()}")
            
            interests = user.interests
            if interests:
                for interest in interests:
                    print(f"- {Fore.WHITE}{interest.tag_name} {Fore.CYAN}(Приоритет: {interest.priority})")
            else:
                print(Fore.YELLOW + "Интересы не настроены.")

            suggestions = self.recommender.get_interest_suggestions(self.current_user_id)
            if suggestions:
                print(Fore.GREEN + "\nПредложенные темы на основе вашего избранного:")
                for i, s in enumerate(suggestions[:5], 1):
                    print(f"  {i}. {s}")

            print(f"\n{Fore.YELLOW}1. Добавить из предложенных  2. Добавить вручную")
            print(f"{Fore.YELLOW}3. Удалить интерес           4. Изменить приоритет")
            print(f"{Fore.YELLOW}5. Получить рекомендации     6. Назад")
            
            choice = input(Fore.YELLOW + "Выбор: ")
            if choice == "6":
                break

            try:
                if choice == "1" and suggestions:
                    idx = int(input("Номер предложения: ")) - 1
                    if 0 <= idx < len(suggestions):
                        new_int = UserInterest(user_id=user.id, tag_name=suggestions[idx])
                        self.session.add(new_int)
                        self.session.commit()
                        print(Fore.GREEN + "Интерес добавлен.")
                elif choice == "2":
                    tag = input("Название тега: ")
                    priority = int(input("Приоритет (1-10): ") or "5")
                    self.session.add(UserInterest(user_id=user.id, tag_name=tag, priority=priority))
                    self.session.commit()
                    print(Fore.GREEN + "Интерес добавлен.")
                elif choice == "3":
                    tag = input("Тег для удаления: ")
                    interest = self.session.query(UserInterest).filter_by(user_id=user.id, tag_name=tag).first()
                    if interest:
                        self.session.delete(interest)
                        self.session.commit()
                        print(Fore.GREEN + "Интерес удален.")
                    else:
                        print(Fore.RED + "Интерес не найден.")
                elif choice == "4":
                    tag = input("Тег: ")
                    interest = self.session.query(UserInterest).filter_by(user_id=user.id, tag_name=tag).first()
                    if interest:
                        interest.priority = int(input("Новый приоритет: "))
                        self.session.commit()
                        print(Fore.GREEN + "Приоритет обновлен.")
                    else:
                        print(Fore.RED + "Интерес не найден.")
                elif choice == "5":
                    self.get_recommendations_interactive()
            except ValueError:
                print(Fore.RED + "Неверный ввод.")
            except Exception as e:
                print(Fore.RED + f"Ошибка: {e}")

    def send_test_digest(self) -> None:
        """Send test digest email to current user with fallback logic."""
        if not self.current_user_id:
            print(Fore.RED + "Пользователь не выбран.")
            return

        print(Fore.WHITE + "Генерация и отправка тестовой подборки...")
        items = self.aggregator.get_daily_digest(self.current_user_id, max_items=15)

        if not items:
            print(Fore.YELLOW + "По вашим интересам контент не найден, показываем свежие материалы")
            items = self.aggregator.get_fallback_content(max_items=15)

        if not items:
            print(Fore.RED + "Контент не найден даже в общем списке.")
            return

        success = self.aggregator.send_email_digest(self.current_user_id, items)
        if success:
            print(Fore.GREEN + "Email успешно отправлен.")
        else:
            print(Fore.RED + "Ошибка при отправке Email. Проверьте настройки SMTP.")

    def show_statistics(self) -> None:
        """Показать статистику использования."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "СТАТИСТИКА")
        print(Fore.CYAN + "─"*40)

        # Статистика контента
        total_items = self.session.query(ContentItem).count()
        youtube_items = self.session.query(ContentItem).filter_by(platform="youtube").count()
        habr_items = self.session.query(ContentItem).filter_by(platform="habr").count()
        coursera_items = self.session.query(ContentItem).filter_by(platform="coursera").count()

        print(Fore.CYAN + "\nСтатистика контента:")
        print(f"  {Fore.WHITE}Всего элементов: {Fore.GREEN}{total_items}")
        print(f"  {Fore.WHITE}YouTube: {Fore.GREEN}{youtube_items}")
        print(f"  {Fore.WHITE}Habr: {Fore.GREEN}{habr_items}")
        print(f"  {Fore.WHITE}Coursera: {Fore.GREEN}{coursera_items}")

        # Статистика пользователей
        total_users = self.session.query(User).count()
        active_users = self.session.query(UserProgress).distinct(UserProgress.user_id).count()

        print(Fore.CYAN + "\nСтатистика пользователей:")
        print(f"  {Fore.WHITE}Всего пользователей: {Fore.GREEN}{total_users}")
        print(f"  {Fore.WHITE}Активные пользователи (с прогрессом): {Fore.GREEN}{active_users}")

        # Статистика завершения
        total_completed = self.session.query(UserProgress).filter_by(completed=True).count()
        avg_rating = self.session.query(func.avg(UserProgress.rating)).filter(UserProgress.rating.isnot(None)).scalar()

        print(Fore.CYAN + "\nСтатистика завершения:")
        print(f"  {Fore.WHITE}Всего завершенных элементов: {Fore.GREEN}{total_completed}")
        if avg_rating:
            print(f"  {Fore.WHITE}Средняя оценка: {Fore.GREEN}{avg_rating:.1f}/5")

        # Статистика тегов
        popular_tags = self.session.query(Tag.name).join(ContentItem.tags).group_by(Tag.name).order_by(
            func.count(ContentItem.id).desc()
        ).limit(5).all()

        if popular_tags:
            print(Fore.CYAN + "\nСамые популярные теги:")
            for tag in popular_tags:
                count = self.session.query(ContentItem).join(ContentItem.tags).filter(Tag.name == tag[0]).count()
                print(f"  {Fore.WHITE}{tag[0]}: {Fore.GREEN}{count} элементов")

        # Состояние системы
        db_path = settings.database_url.replace("sqlite:///", "")
        if Path(db_path).exists():
            size_mb = Path(db_path).stat().st_size / (1024 * 1024)
            print(Fore.CYAN + "\nСостояние системы:")
            print(f"  {Fore.WHITE}Размер базы данных: {Fore.GREEN}{size_mb:.2f} МБ")
            print(f"  {Fore.WHITE}Последнее обновление: {Fore.GREEN}{datetime.now().strftime('%Y-%m-%d %H:%M')}")