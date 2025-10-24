# doc_sync/providers/yandex_wiki.py
import requests
from typing import Dict, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse
from .base import DocumentProvider

class YandexWikiProvider(DocumentProvider):
    """Провайдер для Yandex Wiki"""
    
    def setup_auth(self):
        self.oauth_token = self.auth_config.get('oauth_token')
        self.org_id = self.auth_config.get('org_id')
        self.base_url = "https://api.wiki.yandex.net/v1"
        
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"OAuth {self.oauth_token}",
            "X-Org-Id": str(self.org_id),
            "Accept": "application/json; charset=utf-8",
            "Content-Type": "application/json; charset=utf-8"
        })
    
    def extract_slug_from_url(self, url: str) -> str:
        """Извлечь slug из URL"""
        if "wiki.yandex.ru/" in url:
            parts = url.split("wiki.yandex.ru/")
            if len(parts) > 1:
                return parts[1].strip("/")
        return None

    def fetch_content(self, url: str) -> Tuple[str, Dict]:
        """Получить содержимое страницы Wiki"""
        slug = self.extract_slug_from_url(url)
        if not slug:
            raise ValueError(f"Cannot extract slug from URL: {url}")
    
        # Получаем страницу с контентом
        response = self.session.get(
            f"{self.base_url}/pages",
            params={
                "slug": slug,
                "fields": "content,attributes,breadcrumbs"
            }
        )
    
        if response.status_code != 200:
            raise Exception(f"Failed to fetch page: {response.status_code}")
    
        data = response.json()
    
        # Извлекаем метаданные
        metadata = {
            'title': data.get('title', 'Untitled'),
            'id': data.get('id'),
            'slug': data.get('slug'),
            'modified_at': data.get('attributes', {}).get('modified_at'),  # Это поле используется
            'page_type': data.get('page_type')
        }

        # ПРОБЛЕМА: modified_at не совпадает с тем что ожидает doc_sync.py
        # Нужно добавить стандартное поле:
        metadata['modified_time'] = data.get('attributes', {}).get('modified_at')
    
        # Получаем контент
        content = data.get('content', '')
    
        # Проверяем тип страницы
        page_type = data.get('page_type', 'page')
    
        # Если контент уже в текстовом/markdown формате (что обычно для Yandex Wiki)
        if page_type in ['page', 'wysiwyg'] and isinstance(content, str):
            # Возвращаем как есть с специальным маркером
            return content, {**metadata, '_is_markdown': True}
    
        # Для других типов конвертируем в HTML
        html_content = self._content_to_html(content, page_type)
        return html_content, metadata

    def _content_to_html(self, content, page_type: str) -> str:
        """Преобразовать контент в HTML для последующей конвертации"""
        # Этот метод вызывается только для специальных типов страниц
        if isinstance(content, dict):
            # Для структурированного контента создаем простой HTML
            html = "<div>"
            for key, value in content.items():
                html += f"<h3>{key}</h3><p>{value}</p>"
            html += "</div>"
            return html
    
        # Для всего остального возвращаем как строку в div
        return f"<div>{str(content)}</div>"    
  
    def check_for_updates(self, url: str, last_modified: Optional[datetime]) -> bool:
        """Проверить обновления страницы"""
        if not last_modified:
            return True
    
        slug = self.extract_slug_from_url(url)
        if not slug:
            return False
    
        try:
            from datetime import timezone
        
            response = self.session.get(
                f"{self.base_url}/pages",
                params={
                    "slug": slug,
                    "fields": "attributes"
                }
            )
        
            if response.status_code == 200:
                data = response.json()
                modified_at_str = data.get('attributes', {}).get('modified_at')
                if modified_at_str:
                    # Парсим дату
                    modified_at = datetime.fromisoformat(modified_at_str.replace('Z', '+00:00'))
                
                    # Нормализуем last_modified
                    if isinstance(last_modified, str):
                        last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                
                    if last_modified.tzinfo is None:
                        last_modified = last_modified.replace(tzinfo=timezone.utc)
                    if modified_at.tzinfo is None:
                        modified_at = modified_at.replace(tzinfo=timezone.utc)
                
                    return modified_at > last_modified
        except Exception as e:
            logger.error(f"Error checking updates for {url}: {e}")
            return True  # При ошибке лучше обновить
    
        return False