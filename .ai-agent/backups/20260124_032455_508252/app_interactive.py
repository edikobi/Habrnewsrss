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
        elif c == 3: self.search_content()
        elif c == 5: self.configure_user_settings()
        return c

    def view_content(self) -> None:
        if not self.current_user_id: return
        digest = self.aggregator.get_daily_digest(self.current_user_id)
        for i, item in enumerate(digest, 1):
            print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title} ({item.platform})")

    def search_content(self) -> None:
        query = input(Fore.YELLOW + "Поиск: ").strip()
        if not query: return
        results = self.aggregator.search_content([query])
        for i, item in enumerate(results, 1):
            print(f"{Fore.YELLOW}{i}.{Fore.WHITE} {item.title}")

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