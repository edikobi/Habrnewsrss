"""Интерактивное меню для системы агрегации контента."""
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
    """Интерактивное меню для системы агрегации контента с управлением источниками и поиском."""

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
        """Обеспечить наличие демо-пользователя и контента."""
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
                print(Fore.GREEN + f"✓ Создан демо-пользователь с ID: {user.id}")

            content_count = self.session.query(ContentItem).count()
            if content_count == 0 and self.sources["habr"]["enabled"]:
                items = self.sources["habr"]["instance"].fetch_content(["python"], 5)
                self.aggregator.save_content_items(items)
                print(Fore.GREEN + f"✓ Добавлено {len(items)} демо-элементов контента из Habr")
        except Exception as e:
            print(Fore.YELLOW + f"⚠ Создание демо-данных пропущено: {e}")

    def run(self) -> None:
        """Основной интерактивный цикл."""
        init(autoreset=True)
        self._ensure_demo_data()

        print(Fore.CYAN + "\n" + "="*50)
        print(Fore.CYAN + "АГРЕГАТОР ОБРАЗОВАТЕЛЬНОГО КОНТЕНТА - ИНТЕРАКТИВНЫЙ РЕЖИМ")
        print(Fore.CYAN + "="*50)

        try:
            while True:
                choice = self.show_main_menu()
                if choice == 7:
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
        print(f"{Fore.YELLOW}1.{Fore.WHITE} Просмотр контента и новостей")
        print(f"{Fore.YELLOW}2.{Fore.WHITE} Управление источниками")
        print(f"{Fore.YELLOW}3.{Fore.WHITE} Поиск контента")
        print(f"{Fore.YELLOW}4.{Fore.WHITE} Получить рекомендации")
        print(f"{Fore.YELLOW}5.{Fore.WHITE} Настройки")
        print(f"{Fore.YELLOW}6.{Fore.WHITE} Просмотр статистики")
        print(f"{Fore.YELLOW}7.{Fore.WHITE} Выход")
        print(Fore.CYAN + "─"*40)

        while True:
            try:
                choice = int(input(Fore.YELLOW + "\nВведите ваш выбор (1-7): "))
                if 1 <= choice <= 7:
                    break
                print(Fore.RED + "Пожалуйста, введите число от 1 до 7.")
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
            self.configure_settings()
        elif choice == 6:
            self.show_statistics()

        return choice

    def view_content(self) -> None:
        """Просмотр и поиск контента."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "ПРОСМОТР КОНТЕНТА")
        print(Fore.CYAN + "─"*40)

        user_id_input = input(Fore.YELLOW + "Введите ID пользователя для персонализированной подборки (или нажмите Enter для всего контента): ")

        if user_id_input.strip():
            try:
                user_id = int(user_id_input)
                user = self.session.query(User).get(user_id)
                if not user:
                    print(Fore.RED + f"Пользователь с ID {user_id} не найден.")
                    return

                print(Fore.WHITE + f"\nГенерация ежедневной подборки для пользователя: {Fore.GREEN}{user.username}")
                digest = self.aggregator.get_daily_digest(user_id, max_items=10)

                if not digest:
                    print(Fore.YELLOW + "Контент по вашим интересам не найден.")
                    return

                print(Fore.GREEN + f"\nНайдено {len(digest)} элементов:")
                for i, item in enumerate(digest, 1):
                    print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")
                    print(f"   Платформа: {Fore.CYAN}{item.platform}{Fore.WHITE} | Сложность: {Fore.CYAN}{item.difficulty}")
                    print(f"   URL: {Fore.BLUE}{item.url}")
                    print()

                mark_choice = input(Fore.YELLOW + "Введите номер элемента для отметки как завершенного (или 0 для пропуска): ")
                if mark_choice.isdigit():
                    item_idx = int(mark_choice)
                    if 0 < item_idx <= len(digest):
                        item = digest[item_idx-1]
                        rating = input(Fore.YELLOW + "Оценка (1-5, по умолчанию 5): ")
                        rating = int(rating) if rating.isdigit() else 5
                        notes = input(Fore.YELLOW + "Заметки (опционально): ")

                        progress = UserProgress(user_id=user_id, content_id=item.id)
                        progress.mark_completed(rating=rating, notes=notes)
                        self.session.add(progress)
                        self.session.commit()
                        print(Fore.GREEN + "Элемент отмечен как завершенный!")

            except ValueError:
                print(Fore.RED + "Неверный ID пользователя.")
        else:
            print(Fore.WHITE + "\nНедавний контент из всех источников:")
            items = self.session.query(ContentItem).order_by(ContentItem.published_at.desc()).limit(20).all()

            for i, item in enumerate(items, 1):
                print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")
                print(f"   Платформа: {Fore.CYAN}{item.platform}{Fore.WHITE} | Опубликовано: {item.published_at}")
                print(f"   URL: {Fore.BLUE}{item.url}")
                print()

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
        """Интерактивный поиск по всем источникам."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "ПОИСК КОНТЕНТА")
        print(Fore.CYAN + "─"*40)

        keywords_input = input(Fore.YELLOW + "Введите ключевые слова для поиска (через запятую): ")
        keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]

        if not keywords:
            print(Fore.RED + "Ключевые слова не указаны.")
            return

        print(Fore.WHITE + "\nДоступные источники: youtube, habr, coursera, all")
        source_filter = input(Fore.YELLOW + "Фильтр по источнику (по умолчанию: all): ").lower() or "all"

        print(Fore.WHITE + "\nУровни сложности: beginner, intermediate, advanced, all")
        difficulty_filter = input(Fore.YELLOW + "Фильтр по сложности (по умолчанию: all): ").lower() or "all"

        try:
            max_results = int(input(Fore.YELLOW + "Максимальное количество результатов (по умолчанию: 50): ") or "50")
        except ValueError:
            max_results = 50

        print(Fore.WHITE + f"\nПоиск по: {Fore.GREEN}{', '.join(keywords)}")
        if source_filter != "all":
            print(Fore.WHITE + f"Фильтр источника: {Fore.CYAN}{source_filter}")
        if difficulty_filter != "all":
            print(Fore.WHITE + f"Фильтр сложности: {Fore.CYAN}{difficulty_filter}")

        results = self.aggregator.search_content(keywords, source_filter, difficulty_filter, max_results)

        print(Fore.GREEN + f"\nНайдено {len(results)} результатов:")
        for i, item in enumerate(results, 1):
            print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")
            print(f"   Платформа: {Fore.CYAN}{item.platform}{Fore.WHITE} | Сложность: {Fore.CYAN}{item.difficulty}")
            print(f"   Опубликовано: {item.published_at}")
            print(f"   URL: {Fore.BLUE}{item.url}")
            if item.description and len(item.description) > 100:
                print(f"   Описание: {Fore.WHITE}{item.description[:100]}...")
            print()

    def get_recommendations_interactive(self) -> None:
        """Интерактивное меню для получения персонализированных рекомендаций."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "ПОЛУЧЕНИЕ РЕКОМЕНДАЦИЙ")
        print(Fore.CYAN + "─"*40)

        try:
            user_id_input = input(Fore.YELLOW + "Введите ID пользователя: ")
            user_id = int(user_id_input)
            user = self.session.query(User).get(user_id)
            if not user:
                print(Fore.RED + "Пользователь не найден.")
                return

            max_recs_input = input(Fore.YELLOW + "Максимум рекомендаций (по умолчанию 5): ")
            max_recs = int(max_recs_input) if max_recs_input.isdigit() else 5

            recs = self.recommender.get_recommendations(user_id, max_recs)

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

                    progress = UserProgress(user_id=user_id, content_id=item.id)
                    progress.mark_completed(rating=rating, notes=notes)
                    self.session.add(progress)
                    self.session.commit()
                    print(Fore.GREEN + "Элемент отмечен как завершенный!")

        except ValueError:
            print(Fore.RED + "Неверный ввод.")
        except Exception as e:
            print(Fore.RED + f"Ошибка: {e}")

    def configure_settings(self) -> None:
        """Обновить настройки приложения."""
        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.CYAN + "НАСТРОЙКИ")
        print(Fore.CYAN + "─"*40)

        print(Fore.WHITE + "\nТекущие настройки:")
        print(f"{Fore.YELLOW}1.{Fore.WHITE} Час ежедневной подборки: {Fore.GREEN}{settings.daily_digest_hour}:00")
        print(f"{Fore.YELLOW}2.{Fore.WHITE} Интервал обновления контента: {Fore.GREEN}{settings.content_update_interval_hours} часов")
        print(f"{Fore.YELLOW}3.{Fore.WHITE} Максимум рекомендаций в день: {Fore.GREEN}{settings.max_recommendations_per_day}")
        print(f"{Fore.YELLOW}4.{Fore.WHITE} Расположение базы данных: {Fore.GREEN}{settings.database_url}")
        print(f"{Fore.YELLOW}5.{Fore.WHITE} Размер пагинации в интерактивном режиме: {Fore.GREEN}{getattr(settings, 'interactive_pagination_size', 10)}")
        print(f"{Fore.YELLOW}6.{Fore.WHITE} Показывать превью в интерактивном режиме: {Fore.GREEN}{getattr(settings, 'interactive_show_previews', True)}")

        print(Fore.YELLOW + "\nВведите номер настройки для изменения (или 0 для возврата): ")
        try:
            choice = int(input(Fore.YELLOW + "Выбор: "))
            if choice == 0:
                return

            if choice == 1:
                new_hour = int(input(Fore.YELLOW + "Новый час ежедневной подборки (0-23): "))
                if 0 <= new_hour <= 23:
                    print(Fore.GREEN + f"Час ежедневной подборки будет установлен в {new_hour}:00")
                else:
                    print(Fore.RED + "Час должен быть от 0 до 23.")

            elif choice == 2:
                new_interval = int(input(Fore.YELLOW + "Новый интервал обновления (часы, 1-168): "))
                if 1 <= new_interval <= 168:
                    print(Fore.GREEN + f"Интервал обновления будет установлен в {new_interval} часов")
                else:
                    print(Fore.RED + "Интервал должен быть от 1 до 168 часов (1 неделя).")

            elif choice == 3:
                new_max = int(input(Fore.YELLOW + "Новый максимум рекомендаций (1-50): "))
                if 1 <= new_max <= 50:
                    print(Fore.GREEN + f"Максимум рекомендаций будет установлен в {new_max}")
                else:
                    print(Fore.RED + "Должно быть от 1 до 50.")

            elif choice == 4:
                new_db = input(Fore.YELLOW + "Новый путь к базе данных (например, sqlite:///new.db): ")
                if new_db.startswith("sqlite:///"):
                    print(Fore.GREEN + f"Расположение базы данных будет установлено в {new_db}")
                else:
                    print(Fore.RED + "URL базы данных должен начинаться с 'sqlite:///'")

            elif choice == 5:
                new_size = int(input(Fore.YELLOW + "Новый размер пагинации (5-50): "))
                if 5 <= new_size <= 50:
                    print(Fore.GREEN + f"Размер пагинации будет установлен в {new_size}")
                else:
                    print(Fore.RED + "Должно быть от 5 до 50.")

            elif choice == 6:
                new_setting = input(Fore.YELLOW + "Показывать превью? (yes/no): ").lower()
                if new_setting in ["yes", "no"]:
                    value = new_setting == "yes"
                    print(Fore.GREEN + f"Показ превью будет установлен в {value}")
                else:
                    print(Fore.RED + "Пожалуйста, введите 'yes' или 'no'.")

            else:
                print(Fore.RED + "Неверный выбор.")

            print(Fore.YELLOW + "\nПримечание: для применения некоторых настроек требуется перезапуск приложения.")

        except ValueError:
            print(Fore.RED + "Пожалуйста, введите корректное число.")

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
            print(f"  {Fore.WHITE}Последнее обновление: {Fore.GREEN}{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")