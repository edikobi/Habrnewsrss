from app.database import (
    get_db_session, User, ContentItem, UserInterest, 
    UserProgress, Tag, SessionLocal, UserSettings, 
    FavoriteContent, SearchQuery
)
from app.database import (
    get_db_session, User, ContentItem, UserInterest, 
    UserProgress, Tag, SessionLocal, UserSettings, FavoriteContent
)
from app.database import (
    get_db_session, User, ContentItem, UserInterest, 
)
from app.database import SearchQuery
from app.database import UserSettings, FavoriteContent
import datetime

from app.database import (
    get_db_session, User, ContentItem, UserInterest,
    UserProgress, Tag, SessionLocal, UserSettings,
    FavoriteContent, SearchQuery
)

import os
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from sqlalchemy import func
import click
from colorama import init, Fore, Back, Style
from docx import Document

from app.services.aggregator import ContentAggregator, update_all_content
from app.services.recommender import ContentRecommender
from app.services.email_sender import EmailSender
from app.config import settings
from app.sources.youtube import YouTubeSource
from app.sources.habr import HabrSource
from app.sources.coursera import CourseraSource

logger = logging.getLogger(__name__)

class InteractiveMenu:
    """Интерактивное меню для системы агрегации контента."""

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
        self.current_user_id: Optional[int] = self._load_current_user_id()

    def _load_current_user_id(self) -> Optional[int]:
        try:
            path = Path.cwd() / '.current_user'
            if path.exists():
                content = path.read_text().strip()
                return int(content) if content.isdigit() else None
        except Exception:
            return None

    def _save_current_user_id(self, user_id: Optional[int]) -> None:
        path = Path.cwd() / '.current_user'
        if user_id:
            path.write_text(str(user_id))
        elif path.exists():
            path.unlink()

    def run(self) -> None:
        init(autoreset=True)
        print(Fore.CYAN + "АГРЕГАТОР ОБРАЗОВАТЕЛЬНОГО КОНТЕНТА")
        try:
            while True:
                choice = self.show_main_menu()
                if choice == 8: break
        finally:
            self.session.close()

    def show_main_menu(self) -> int:
        print(Fore.CYAN + "\n" + "═"*40)
        if self.current_user_id:
            user = self.session.query(User).get(self.current_user_id)
            if user: print(f"{Fore.GREEN}Пользователь: {user.username}")

        menu = ["Просмотр контента", "Управление источниками", "Поиск контента", 
                "Рекомендации", "Настройки", "Статистика", "Все статьи БД", "Выход"]
        for i, item in enumerate(menu, 1):
            print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item}")

        choice = input(Fore.YELLOW + "\nВыбор: ")
        if not choice.isdigit(): return 0
        c = int(choice)
        if c == 1: self.view_content()
        elif c == 2: self.manage_sources()
        elif c == 3: self.search_content()
        elif c == 4: self.show_recommendations()
        elif c == 5: self.configure_user_settings()
        elif c == 6: self.show_statistics()
        elif c == 7: self.browse_all_articles()
        return c

    def view_content(self) -> None:
        """Просмотр персонализированного контента с возможностью выбора статьи."""
        if not self.current_user_id:
            print(Fore.RED + "Сначала выберите пользователя в настройках.")
            return

        digest = self.aggregator.get_daily_digest(self.current_user_id)
        if not digest:
            print(Fore.YELLOW + "Нет доступного контента.")
            return

        print(Fore.CYAN + "\nПЕРСОНАЛИЗИРОВАННЫЙ КОНТЕНТ:")
        for i, item in enumerate(digest, 1):
            print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title} ({item.platform})")
        print(f"{Fore.YELLOW}0.{Fore.WHITE} Назад")

        choice = input(Fore.YELLOW + "\nВыберите статью для просмотра (номер): ").strip()
        if choice == "0" or not choice:
            return
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(digest):
                self._display_article(digest[idx])

    def search_content(self) -> None:
        """Поиск контента с возможностью выбора и просмотра статьи."""
        query = input(Fore.YELLOW + "Поиск: ").strip()
        if not query:
            return

        # Track search interest if user is logged in
        if self.current_user_id:
            try:
                self.aggregator.track_search_query(self.current_user_id, query)
            except Exception as e:
                print(f"{Fore.RED}Ошибка отслеживания интересов: {e}")

        results = self.aggregator.search_content([query])
        if not results:
            print(Fore.YELLOW + "Ничего не найдено.")
            return

        print(Fore.CYAN + f"\nНАЙДЕНО {len(results)} РЕЗУЛЬТАТОВ:")
        for i, item in enumerate(results, 1):
            platform_info = f" ({item.platform})" if item.platform else ""
            print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}{platform_info}")
        print(f"{Fore.YELLOW}0.{Fore.WHITE} Назад")

        choice = input(Fore.YELLOW + "\nВыберите статью для просмотра (номер): ").strip()
        if choice == "0" or not choice:
            return
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(results):
                self._display_article(results[idx])

    def _display_article(self, item: ContentItem) -> None:
        """Отобразить полную информацию о статье с возможностью экспорта."""
        print(Fore.CYAN + "\n" + "═"*60)
        print(Fore.GREEN + f"ЗАГОЛОВОК: {item.title}")
        print(Fore.WHITE + f"Платформа: {item.platform or 'Неизвестно'}")
        print(Fore.WHITE + f"URL: {item.url or 'Нет ссылки'}")

        if item.published_at:
            print(Fore.WHITE + f"Опубликовано: {item.published_at.strftime('%Y-%m-%d %H:%M')}")

        if item.tags:
            tags_str = ", ".join([t.name for t in item.tags[:10]])
            print(Fore.WHITE + f"Теги: {tags_str}")

        print(Fore.CYAN + "\n" + "-"*60)
        print(Fore.WHITE + "ОПИСАНИЕ:")
        print(item.description or "Нет описания")

        if item.full_text:
            print(Fore.CYAN + "\n" + "-"*60)
            print(Fore.WHITE + "ПОЛНЫЙ ТЕКСТ:")
            # Показать первые 2000 символов с возможностью продолжения
            text = item.full_text
            if len(text) > 2000:
                print(text[:2000])
                show_more = input(Fore.YELLOW + "\n[Enter - показать ещё, 0 - выход]: ").strip()
                if show_more == "":
                    print(text[2000:])
            else:
                print(text)
        else:
            print(Fore.YELLOW + "\nПолный текст недоступен.")

        print(Fore.CYAN + "\n" + "═"*60)
        print(f"{Fore.YELLOW}1.{Fore.WHITE} Открыть в браузере")
        print(f"{Fore.YELLOW}2.{Fore.WHITE} Добавить в избранное")
        print(f"{Fore.YELLOW}3.{Fore.WHITE} Отметить как прочитанное")
        print(f"{Fore.YELLOW}0.{Fore.WHITE} Назад")

        action = input(Fore.YELLOW + "\nДействие: ").strip()
        if action == "1" and item.url:
            import webbrowser
            webbrowser.open(item.url)
            print(Fore.GREEN + "✓ Открыто в браузере")
        elif action == "2" and self.current_user_id:
            existing = self.session.query(FavoriteContent).filter_by(
                user_id=self.current_user_id, content_id=item.id
            ).first()
            if not existing:
                fav = FavoriteContent(user_id=self.current_user_id, content_id=item.id)
                self.session.add(fav)
                self.session.commit()
                print(Fore.GREEN + "✓ Добавлено в избранное")
            else:
                print(Fore.YELLOW + "Уже в избранном")
        elif action == "3" and self.current_user_id:
            existing = self.session.query(UserProgress).filter_by(
                user_id=self.current_user_id, content_id=item.id
            ).first()
            if not existing:
                progress = UserProgress(user_id=self.current_user_id, content_id=item.id)
                progress.mark_completed()
                self.session.add(progress)
                self.session.commit()
                print(Fore.GREEN + "✓ Отмечено как прочитанное")
            else:
                existing.mark_completed()
                self.session.commit()
                print(Fore.GREEN + "✓ Отмечено как прочитанное")

    def manage_sources(self) -> None:
        """Управление источниками контента."""
        print(Fore.CYAN + "\nУПРАВЛЕНИЕ ИСТОЧНИКАМИ")
        print(Fore.WHITE + "Текущие источники:")

        for name, info in self.sources.items():
            status = Fore.GREEN + "✓ Включен" if info["enabled"] else Fore.RED + "✗ Выключен"
            print(f"  {Fore.YELLOW}{name}{Fore.WHITE}: {status}")

        print(f"\n{Fore.YELLOW}1.{Fore.WHITE} Переключить YouTube")
        print(f"{Fore.YELLOW}2.{Fore.WHITE} Переключить Habr")
        print(f"{Fore.YELLOW}3.{Fore.WHITE} Переключить Coursera")
        print(f"{Fore.YELLOW}0.{Fore.WHITE} Назад")

        choice = input(Fore.YELLOW + "\nВыбор: ").strip()
        if choice == "1":
            self.sources["youtube"]["enabled"] = not self.sources["youtube"]["enabled"]
            status = "включен" if self.sources["youtube"]["enabled"] else "выключен"
            print(Fore.GREEN + f"✓ YouTube {status}")
        elif choice == "2":
            self.sources["habr"]["enabled"] = not self.sources["habr"]["enabled"]
            status = "включен" if self.sources["habr"]["enabled"] else "выключен"
            print(Fore.GREEN + f"✓ Habr {status}")
        elif choice == "3":
            self.sources["coursera"]["enabled"] = not self.sources["coursera"]["enabled"]
            status = "включен" if self.sources["coursera"]["enabled"] else "выключен"
            print(Fore.GREEN + f"✓ Coursera {status}")

    def show_recommendations(self) -> None:
        """Показать персонализированные рекомендации."""
        if not self.current_user_id:
            print(Fore.RED + "Сначала выберите пользователя в настройках.")
            return

        print(Fore.CYAN + "\nПОЛУЧЕНИЕ РЕКОМЕНДАЦИЙ...")
        recommendations = self.recommender.get_recommendations(self.current_user_id, max_recommendations=10)

        if not recommendations:
            print(Fore.YELLOW + "Нет рекомендаций. Попробуйте добавить интересы или просмотреть контент.")
            return

        print(Fore.CYAN + f"\nРЕКОМЕНДАЦИИ ДЛЯ ВАС ({len(recommendations)}):")
        for i, item in enumerate(recommendations, 1):
            platform_info = f" ({item.platform})" if item.platform else ""
            print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}{platform_info}")
        print(f"{Fore.YELLOW}0.{Fore.WHITE} Назад")

        choice = input(Fore.YELLOW + "\nВыберите статью для просмотра (номер): ").strip()
        if choice == "0" or not choice:
            return
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(recommendations):
                self._display_article(recommendations[idx])

    def show_statistics(self) -> None:
        """Показать статистику пользователя."""
        if not self.current_user_id:
            print(Fore.RED + "Сначала выберите пользователя в настройках.")
            return

        user = self.session.query(User).get(self.current_user_id)
        if not user:
            print(Fore.RED + "Пользователь не найден.")
            return

        print(Fore.CYAN + "\n" + "═"*40)
        print(Fore.GREEN + f"СТАТИСТИКА: {user.username}")
        print(Fore.CYAN + "═"*40)

        # Подсчёт статистики
        total_content = self.session.query(ContentItem).count()
        completed_count = user.completed_content_count()
        total_time = user.total_study_time()
        interests_count = len(user.interests)
        favorites_count = self.session.query(FavoriteContent).filter_by(user_id=user.id).count()

        print(f"{Fore.WHITE}Всего статей в БД: {Fore.YELLOW}{total_content}")
        print(f"{Fore.WHITE}Прочитано статей: {Fore.YELLOW}{completed_count}")
        print(f"{Fore.WHITE}Время обучения: {Fore.YELLOW}{total_time} мин")
        print(f"{Fore.WHITE}Интересов: {Fore.YELLOW}{interests_count}")
        print(f"{Fore.WHITE}В избранном: {Fore.YELLOW}{favorites_count}")

        if user.created_at:
            days_active = (datetime.utcnow() - user.created_at).days
            print(f"{Fore.WHITE}Дней в системе: {Fore.YELLOW}{days_active}")

        print(Fore.CYAN + "═"*40)
        input(Fore.YELLOW + "\nНажмите Enter для продолжения...")

    def browse_all_articles(self) -> None:
        """Просмотр всех статей в базе данных с пагинацией."""
        page = 0
        page_size = 15

        while True:
            total = self.session.query(ContentItem).count()
            if total == 0:
                print(Fore.YELLOW + "База данных пуста.")
                return

            articles = self.session.query(ContentItem).order_by(
                ContentItem.added_at.desc()
            ).offset(page * page_size).limit(page_size).all()

            if not articles:
                print(Fore.YELLOW + "Больше статей нет.")
                page = max(0, page - 1)
                continue

            total_pages = (total + page_size - 1) // page_size
            print(Fore.CYAN + f"\nВСЕ СТАТЬИ В БД (страница {page + 1}/{total_pages}, всего {total}):")

            for i, item in enumerate(articles, 1):
                idx = page * page_size + i
                platform_info = f" ({item.platform})" if item.platform else ""
                title = item.title[:50] + "..." if len(item.title) > 50 else item.title
                print(f"{Fore.YELLOW}{idx}.{Fore.WHITE} {title}{platform_info}")

            print(f"\n{Fore.YELLOW}n{Fore.WHITE} - следующая страница")
            print(f"{Fore.YELLOW}p{Fore.WHITE} - предыдущая страница")
            print(f"{Fore.YELLOW}номер{Fore.WHITE} - открыть статью")
            print(f"{Fore.YELLOW}0{Fore.WHITE} - назад")

            choice = input(Fore.YELLOW + "\nВыбор: ").strip().lower()

            if choice == "0":
                return
            elif choice == "n":
                if (page + 1) * page_size < total:
                    page += 1
            elif choice == "p":
                page = max(0, page - 1)
            elif choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < total:
                    # Получить конкретную статью по индексу
                    article = self.session.query(ContentItem).order_by(
                        ContentItem.added_at.desc()
                    ).offset(idx).first()
                    if article:
                        self._display_article(article)

    def configure_user_settings(self) -> None:
        while True:
            print(Fore.CYAN + "\nНАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ")
            print(f"{Fore.YELLOW}1.{Fore.WHITE} Выбор пользователя\n{Fore.YELLOW}2.{Fore.WHITE} Настройки email\n{Fore.YELLOW}3.{Fore.WHITE} Управление интересами\n{Fore.YELLOW}6.{Fore.WHITE} Назад")
            choice = input(Fore.YELLOW + "\nВыбор: ").strip()
            
            if choice == "1":
                users = self.session.query(User).all()
                for u in users: print(f"ID: {u.id} | {u.username}")
                uid = input("ID: ")
                if uid.isdigit():
                    self.current_user_id = int(uid)
                    self._save_current_user_id(self.current_user_id)
            elif choice == "3":
                if not self.current_user_id: continue
                user = self.session.query(User).get(self.current_user_id)
                
                # Показать текущие интересы
                current_interests = [interest.tag_name for interest in user.interests]
                if current_interests:
                    # Получить топ интересов с приоритетами
                    top_interests = self.aggregator.get_top_interests(user.id, 95)
                    print(Fore.WHITE + f"Текущие интересы ({len(current_interests)} всего, топ-95 для поиска): " + 
                          Fore.YELLOW + ", ".join(top_interests[:10]) + 
                          (f" и ещё {len(top_interests)-10}..." if len(top_interests) > 10 else ""))
                    print(Fore.CYAN + f"Лимит интересов для поиска: 95 тегов (для избежания ошибок Habr API)")
                else:
                    print(Fore.YELLOW + "У пользователя нет настроенных интересов.")

                print(f"\n{Fore.YELLOW}1.{Fore.WHITE} Добавить интерес")
                print(f"{Fore.YELLOW}2.{Fore.WHITE} Удалить интерес")
                print(f"{Fore.YELLOW}3.{Fore.WHITE} Назад")

                sub_choice = input(Fore.YELLOW + "\nВыбор: ").strip()

                if sub_choice == "1":
                    tag_input = input(Fore.YELLOW + "Введите интерес (тег) для добавления: ").strip()
                    if tag_input:
                        # Проверить, существует ли уже такой интерес
                        existing = self.session.query(UserInterest).filter_by(
                            user_id=user.id, 
                            tag_name=tag_input.lower()
                        ).first()

                        if existing:
                            print(Fore.YELLOW + f"Интерес '{tag_input}' уже существует.")
                            # Обновить время использования существующего интереса
                            existing.last_used = datetime.utcnow()
                            self.session.commit()
                        else:
                            interest = UserInterest(user_id=user.id, tag_name=tag_input.lower())
                            self.session.add(interest)
                            self.session.commit()
                            print(Fore.GREEN + f"✓ Добавлен интерес: {tag_input}")
                            
                            # Автоматически обрезать интересы до лимита 95 после добавления
                            try:
                                self.aggregator._trim_interests_to_limit(user.id, 95)
                                current_count = len([i for i in user.interests])
                                print(Fore.CYAN + f"Текущее количество интересов: {current_count}/95")
                            except Exception as e:
                                print(Fore.YELLOW + f"⚠ Предупреждение при обрезке интересов: {e}")
                elif sub_choice == "3": break
            elif choice == "6": break