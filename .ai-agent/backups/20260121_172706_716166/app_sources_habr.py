from typing import List, Dict, Any

from typing import List, Dict, Any, Optional
from collections import defaultdict
import datetime
import logging
import urllib.parse
import feedparser
import requests
from requests.exceptions import RequestException, Timeout
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.sources.base import ContentSource
from app.database import ContentItem, Tag, ContentType, DifficultyLevel
from app.config import settings

class HabrSource(ContentSource):
    """Habr RSS feed content source."""
    
    RSS_URL = "https://habr.com/ru/rss/all/all/"

    def __init__(self):
        super().__init__(name="Habr", platform="habr", content_type=ContentType.HABR_ARTICLE)

    def fetch_content(self, keywords: List[str], max_results: int = 30) -> List[ContentItem]:
        """Fetch articles from Habr RSS with OR logic and fallback search."""
        logger = logging.getLogger(__name__)
        all_items = []
        seen_ids = set()

        logger.info(f"Habr поиск запущен с {len(keywords)} ключевыми словами: {keywords}, максимум: {max_results}")

        # Проверка на валидность ключевых слов
        if not keywords:
            logger.warning("Пустой список ключевых слов для поиска Habr")
            return []

        # Нормализация ключевых слов (удаление пробелов, приведение к нижнему регистру)
        normalized_keywords = [kw.strip().lower() for kw in keywords if kw and kw.strip()]
        if not normalized_keywords:
            logger.warning("Нет валидных ключевых слов после нормализации")
            return []

        logger.info(f"Нормализованные ключевые слова: {normalized_keywords}")

        try:
            # Уровень 1: Поиск по всем ключевым словам через OR
            if normalized_keywords:
                # Формируем запрос: keyword1 OR keyword2 OR keyword3
                # Кодируем каждый ключевой слова отдельно, затем соединяем
                encoded_keywords = [urllib.parse.quote_plus(kw) for kw in normalized_keywords]
                query = ' OR '.join(encoded_keywords)
                rss_url = f"https://habr.com/ru/rss/search/?q={query}&with_hubs=true&with_tags=true&limit=100"
                logger.info(f"Habr поиск Уровень 1 (OR запрос): {rss_url}")

                feed = feedparser.parse(rss_url)
                logger.info(f"Найдено {len(feed.entries)} статей в OR поиске")

                for entry in feed.entries:
                    if len(all_items) >= max_results:
                        break
                    if entry.id not in seen_ids:
                        item = self._process_entry(entry)
                        if item:
                            all_items.append(item)
                            seen_ids.add(entry.id)

            logger.info(f"После Уровня 1: {len(all_items)} статей")

            # Уровень 2: Если результатов мало или нет, ищем по каждому ключевому слову отдельно
            # Смягчаем условие: если меньше чем max_results/2 или вообще нет результатов
            if normalized_keywords and (len(all_items) < max_results // 2 or len(all_items) == 0):
                logger.info(f"Запуск Уровня 2: поиск по отдельным ключевым словам")
                for keyword in normalized_keywords:
                    if len(all_items) >= max_results:
                        break

                    query = urllib.parse.quote_plus(keyword)
                    rss_url = f"https://habr.com/ru/rss/search/?q={query}&with_hubs=true&with_tags=true&limit=50"
                    logger.info(f"Habr поиск Уровень 2 (одиночный): {rss_url}")

                    feed = feedparser.parse(rss_url)
                    logger.info(f"Найдено {len(feed.entries)} статей для ключевого слова '{keyword}'")

                    for entry in feed.entries:
                        if len(all_items) >= max_results:
                            break
                        if entry.id not in seen_ids:
                            item = self._process_entry(entry)
                            if item:
                                all_items.append(item)
                                seen_ids.add(entry.id)

            logger.info(f"После Уровня 2: {len(all_items)} статей")

            # Уровень 3: Если всё ещё мало результатов, используем общую RSS ленту с фильтрацией
            # Смягчаем условие: если меньше чем max_results или вообще нет результатов
            if len(all_items) < max_results or len(all_items) == 0:
                logger.info(f"Запуск Уровня 3: общая RSS лента с фильтрацией")
                logger.info(f"Habr поиск Уровень 3 (общая лента): {self.RSS_URL}")
                feed = feedparser.parse(self.RSS_URL)
                logger.info(f"Найдено {len(feed.entries)} статей в общей ленте")

                for entry in feed.entries:
                    if len(all_items) >= max_results:
                        break
                    if entry.id not in seen_ids:
                        # Фильтруем по ключевым словам в заголовке/описании для общей ленты
                        title_lower = entry.title.lower()
                        summary_lower = entry.summary.lower() if hasattr(entry, 'summary') else ""

                        if normalized_keywords:
                            keyword_match = any(kw.lower() in title_lower or kw.lower() in summary_lower 
                                              for kw in normalized_keywords)
                            if not keyword_match:
                                continue

                        item = self._process_entry(entry)
                        if item:
                            all_items.append(item)
                            seen_ids.add(entry.id)

            logger.info(f"Итог: найдено {len(all_items)} уникальных статей")
            return all_items

        except Exception as e:
            logger.error(f"Ошибка Habr RSS: {e}", exc_info=True)
            return []

    def _process_entry(self, entry) -> Optional[ContentItem]:
        """Process RSS entry into ContentItem with full text loading."""
        logger = logging.getLogger(__name__)
        try:
            title = entry.title
            summary = entry.summary

            tags = self._extract_tags(entry)
            description = self._clean_html(summary)

            # Estimate difficulty
            difficulty = DifficultyLevel.INTERMEDIATE
            if any(kw in title.lower() for kw in ["основы", "введение", "новичков"]):
                difficulty = DifficultyLevel.BEGINNER
            elif any(kw in title.lower() for kw in ["сложные", "архитектура", "внутреннее устройство"]):
                difficulty = DifficultyLevel.ADVANCED

            # Fetch FULL TEXT immediately
            full_text = self.fetch_full_text(entry.link)

            source_data = {
                'id': entry.id,
                'title': title,
                'description': description,
                'full_text': full_text,
                'url': entry.link,
                'published_at': datetime.datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') else None,
                'difficulty': difficulty,
                'duration_minutes': 10  # Default for articles
            }

            logger.debug(f"Processed Habr article: {title}")
            return self._create_content_item(source_data, tags)
        except Exception as e:
            logger.error(f"Error processing Habr entry {getattr(entry, 'link', 'unknown')}: {e}")
            return None

    def search_live(self, keywords: List[str], max_results: int = 30, session: Optional[Session] = None) -> List[ContentItem]:
        """Search Habr articles in real-time via RSS and return ContentItem objects without saving to database."""
        try:
            articles = self.fetch_content(keywords, max_results)
            if not session:
                return articles

            filtered_articles = []
            for item in articles:
                exists = session.query(ContentItem).filter_by(
                    source_id=item.source_id,
                    platform=self.platform
                ).first()
                if not exists:
                    filtered_articles.append(item)
            return filtered_articles
        except Exception as e:
            print(f"Habr live search error: {e}")
            return []

    def save_selected_items(self, items: List[ContentItem], session: Session) -> List[ContentItem]:
        """Save selected ContentItem objects to database, handling duplicate detection."""
        saved_items = []
        tag_cache = {}
        try:
            for item in items:
                exists = session.query(ContentItem).filter_by(
                    source_id=item.source_id,
                    platform=self.platform
                ).first()

                if not exists:
                    # Загрузить полный текст статьи, если его еще нет
                    if not item.full_text:
                        item.full_text = self.fetch_full_text(item.url)

                    new_tags = []
                    for tag in (item.tags or []):
                        # Normalize tag name to lowercase for consistency
                        tag_name = tag.name.lower() if tag.name else ""
                        if tag_name in tag_cache:
                            db_tag = tag_cache[tag_name]
                        else:
                            db_tag = session.query(Tag).filter_by(name=tag_name).first()
                            if not db_tag:
                                db_tag = Tag(name=tag_name)
                                session.add(db_tag)
                            tag_cache[tag_name] = db_tag
                        new_tags.append(db_tag)
                    item.tags = new_tags
                    session.add(item)
                    saved_items.append(item)

            session.commit()
            return saved_items
        except Exception as e:
            session.rollback()
            print(f"Error saving Habr items: {e}")
            return []

    def _extract_tags(self, entry: Dict[str, Any]) -> List[Tag]:
        """Extract tags from RSS entry."""
        tag_names = set()
        if hasattr(entry, 'tags'):
            for t in entry.tags:
                # Normalize tag names to lowercase
                tag_name = t.term.lower() if hasattr(t, 'term') else str(t).lower()
                tag_names.add(tag_name)
        return [Tag(name=name) for name in tag_names]

    def _clean_html(self, html: str) -> str:
        """Remove HTML tags and truncate text."""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=' ')
        return text[:500] + "..." if len(text) > 500 else text

    def fetch_full_text(self, url: str, timeout: int = 10) -> str:
        """Fetch full text content from Habr article URL with ads and extra content separated."""
        import re
        import logging
        logger = logging.getLogger(__name__)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code != 200:
                return ""

            soup = BeautifulSoup(response.text, "html.parser")

            # Remove unwanted elements before extracting text
            for tag in soup(['script', 'style', 'nav', 'aside', 'footer', 'header', 'noscript', 'iframe']):
                tag.extract()

            # Remove ad-related elements by class/id patterns
            try:
                for element in soup.find_all(class_=re.compile(r'ad|advertisement|banner|promo|commercial', re.I)):
                    element.extract()
                for element in soup.find_all(id=re.compile(r'ad|advertisement|banner|promo|commercial', re.I)):
                    element.extract()
            except Exception:
                pass  # Continue if regex fails

            # Find main article container (priority order)
            container = (
                soup.find('div', class_='tm-article-body') or 
                soup.find('div', class_='article-formatted-body') or
                soup.find('div', class_='post__text') or 
                soup.find('div', class_='tm-article-presenter__content') or
                soup.find('div', class_='article__content') or
                soup.find('article') or
                soup.find('div', class_='content') or
                soup.find('div', class_='tm-article-presenter__body') or
                soup.find('div', class_='tm-page-article__body') or
                soup.find('div', {'id': 'post-content-body'})
            )

            if container:
                logger.debug(f"Найден контейнер для статьи {url}")
                # Extract main article text
                main_text = container.get_text(separator='\n', strip=True)

                # Remove container to avoid duplication in extra content
                container.extract()

                # Extract remaining content (sidebars, additional materials)
                extra_text = soup.get_text(separator='\n', strip=True)

                # Append extra content with marker if substantial
                if extra_text and len(extra_text) > 100:
                    main_text += '\n\n' + '='*40 + '\n[ДОПОЛНИТЕЛЬНЫЕ МАТЕРИАЛЫ]\n' + '='*40 + '\n\n' + extra_text
            else:
                logger.warning(f"Не найден контейнер для статьи {url}, используется fallback")
                # Fallback: extract all remaining text
                main_text = soup.get_text(separator='\n', strip=True)

            # Clean up excessive whitespace (max 2 consecutive newlines)
            try:
                main_text = re.sub(r'\n{3,}', '\n\n', main_text)
            except Exception:
                pass  # Return uncleaned text if regex fails

            return main_text.strip()

        except (RequestException, Timeout, Exception) as e:
            logger.warning(f"Error fetching full text from {url}: {e}")
            return ""