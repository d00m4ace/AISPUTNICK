# doc_sync/providers/confluence.py
import requests
from atlassian import Confluence
from bs4 import BeautifulSoup
from typing import Dict, Optional, Tuple
from datetime import datetime
import logging
import re
import os
import sys

# Добавляем родительскую директорию в path для импортов
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from providers.base import DocumentProvider

logger = logging.getLogger(__name__)

class ConfluenceProvider(DocumentProvider):
    """Провайдер для Atlassian Confluence"""
    
    def setup_auth(self):
        """Настройка авторизации для Confluence"""
        self.site_url = self.auth_config.get('site_url')
        self.email = self.auth_config.get('email')
        self.api_token = self.auth_config.get('api_token')
        
        if not all([self.site_url, self.email, self.api_token]):
            raise ValueError("site_url, email, and api_token are required for Confluence provider")
        
        # Инициализируем Confluence клиент
        # Убираем /wiki из URL если есть для atlassian библиотеки
        base_url = self.site_url.rstrip('/').replace('/wiki', '')
        wiki_url = f"{base_url}/wiki"
        
        self.confluence = Confluence(
            url=wiki_url,
            username=self.email,
            password=self.api_token
        )
        
        # Также настраиваем requests сессию для прямых API вызовов
        self.session = requests.Session()
        self.session.auth = (self.email, self.api_token)
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json"
        })
        
        logger.info(f"Confluence provider initialized for: {wiki_url}")
    
    def extract_page_info(self, url: str) -> Dict[str, str]:
        """Извлечь информацию о странице из URL"""
        # Примеры URL:
        # https://smartchip79.atlassian.net/wiki/spaces/test/pages/622593/AzerothCore
        # https://smartchip79.atlassian.net/wiki/spaces/SPACE/pages/PAGE_ID/Page-Title
        
        if '/wiki/spaces/' not in url:
            raise ValueError(f"Invalid Confluence URL format: {url}")
        
        # Парсим URL
        parts = url.split('/wiki/spaces/')
        if len(parts) != 2:
            raise ValueError(f"Cannot parse Confluence URL: {url}")
        
        base_url = parts[0]
        path_parts = parts[1].split('/')
        
        if len(path_parts) < 3 or path_parts[1] != 'pages':
            raise ValueError(f"Invalid Confluence page URL format: {url}")
        
        space_key = path_parts[0]
        page_id = path_parts[2]
        
        # Извлекаем заголовок если есть
        title = None
        if len(path_parts) > 3:
            title = path_parts[3].replace('-', ' ')
        
        return {
            'base_url': base_url,
            'space_key': space_key,
            'page_id': page_id,
            'title': title
        }
    
    def fetch_content(self, url: str) -> Tuple[str, Dict]:
        """Получить содержимое Confluence страницы"""
        page_info = self.extract_page_info(url)
        page_id = page_info['page_id']
        space_key = page_info['space_key']
        
        try:
            # Метод 1: Используем atlassian библиотеку для получения страницы
            page = self.confluence.get_page_by_id(
                page_id=int(page_id), 
                expand="body.storage,version,space"
            )
            
            # Извлекаем метаданные
            metadata = {
                'title': page.get('title', 'Untitled'),
                'id': page.get('id'),
                'space_key': page.get('space', {}).get('key', space_key),
                'version': page.get('version', {}).get('number'),
                'last_modified': page.get('version', {}).get('when'),  # Это поле используется
                'url': url,
                'page_type': page.get('type', 'page')
            }

            # ДОБАВИТЬ: стандартное поле
            metadata['modified_time'] = page.get('version', {}).get('when')
            
            # Получаем HTML содержимое
            html_content = page.get('body', {}).get('storage', {}).get('value', '')
            
            if not html_content:
                # Попробуем альтернативный способ
                html_content = self._fetch_content_alternative(page_id)
            
            # Очищаем и обрабатываем HTML
            processed_html = self._process_confluence_html(html_content)
            
            logger.info(f"Successfully fetched Confluence page: {metadata['title']}")
            return processed_html, metadata
            
        except Exception as e:
            logger.error(f"Error fetching Confluence page {page_id}: {e}")
            # Попробуем альтернативный метод через прямой API
            return self._fetch_content_direct_api(page_info)
    
    def _fetch_content_alternative(self, page_id: str) -> str:
        """Альтернативный способ получения контента через прямой API"""
        try:
            response = self.session.get(
                f"{self.site_url}/rest/api/content/{page_id}",
                params={
                    'expand': 'body.storage'
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('body', {}).get('storage', {}).get('value', '')
            else:
                logger.warning(f"Failed to fetch content via direct API: {response.status_code}")
                return ""
                
        except Exception as e:
            logger.warning(f"Alternative content fetch failed: {e}")
            return ""
    
    def _fetch_content_direct_api(self, page_info: Dict) -> Tuple[str, Dict]:
        """Прямой вызов Confluence REST API"""
        page_id = page_info['page_id']
        
        try:
            response = self.session.get(
                f"{page_info['base_url']}/wiki/rest/api/content/{page_id}",
                params={
                    'expand': 'body.storage,version,space'
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to fetch page via direct API: {response.status_code}, {response.text}")
            
            data = response.json()
            
            metadata = {
                'title': data.get('title', 'Untitled'),
                'id': data.get('id'),
                'space_key': data.get('space', {}).get('key'),
                'version': data.get('version', {}).get('number'),
                'last_modified': data.get('version', {}).get('when'),
                'url': f"{page_info['base_url']}/wiki{data.get('_links', {}).get('webui', '')}",
                'page_type': data.get('type', 'page')
            }
            
            html_content = data.get('body', {}).get('storage', {}).get('value', '')
            processed_html = self._process_confluence_html(html_content)
            
            return processed_html, metadata
            
        except Exception as e:
            logger.error(f"Direct API fetch failed: {e}")
            raise
    
    def _process_confluence_html(self, html_content: str) -> str:
        """Обработать и очистить Confluence HTML"""
        if not html_content:
            return "<p>No content available</p>"
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Удаляем Confluence-специфичные элементы
            for element in soup.find_all(['ac:structured-macro', 'ac:parameter', 'ac:rich-text-body']):
                element.decompose()
            
            # Обрабатываем Confluence макросы
            html_content = self._process_confluence_macros(str(soup))
            
            # Очищаем лишние атрибуты
            soup = BeautifulSoup(html_content, 'html.parser')
            for tag in soup.find_all():
                # Удаляем Confluence-специфичные атрибуты
                attrs_to_remove = [attr for attr in tag.attrs.keys() 
                                 if attr.startswith(('ac:', 'ri:', 'data-'))]
                for attr in attrs_to_remove:
                    del tag[attr]
            
            return str(soup)
            
        except Exception as e:
            logger.warning(f"HTML processing failed: {e}")
            # Возвращаем исходный HTML в случае ошибки
            return html_content
    
    def _process_confluence_macros(self, html: str) -> str:
        """Обработать Confluence макросы"""
        # Простая обработка некоторых популярных макросов
        
        # Макрос code
        html = re.sub(
            r'<ac:structured-macro[^>]*ac:name="code"[^>]*>(.*?)</ac:structured-macro>',
            r'<pre><code>\1</code></pre>',
            html,
            flags=re.DOTALL
        )
        
        # Макрос info
        html = re.sub(
            r'<ac:structured-macro[^>]*ac:name="info"[^>]*>(.*?)</ac:structured-macro>',
            r'<div class="info-box">\1</div>',
            html,
            flags=re.DOTALL
        )
        
        # Макрос warning
        html = re.sub(
            r'<ac:structured-macro[^>]*ac:name="warning"[^>]*>(.*?)</ac:structured-macro>',
            r'<div class="warning-box">\1</div>',
            html,
            flags=re.DOTALL
        )
        
        # Макрос note
        html = re.sub(
            r'<ac:structured-macro[^>]*ac:name="note"[^>]*>(.*?)</ac:structured-macro>',
            r'<div class="note-box">\1</div>',
            html,
            flags=re.DOTALL
        )
        
        # Таблицы содержания
        html = re.sub(
            r'<ac:structured-macro[^>]*ac:name="toc"[^>]*>.*?</ac:structured-macro>',
            '<div class="table-of-contents">[Table of Contents]</div>',
            html,
            flags=re.DOTALL
        )
        
        return html
    
    def check_for_updates(self, url: str, last_modified: Optional[datetime]) -> bool:
        """Проверить обновления страницы"""
        if not last_modified:
            return True
        
        try:
            page_info = self.extract_page_info(url)
            page_id = page_info['page_id']
            
            # Получаем только информацию о версии
            page = self.confluence.get_page_by_id(
                page_id=int(page_id), 
                expand="version"
            )
            
            version_info = page.get('version', {})
            when_str = version_info.get('when')
            
            if when_str:
                # Парсим дату из Confluence формата
                page_modified = datetime.fromisoformat(
                    when_str.replace('Z', '+00:00')
                )
                return page_modified > last_modified
                
        except Exception as e:
            logger.error(f"Error checking updates for {url}: {e}")
            return False
        
        return False
    
    def check_for_updates(self, url: str, last_modified: Optional[datetime]) -> bool:
        """Проверить обновления страницы"""
        if not last_modified:
            return True
    
        try:
            from datetime import timezone
        
            page_info = self.extract_page_info(url)
            page_id = page_info['page_id']
        
            # Получаем только информацию о версии
            page = self.confluence.get_page_by_id(
                page_id=int(page_id), 
                expand="version"
            )
        
            version_info = page.get('version', {})
            when_str = version_info.get('when')
        
            if when_str:
                # Парсим дату из Confluence формата
                page_modified = datetime.fromisoformat(
                    when_str.replace('Z', '+00:00')
                )
            
                # Нормализуем last_modified
                if isinstance(last_modified, str):
                    last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
            
                if last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=timezone.utc)
                if page_modified.tzinfo is None:
                    page_modified = page_modified.replace(tzinfo=timezone.utc)
            
                return page_modified > last_modified
            
        except Exception as e:
            logger.error(f"Error checking updates for {url}: {e}")
            return True  # При ошибке лучше обновить
    
        return False