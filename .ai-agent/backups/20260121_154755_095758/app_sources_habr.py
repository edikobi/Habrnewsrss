from typing import List, Dict, Any

from typing import List, Dict, Any, Optional
from collections import defaultdict
import datetime
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
        """Fetch articles from Habr RSS, using search RSS when keywords provided."""
        try:
            # Use search RSS if keywords provided, otherwise default feed
            if keywords:
                query = urllib.parse.quote_plus(' '.join(keywords))
                rss_url = f"https://habr.com/ru/rss/search/?q={query}&with_hubs=true&with_tags=true&limit=100"
            else:
                rss_url = self.RSS_URL

            feed = feedparser.parse(rss_url)
            content_items = []

            for entry in feed.entries:
                title = entry.title
                summary = entry.summary

                tags = self._extract_tags(entry)
                description = self._clean_html(summary)

                # Estimate difficulty (same logic)
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

                content_items.append(self._create_content_item(source_data, tags))
                if len(content_items) >= max_results:
                    break

            return content_items
        except Exception as e:
            print(f"Habr RSS error: {e}")
            return []

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