# doc_sync/providers/buildin_ai.py
import requests
from typing import Dict, Optional, Tuple, List
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import json
import logging
import re
import sys
import os
import time

# Добавляем родительскую директорию в path для импортов
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from providers.base import DocumentProvider

logger = logging.getLogger(__name__)

class BuildinProvider(DocumentProvider):
    """Провайдер для Buildin.ai с поддержкой Google Drive контента"""
    
    def __init__(self, auth_config: Dict):
        super().__init__(auth_config)
        self.total_blocks_to_process = 0
        self.blocks_processed = 0
        self.start_time = None
        self.show_progress = auth_config.get('show_progress', True)
    
    def setup_auth(self):
        """Настройка авторизации для Buildin.ai"""
        self.bot_token = self.auth_config.get('bot_token')
        if not self.bot_token:
            raise ValueError("bot_token is required for Buildin provider")
        
        self.base_url = "https://api.buildin.ai/v1"
        
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        
        # Опция для включения Google Drive контента
        self.include_gdrive_content = self.auth_config.get('include_gdrive_content', False)
        
        # Если включена опция, инициализируем Google Drive провайдера
        self.gdrive_provider = None
        if self.include_gdrive_content:
            gdrive_auth = self.auth_config.get('gdrive_auth_config')
            if gdrive_auth:
                try:
                    from providers.google_docs import GoogleDocsProvider
                    self.gdrive_provider = GoogleDocsProvider(gdrive_auth)
                    logger.info("Google Drive provider initialized for content inclusion")
                except Exception as e:
                    logger.warning(f"Failed to initialize Google Drive provider: {e}")
                    self.include_gdrive_content = False
        
        logger.info(f"Buildin provider initialized with base URL: {self.base_url}")      

    def _update_progress(self, increment: int = 1):
        """Обновить прогресс-бар"""
        if not self.show_progress:
            return
        
        if increment > 0:
            self.blocks_processed += increment
    
        # Динамически увеличиваем ожидаемое количество если нужно
        if self.blocks_processed > self.total_blocks_to_process:
            # Увеличиваем ожидаемое количество с запасом
            self.total_blocks_to_process = self.blocks_processed + 10
    
        # Расчет прогресса
        if self.total_blocks_to_process > 0:
            percentage = min(100.0, (self.blocks_processed / self.total_blocks_to_process * 100))
        else:
            percentage = 0
    
        # Расчет времени
        elapsed_time = time.time() - self.start_time if self.start_time else 0
        time_str = f"{elapsed_time:.1f}s"
    
        # Прогресс-бар с фиксированной длиной
        bar_length = 30
        filled = int(bar_length * min(1.0, self.blocks_processed / self.total_blocks_to_process)) if self.total_blocks_to_process > 0 else 0
        bar = '█' * filled + '░' * (bar_length - filled)
    
        # Вывод прогресса
        print(f"\r Processing: [{bar}] {self.blocks_processed}/{self.total_blocks_to_process} ({percentage:.1f}%) - {time_str}", end='', flush=True)

    def _count_total_blocks(self, page_id: str, count_nested: bool = True) -> int:
        """Подсчитать общее количество блоков на странице"""
        total = 0
        has_more = True
        start_cursor = None
        blocks_with_children = []
        child_pages = []
    
        # Первый проход - считаем основные блоки
        while has_more:
            params = {'page_size': 100}
            if start_cursor:
                params['start_cursor'] = start_cursor
        
            try:
                response = self.session.get(
                    f"{self.base_url}/blocks/{page_id}/children",
                    params=params
                )
            
                if response.status_code != 200:
                    break
            
                data = response.json()
                blocks = data.get('results', [])
                total += len(blocks)
            
                # Собираем информацию о блоках
                for block in blocks:
                    block_type = block.get('type')
                
                    # Если это дочерняя страница и включен fetch_child_pages
                    if block_type == 'child_page' and self.auth_config.get('fetch_child_pages', False):
                        child_pages.append(block.get('id'))
                        # Добавляем примерное количество для preview (5 блоков + свойства)
                        total += 6
                
                    # Собираем блоки с has_children для подсчета вложенных
                    elif block.get('has_children') and count_nested:
                        blocks_with_children.append(block.get('id'))
            
                has_more = data.get('has_more', False)
                start_cursor = data.get('next_cursor')
            
                # Защита от слишком больших страниц
                if total > 5000:
                    break
                
            except Exception as e:
                logger.warning(f"Error counting blocks: {e}")
                break
    
        # Подсчитываем вложенные блоки (toggle, lists и т.д.)
        if count_nested and blocks_with_children:
            # Для больших страниц берем выборку
            sample_size = min(10, len(blocks_with_children))
            sample = blocks_with_children[:sample_size]
        
            nested_count = 0
            for block_id in sample:
                try:
                    response = self.session.get(f"{self.base_url}/blocks/{block_id}/children")
                    if response.status_code == 200:
                        data = response.json()
                        nested_count += len(data.get('results', []))
                except:
                    pass
        
            # Экстраполируем для всех блоков с детьми
            if sample_size > 0:
                avg_nested = nested_count / sample_size
                estimated_nested = int(avg_nested * len(blocks_with_children))
                total += estimated_nested
    
        return total

    def extract_page_id(self, url: str) -> str:
        """Извлечь ID страницы из URL"""
        # Убираем якорь если есть
        if '#' in url:
            url = url.split('#')[0]
        
        if '/' not in url:
            # Вероятно, это уже ID
            return url
        
        # Попробуем извлечь из URL
        if 'buildin.ai' in url:
            parts = url.rstrip('/').split('/')
            if len(parts) > 0:
                # Берем последнюю часть URL как ID
                return parts[-1]
        
        raise ValueError(f"Cannot extract page ID from URL: {url}")
    
    def _extract_google_urls(self, properties: Dict) -> List[Dict]:
        """Извлечь Google Drive URL из свойств страницы"""
        google_urls = []
        
        # Проверяем что properties не None и является словарем
        if not properties or not isinstance(properties, dict):
            return google_urls
        
        for prop_name, prop_value in properties.items():
            # Проверяем что prop_value не None и является словарем
            if not prop_value or not isinstance(prop_value, dict):
                continue
                
            prop_type = prop_value.get('type')
            if not prop_type:
                continue
            
            # Проверяем URL свойства
            if prop_type == 'url':
                url = prop_value.get('url', '')
                if url and ('docs.google.com' in url or 'drive.google.com' in url):
                    google_urls.append({
                        'property_name': prop_name,
                        'url': url,
                        'type': self._detect_google_doc_type(url)
                    })
            
            # Проверяем rich_text свойства на наличие ссылок
            elif prop_type == 'rich_text':
                rich_text_items = prop_value.get('rich_text')
                if rich_text_items and isinstance(rich_text_items, list):
                    for item in rich_text_items:
                        if isinstance(item, dict) and 'text' in item:
                            text_obj = item.get('text')
                            if isinstance(text_obj, dict):
                                text = text_obj.get('content', '')
                                # Ищем Google URLs в тексте
                                urls = re.findall(r'https?://(?:docs|drive)\.google\.com/[^\s]+', text)
                                for url in urls:
                                    google_urls.append({
                                        'property_name': prop_name,
                                        'url': url,
                                        'type': self._detect_google_doc_type(url)
                                    })
        
        return google_urls
   
    def _detect_google_doc_type(self, url: str) -> str:
        """Определить тип Google документа по URL"""
        if 'spreadsheets' in url:
            return 'spreadsheet'
        elif 'document' in url:
            return 'document'
        elif 'presentation' in url:
            return 'presentation'
        elif 'drive.google.com' in url:
            return 'file'
        return 'unknown'
    
    def _fetch_google_content(self, url: str, doc_type: str) -> str:
        """Получить содержимое Google документа"""
        if not self.gdrive_provider:
            return ""
        
        try:
            # Получаем содержимое через Google Drive провайдера
            content, metadata = self.gdrive_provider.fetch_content(url)
            
            # Конвертируем HTML в Markdown если нужно
            if not metadata.get('_is_markdown', False):
                try:
                    from converters import HTMLToMarkdownConverter
                    converter = HTMLToMarkdownConverter()
                    content = converter.convert(content)
                except ImportError:
                    # Если не можем импортировать конвертер, делаем простое преобразование
                    content = re.sub(r'<[^>]+>', '', content)  # Удаляем HTML теги
                    content = content.strip()
            
            return content
            
        except Exception as e:
            logger.warning(f"Failed to fetch Google content from {url}: {e}")
            return f"*[Не удалось загрузить содержимое: {str(e)}]*"
    
    def fetch_content(self, url: str) -> Tuple[str, Dict]:
        """Получить содержимое страницы Buildin"""
        page_id = self.extract_page_id(url)
    
        # Инициализация
        self.blocks_processed = 0
        self.start_time = time.time()
    
        if self.show_progress:
            print(f"\n🚀 Fetching Buildin page: {page_id}")
            print("📊 Counting blocks...")
    
        # Получаем информацию о странице
        page_response = self.session.get(f"{self.base_url}/pages/{page_id}")
    
        if page_response.status_code != 200:
            raise Exception(f"Failed to fetch page: {page_response.status_code}, {page_response.text}")
    
        page_data = page_response.json()
        
        # Проверяем что page_data валидный
        if not page_data or not isinstance(page_data, dict):
            raise Exception(f"Invalid page data received for {page_id}")
    
        # Извлекаем метаданные
        metadata = {
            'title': self._extract_title(page_data),
            'id': page_data.get('id'),
            'created_time': page_data.get('created_time'),
            'last_edited_time': page_data.get('last_edited_time'),
            'url': page_data.get('url', url)
        }

        # ДОБАВИТЬ: стандартное поле для совместимости
        metadata['modified_time'] = page_data.get('last_edited_time')
    
        if self.show_progress:
            print(f"📄 Page: {metadata['title']}")
    
        # Быстрый подсчет без вложенных
        quick_count = self._count_total_blocks(page_id, count_nested=False)
    
        # Для маленьких страниц делаем точный подсчет
        if quick_count < 5000:
            self.total_blocks_to_process = self._count_total_blocks(page_id, count_nested=True)
        else:
            # Для больших используем приблизительную оценку
            self.total_blocks_to_process = quick_count
        
            # Если есть дочерние страницы с preview, добавляем больше
            if self.auth_config.get('fetch_child_pages', False):
                # Приблизительная оценка: каждая дочерняя страница добавляет ~5 блоков
                self.total_blocks_to_process = int(quick_count * 1.5)
    
        # Минимум 1 блоков для избежания деления на 0
        self.total_blocks_to_process = max(1, self.total_blocks_to_process)
    
        # ИСПРАВЛЕНИЕ: Безопасно получаем properties
        properties = page_data.get('properties') or {}
        
        # Добавляем блоки для свойств и Google docs если есть
        if properties and isinstance(properties, dict):
            props_to_process = len([p for p in properties if p.lower() not in ['title', 'name']])
            self.total_blocks_to_process += props_to_process
    
        if self.include_gdrive_content and properties:
            google_urls = self._extract_google_urls(properties)
            self.total_blocks_to_process += len(google_urls)
    
        if self.show_progress:
            if quick_count >= 5000:
                print(f"📦 Estimated items to process: ~{self.total_blocks_to_process}")
            else:
                print(f"📦 Total items to process: {self.total_blocks_to_process}")
            self._update_progress(0)  # Инициализируем прогресс-бар
    
        # Получаем блоки страницы и конвертируем в Markdown
        markdown_content = self._fetch_page_blocks_as_markdown(page_id, page_data)
    
        # Добавляем свойства страницы с проверкой
        properties_markdown = ""
        if properties and isinstance(properties, dict):
            properties_markdown = self._properties_to_markdown(properties)
    
        # Извлекаем Google URLs если включена опция
        google_content = ""
        if self.include_gdrive_content and properties:
            google_urls = self._extract_google_urls(properties) if properties else []
            if google_urls:
                google_content = "\n\n## 🔎 Прикрепленные документы\n\n"
                for doc_info in google_urls:
                    google_content += f"### 📄 {doc_info['property_name']}\n\n"
                    google_content += f"**URL:** {doc_info['url']}\n"
                    google_content += f"**Тип:** {doc_info['type']}\n\n"
                
                    # Получаем содержимое документа
                    doc_content = self._fetch_google_content(doc_info['url'], doc_info['type'])
                    if doc_content:
                        google_content += "#### Содержимое:\n\n"
                        google_content += doc_content
                        google_content += "\n\n---\n\n"
                    else:
                        google_content += "*[Содержимое недоступно]*\n\n---\n\n"
                
                    self._update_progress(1)
    
        # Комбинируем все в Markdown
        full_markdown = ""
        if properties_markdown:
            full_markdown += f"## Properties\n\n{properties_markdown}\n\n---\n\n"
        full_markdown += markdown_content
        if google_content:
            full_markdown += google_content
    
        # Финальная информация
        if self.show_progress:
            # Финальное обновление прогресса на 100%
            if self.blocks_processed != self.total_blocks_to_process:
                self.total_blocks_to_process = self.blocks_processed
                self._update_progress(0)
        
            elapsed = time.time() - self.start_time
            print(f"\n✅ Completed in {elapsed:.1f}s")
    
        # Возвращаем контент с флагом, что это уже Markdown
        return full_markdown, {**metadata, '_is_markdown': True}

    def _extract_title(self, page_data: Dict) -> str:
        """Извлечь заголовок из данных страницы"""
        # Проверяем что page_data не None и является словарем
        if not page_data or not isinstance(page_data, dict):
            return 'Untitled'
            
        properties = page_data.get('properties')
        
        # Проверяем что properties не None и является словарем
        if not properties or not isinstance(properties, dict):
            return 'Untitled'
        
        # Ищем свойство title или Title
        for prop_name in ['title', 'Title', 'Name', 'name']:
            if prop_name in properties:
                prop = properties[prop_name]
                # Проверяем что prop не None и является словарем
                if prop and isinstance(prop, dict):
                    if prop.get('type') == 'title' and 'title' in prop:
                        title_array = prop.get('title')
                        # Проверяем что title_array является списком
                        if isinstance(title_array, list):
                            for item in title_array:
                                if isinstance(item, dict) and 'text' in item:
                                    text_obj = item.get('text')
                                    if isinstance(text_obj, dict):
                                        content = text_obj.get('content', '')
                                        if content:
                                            return content
        
        return 'Untitled'
    
    def _properties_to_markdown(self, properties: Dict) -> str:
        """Конвертировать свойства страницы в Markdown"""
        # Проверяем что properties не None и является словарем
        if not properties or not isinstance(properties, dict):
            return ""
        
        markdown = ""
        
        for prop_name, prop_value in properties.items():
            # Пропускаем title, так как он уже в заголовке
            if prop_name.lower() in ['title', 'name']:
                continue
            
            # Проверяем что prop_value не None и является словарем
            if not prop_value or not isinstance(prop_value, dict):
                continue
                
            prop_type = prop_value.get('type')
            if not prop_type:
                continue
                
            content = self._extract_property_content(prop_value, prop_type)
            
            if content:
                # Для URL делаем кликабельные ссылки
                if prop_type == 'url':
                    markdown += f"**{prop_name}:** [{content}]({content})\n"
                else:
                    markdown += f"**{prop_name}:** {content}\n"
            
            self._update_progress(1)
        
        return markdown
    
    def _extract_property_content(self, prop_value: Dict, prop_type: str) -> str:
        """Извлечь содержимое из свойства"""
        # Добавляем проверку на None и тип
        if not prop_value or not isinstance(prop_value, dict):
            return ''
            
        if prop_type == 'rich_text':
            texts = []
            rich_text_items = prop_value.get('rich_text')
            if rich_text_items and isinstance(rich_text_items, list):
                for item in rich_text_items:
                    if isinstance(item, dict) and 'text' in item:
                        text_obj = item.get('text')
                        if isinstance(text_obj, dict):
                            content = text_obj.get('content', '')
                            if content:
                                texts.append(content)
            return ' '.join(texts)
        
        elif prop_type == 'select':
            select = prop_value.get('select')
            if select and isinstance(select, dict):
                return select.get('name', '')
            return ''
        
        elif prop_type == 'multi_select':
            items = prop_value.get('multi_select')
            if items and isinstance(items, list):
                names = []
                for item in items:
                    if isinstance(item, dict):
                        name = item.get('name', '')
                        if name:
                            names.append(name)
                return ', '.join(names)
            return ''
        
        elif prop_type == 'checkbox':
            checkbox_value = prop_value.get('checkbox')
            if checkbox_value is not None:
                return '✔' if checkbox_value else '✗'
            return ''
        
        elif prop_type == 'number':
            number = prop_value.get('number')
            return str(number) if number is not None else ''
        
        elif prop_type == 'date':
            date_obj = prop_value.get('date')
            if date_obj and isinstance(date_obj, dict):
                start = date_obj.get('start', '')
                end = date_obj.get('end', '')
                if end:
                    return f"{start} - {end}"
                return start
            return ''
        
        elif prop_type == 'url':
            return prop_value.get('url', '')
        
        elif prop_type == 'email':
            return prop_value.get('email', '')
        
        elif prop_type == 'phone_number':
            return prop_value.get('phone_number', '')
        
        elif prop_type == 'people':
            people = prop_value.get('people')
            if people and isinstance(people, list):
                names = []
                for person in people:
                    if isinstance(person, dict):
                        name = person.get('name', 'Unknown')
                        if name:
                            names.append(name)
                return ', '.join(names)
            return ''
        
        elif prop_type == 'files':
            files = prop_value.get('files')
            if files and isinstance(files, list):
                links = []
                for file in files:
                    if isinstance(file, dict):
                        name = file.get('name', 'File')
                        external = file.get('external')
                        if external and isinstance(external, dict):
                            url = external.get('url', '')
                            if url:
                                links.append(f"[{name}]({url})")
                        else:
                            links.append(name)
                return ', '.join(links)
            return ''
        
        return ''
    
    def _fetch_page_blocks_as_markdown(self, page_id: str, page_data: Dict) -> str:
        """Получить блоки страницы и конвертировать в Markdown"""
        markdown = ""
        has_more = True
        start_cursor = None
        total_blocks = 0
        child_pages_count = 0
    
        while has_more:
            # Формируем параметры запроса
            params = {'page_size': 100}
            if start_cursor:
                params['start_cursor'] = start_cursor
        
            # Получаем блоки
            response = self.session.get(
                f"{self.base_url}/blocks/{page_id}/children",
                params=params
            )
        
            if response.status_code != 200:
                logger.warning(f"Failed to fetch blocks: {response.status_code}")
                break
        
            data = response.json()
            blocks = data.get('results', [])
        
            # Конвертируем блоки в Markdown
            for block in blocks:
                block_type = block.get('type')
            
                # Считаем дочерние страницы
                if block_type == 'child_page':
                    child_pages_count += 1
            
                # Конвертируем блок (прогресс обновится внутри)
                block_markdown = self._block_to_markdown(block)
                if block_markdown:
                    markdown += block_markdown + "\n"
            
                # Обновляем прогресс для этого блока
                self._update_progress(1)
        
            total_blocks += len(blocks)
        
            # Проверяем пагинацию
            has_more = data.get('has_more', False)
            start_cursor = data.get('next_cursor')
        
            # Защита от бесконечного цикла
            if not blocks:
                break
        
            if total_blocks > 10000:
                logger.warning(f"Reached limit of 10000 blocks, stopping")
                break
    
        # Если страница содержит только дочерние страницы, добавим заголовок
        if child_pages_count > 0 and child_pages_count == total_blocks:
            header = f"## Дочерние страницы ({child_pages_count})\n\n"
            markdown = header + markdown
    
        logger.info(f"Processed {total_blocks} blocks, including {child_pages_count} child pages")
    
        return markdown
    
    def _block_to_markdown(self, block: Dict, indent_level: int = 0, is_nested: bool = False) -> str:
        """Конвертировать блок в Markdown"""
        block_type = block.get('type')
        indent = "  " * indent_level
    
        if block_type == 'paragraph':
            content = self._rich_text_to_markdown(block.get('paragraph', {}).get('rich_text', []))
            return f"{indent}{content}" if content else ""
    
        elif block_type == 'heading_1':
            content = self._rich_text_to_markdown(block.get('heading_1', {}).get('rich_text', []))
            return f"{indent}# {content}" if content else ""
    
        elif block_type == 'heading_2':
            content = self._rich_text_to_markdown(block.get('heading_2', {}).get('rich_text', []))
            return f"{indent}## {content}" if content else ""
    
        elif block_type == 'heading_3':
            content = self._rich_text_to_markdown(block.get('heading_3', {}).get('rich_text', []))
            return f"{indent}### {content}" if content else ""
    
        elif block_type == 'bulleted_list_item':
            content = self._rich_text_to_markdown(block.get('bulleted_list_item', {}).get('rich_text', []))
            result = f"{indent}- {content}" if content else ""
        
            # Получаем дочерние блоки
            if block.get('has_children'):
                children = self._fetch_child_blocks(block.get('id'))
                for child in children:
                    child_markdown = self._block_to_markdown(child, indent_level + 1, is_nested=True)
                    if child_markdown:
                        result += "\n" + child_markdown
                    # Обновляем прогресс только если эти блоки не были учтены
                    if not is_nested:
                        self._update_progress(1)
        
            return result
    
        elif block_type == 'numbered_list_item':
            content = self._rich_text_to_markdown(block.get('numbered_list_item', {}).get('rich_text', []))
            result = f"{indent}1. {content}" if content else ""
        
            # Проверяем дочерние блоки
            if block.get('has_children'):
                children = self._fetch_child_blocks(block.get('id'))
                for child in children:
                    child_markdown = self._block_to_markdown(child, indent_level + 1, is_nested=True)
                    if child_markdown:
                        result += "\n" + child_markdown
                    if not is_nested:
                        self._update_progress(1)
        
            return result
    
        elif block_type == 'to_do':
            todo = block.get('to_do', {})
            checked = '[x]' if todo.get('checked') else '[ ]'
            content = self._rich_text_to_markdown(todo.get('rich_text', []))
            result = f"{indent}- {checked} {content}"
        
            # Проверяем дочерние блоки
            if block.get('has_children'):
                children = self._fetch_child_blocks(block.get('id'))
                for child in children:
                    child_markdown = self._block_to_markdown(child, indent_level + 1, is_nested=True)
                    if child_markdown:
                        result += "\n" + child_markdown
                    if not is_nested:
                        self._update_progress(1)
        
            return result
    
        elif block_type == 'toggle':
            content = self._rich_text_to_markdown(block.get('toggle', {}).get('rich_text', []))
            result = f"{indent}▶ {content}"
        
            # Получаем дочерние блоки для toggle
            if block.get('has_children'):
                children = self._fetch_child_blocks(block.get('id'))
                for child in children:
                    child_markdown = self._block_to_markdown(child, indent_level + 1, is_nested=True)
                    if child_markdown:
                        result += "\n" + child_markdown
                    if not is_nested:
                        self._update_progress(1)
        
            return result
    
        elif block_type == 'code':
            code_block = block.get('code', {})
            language = code_block.get('language', '')
            content = self._rich_text_to_markdown(code_block.get('rich_text', []))
            return f"{indent}```{language}\n{content}\n{indent}```"
    
        elif block_type == 'quote':
            content = self._rich_text_to_markdown(block.get('quote', {}).get('rich_text', []))
            result = f"{indent}> {content}"
        
            # Quote тоже может иметь дочерние блоки
            if block.get('has_children'):
                children = self._fetch_child_blocks(block.get('id'))
                for child in children:
                    child_markdown = self._block_to_markdown(child, indent_level + 1, is_nested=True)
                    if child_markdown:
                        result += "\n" + child_markdown
                    if not is_nested:
                        self._update_progress(1)
        
            return result
    
        elif block_type == 'callout':
            callout = block.get('callout', {})
            icon = callout.get('icon', {}).get('emoji', '💡')
            content = self._rich_text_to_markdown(callout.get('rich_text', []))
            result = f"{indent}> {icon} {content}"
        
            # Callout может иметь дочерние блоки
            if block.get('has_children'):
                children = self._fetch_child_blocks(block.get('id'))
                for child in children:
                    child_markdown = self._block_to_markdown(child, indent_level + 1, is_nested=True)
                    if child_markdown:
                        result += "\n" + child_markdown
                    if not is_nested:
                        self._update_progress(1)
        
            return result
    
        elif block_type == 'divider':
            return f"{indent}---"
    
        elif block_type == 'table':
            return self._table_to_markdown(block, indent_level)
    
        elif block_type == 'image':
            image = block.get('image', {})
            url = ''
            if 'external' in image:
                url = image['external'].get('url', '')
            elif 'file' in image:
                url = image['file'].get('url', '')
        
            caption = self._rich_text_to_markdown(image.get('caption', []))
            if url:
                result = f"{indent}![{caption or 'Image'}]({url})"
                if caption:
                    result += f"\n{indent}*{caption}*"
                return result
    
        elif block_type == 'video':
            video = block.get('video', {})
            url = ''
            if 'external' in video:
                url = video['external'].get('url', '')
            elif 'file' in video:
                url = video['file'].get('url', '')
        
            if url:
                return f"{indent}[Video]({url})"
    
        elif block_type == 'file':
            file = block.get('file', {})
            url = ''
            if 'external' in file:
                url = file['external'].get('url', '')
            elif 'file' in file:
                url = file['file'].get('url', '')
        
            caption = self._rich_text_to_markdown(file.get('caption', []))
            if url:
                return f"{indent}[{caption or 'File'}]({url})"
    
        elif block_type == 'bookmark':
            bookmark = block.get('bookmark', {})
            url = bookmark.get('url', '')
            caption = self._rich_text_to_markdown(bookmark.get('caption', []))
        
            if url:
                return f"{indent}[{caption or url}]({url})"
    
        elif block_type == 'embed':
            embed = block.get('embed', {})
            url = embed.get('url', '')
            if url:
                return f"{indent}[Embed]({url})"
    
        elif block_type == 'child_page':
            # В Buildin API заголовок дочерней страницы находится в data.title
            child_data = block.get('data') or {}
            title = child_data.get('title', 'Untitled') if child_data else 'Untitled'
            child_id = block.get('id', '')
        
            # Опционально получаем содержимое дочерней страницы
            fetch_child_content = self.auth_config.get('fetch_child_pages', False)
            max_depth = self.auth_config.get('max_depth', 1)
        
            if fetch_child_content and indent_level < max_depth and child_id:
                try:
                    # Получаем информацию о дочерней странице
                    child_response = self.session.get(f"{self.base_url}/pages/{child_id}")
                    if child_response.status_code == 200:
                        child_page_data = child_response.json()
                        
                        # Проверяем что получили валидные данные
                        if not child_page_data:
                            logger.warning(f"Empty response for child page {child_id}")
                            return f"{indent}- **{title}**"
                        
                        # Безопасно извлекаем заголовок
                        if isinstance(child_page_data, dict):
                            child_title = self._extract_title(child_page_data)
                        else:
                            child_title = title
                    
                        # Добавляем заголовок дочерней страницы
                        result = f"{indent}### 📄 {child_title}\n\n"
                    
                        # Получаем свойства дочерней страницы с проверкой
                        if isinstance(child_page_data, dict):
                            child_properties = child_page_data.get('properties') or {}
                            child_props = self._properties_to_markdown(child_properties)
                            if child_props:
                                result += f"{indent}{child_props}\n"
                    
                        # Получаем первые несколько блоков для preview
                        preview_response = self.session.get(
                            f"{self.base_url}/blocks/{child_id}/children",
                            params={'page_size': 5}
                        )
                        if preview_response.status_code == 200:
                            preview_data = preview_response.json()
                            
                            # Проверяем валидность preview_data
                            if isinstance(preview_data, dict):
                                preview_blocks = preview_data.get('results', [])
                            
                                for preview_block in preview_blocks:
                                    # Рекурсивно обрабатываем блоки дочерней страницы
                                    if preview_block.get('type') != 'child_page':  # Избегаем бесконечной рекурсии
                                        preview_markdown = self._block_to_markdown(preview_block, indent_level + 1, is_nested=True)
                                        if preview_markdown:
                                            result += preview_markdown + "\n"
                                    if not is_nested:
                                        self._update_progress(1)
                            
                                if preview_data.get('has_more'):
                                    result += f"{indent}  *...больше контента в дочерней странице...*\n"
                    
                        return result + "\n"
                    else:
                        logger.warning(f"Failed to fetch child page {child_id}: status {child_response.status_code}")
                        return f"{indent}- **{title}**"
                        
                except Exception as e:
                    logger.error(f"Error fetching child page content for {child_id}: {e}")
                    logger.debug(f"Block data: {block}")
                    return f"{indent}- **{title}**"
        
            # Если не загружаем содержимое, просто добавляем заголовок как список
            return f"{indent}- **{title}**"
    
        elif block_type == 'table_row':
            # Этот тип обрабатывается в _table_to_markdown
            return ""
    
        return ""   
    def _fetch_child_blocks(self, block_id: str) -> list:
        """Получить дочерние блоки"""
        try:
            response = self.session.get(f"{self.base_url}/blocks/{block_id}/children")
            if response.status_code == 200:
                data = response.json()
                return data.get('results', [])
        except Exception as e:
            logger.warning(f"Failed to fetch child blocks for {block_id}: {e}")
        return []
    
    def _table_to_markdown(self, block: Dict, indent_level: int = 0) -> str:
        """Конвертировать таблицу в Markdown"""
        table_id = block.get('id')
        if not table_id:
            return ""
        
        indent = "  " * indent_level
        
        # Получаем строки таблицы
        response = self.session.get(f"{self.base_url}/blocks/{table_id}/children")
        if response.status_code != 200:
            return ""
        
        rows_data = response.json()
        rows = rows_data.get('results', [])
        
        if not rows:
            return ""
        
        markdown = ""
        
        for i, row in enumerate(rows):
            if row.get('type') == 'table_row':
                cells = row.get('table_row', {}).get('cells', [])
                
                # Формируем строку таблицы
                row_content = []
                for cell in cells:
                    content = self._rich_text_to_markdown(cell)
                    row_content.append(content)
                
                markdown += f"{indent}| " + " | ".join(row_content) + " |\n"
                
                # После первой строки добавляем разделитель
                if i == 0:
                    separator = ["-" * max(len(cell), 3) for cell in row_content]
                    markdown += f"{indent}| " + " | ".join(separator) + " |\n"
            
            self._update_progress(1)
        
        return markdown
    
    def _rich_text_to_markdown(self, rich_text_array) -> str:
        """Конвертировать rich text в Markdown"""
        if not rich_text_array:
            return ""
        
        markdown = ""
        
        for item in rich_text_array:
            if 'text' in item:
                content = item['text'].get('content', '')
                link = item['text'].get('link')
                
                # Применяем аннотации
                annotations = item.get('annotations', {})
                
                if annotations.get('bold'):
                    content = f"**{content}**"
                if annotations.get('italic'):
                    content = f"*{content}*"
                if annotations.get('strikethrough'):
                    content = f"~~{content}~~"
                if annotations.get('code'):
                    content = f"`{content}`"
                
                # Ссылка
                if link:
                    url = link.get('url', '')
                    content = f"[{content}]({url})"
                
                markdown += content
            
            elif 'mention' in item:
                mention = item['mention']
                mention_type = mention.get('type')
                
                if mention_type == 'page':
                    page_id = mention.get('page', {}).get('id', '')
                    markdown += f"[Page Reference](#{page_id})"
                elif mention_type == 'database':
                    db_id = mention.get('database', {}).get('id', '')
                    markdown += f"[Database Reference](#{db_id})"
                elif mention_type == 'user':
                    user = mention.get('user', {})
                    name = user.get('name', 'User')
                    markdown += f"@{name}"
                elif mention_type == 'date':
                    date = mention.get('date', {})
                    start = date.get('start', '')
                    markdown += f"{start}"
            
            elif 'equation' in item:
                expression = item['equation'].get('expression', '')
                markdown += f"${expression}$"
        
        return markdown
    
    def check_for_updates(self, url: str, last_modified: Optional[datetime]) -> bool:
        """Проверить обновления страницы"""
        if not last_modified:
            return True
    
        try:
            from datetime import timezone
        
            page_id = self.extract_page_id(url)
        
            # Получаем информацию о странице
            response = self.session.get(f"{self.base_url}/pages/{page_id}")
        
            if response.status_code == 200:
                page_data = response.json()
                last_edited_time_str = page_data.get('last_edited_time')
            
                if last_edited_time_str:
                    # Парсим время из ISO формата
                    last_edited_time = datetime.fromisoformat(
                        last_edited_time_str.replace('Z', '+00:00')
                    )
                
                    # Нормализуем last_modified
                    if isinstance(last_modified, str):
                        last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                
                    if last_modified.tzinfo is None:
                        last_modified = last_modified.replace(tzinfo=timezone.utc)
                    if last_edited_time.tzinfo is None:
                        last_edited_time = last_edited_time.replace(tzinfo=timezone.utc)
                
                    return last_edited_time > last_modified
        except Exception as e:
            logger.error(f"Error checking updates for {url}: {e}")
            return True
    
        return False