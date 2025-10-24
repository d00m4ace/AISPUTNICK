# doc_sync/doc_sync.py
"""
Document Synchronization Utility
Синхронизация документов из различных источников
"""

import json
import os
import re
import sys
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
import tempfile
import shutil

from hotfix_copy import process_files
from trim_files import trim_text_files

# Вместо fcntl используем filelock для кроссплатформенности
try:
    from filelock import FileLock
except ImportError:
    print("Please install filelock: pip install filelock")
    sys.exit(1)


from providers.google_docs import GoogleDocsProvider
from providers.google_drive import GoogleDriveProvider
from providers.yandex_wiki import YandexWikiProvider
from providers.buildin_ai import BuildinProvider
from providers.confluence import ConfluenceProvider
from providers.google_drive_list import GoogleDriveListProvider
from providers.yandex_disk import YandexDiskProvider
from providers.yandex_disk_list import YandexDiskListProvider
from converters import HTMLToMarkdownConverter

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DocumentSync:
    """Основной класс для синхронизации документов"""
    
    PROVIDERS = {
        'google_gdrive': GoogleDriveProvider,
        'google_gdrive_list': GoogleDriveListProvider,
        'google_docs': GoogleDocsProvider,
        'yandex_wiki': YandexWikiProvider,
        'yandex_disk': YandexDiskProvider,
        'yandex_disk_list': YandexDiskListProvider,  
        'buildin': BuildinProvider,
        'confluence': ConfluenceProvider  
    }

    def _normalize_datetime(self, dt_value):
        """Нормализовать datetime значение к aware UTC datetime"""
        from datetime import timezone
    
        if dt_value is None:
            return None
        
        # Если это строка, парсим
        if isinstance(dt_value, str):
            # Обрабатываем разные форматы
            if 'Z' in dt_value:
                dt_value = datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
            elif '+' in dt_value or 'T' in dt_value:
                dt_value = datetime.fromisoformat(dt_value)
            else:
                # Простая дата без timezone
                try:
                    dt_value = datetime.fromisoformat(dt_value)
                except:
                    # Попробуем другой формат
                    dt_value = datetime.strptime(dt_value, '%Y-%m-%d %H:%M:%S')
    
        # Если datetime без timezone, добавляем UTC
        if isinstance(dt_value, datetime) and dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=timezone.utc)
    
        return dt_value
    
    def __init__(self, config_path: str = 'config.json'):
        self.config_path = config_path
        self.load_config()
        self.converter = HTMLToMarkdownConverter()
        self.providers_cache = {}
    
        # Базовый путь к хранилищу
        self.storage_base_path = Path(self.config.get('storage_path', 'local_pages'))
    
        # Создаем структуру директорий если их нет
        self.storage_base_path.mkdir(exist_ok=True)
        md_files_path = self.storage_base_path / self.storage_config['pages_dir']
        md_files_path.mkdir(exist_ok=True)
    
        # Инициализируем файлы если их нет
        self._init_storage_files()
    
    def generate_page_id(self, url: str, provider: str) -> str:
        """Генерировать уникальный ID для страницы на основе URL"""
        import hashlib
        from urllib.parse import urlparse
    
        # Парсим URL
        parsed = urlparse(url)
    
        # Определяем префикс по провайдеру или домену
        if 'wiki.yandex' in parsed.netloc:
            prefix = 'wiki'
        elif 'docs.google.com' in parsed.netloc:
            if 'spreadsheets' in url:
                prefix = 'sheet'
            elif 'document' in url:
                prefix = 'doc'
            elif 'presentation' in url:
                prefix = 'slide'
            else:
                prefix = 'gdoc'
        elif 'drive.google.com' in parsed.netloc:
            prefix = 'drive'
        elif 'buildin.ai' in parsed.netloc or 'buildin.ai' in url:
            prefix = 'buildin'
        elif 'atlassian.net' in parsed.netloc or 'confluence' in parsed.netloc:
            prefix = 'conf'
        elif 'notion.so' in parsed.netloc:
            prefix = 'notion'
        elif 'github.com' in parsed.netloc:
            prefix = 'gh'
        elif 'gitlab' in parsed.netloc:
            prefix = 'gl'
        else:
            # Используем первые буквы домена или провайдера
            domain_parts = parsed.netloc.replace('www.', '').split('.')
            if domain_parts:
                prefix = domain_parts[0][:4]
            else:
                prefix = provider[:4]
    
        # Генерируем уникальный хэш на основе URL
        # Используем SHA256 и берем первые символы
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    
        # Формируем ID: префикс_первые6символов_последние6символов
        # Это дает хорошую уникальность и читаемость
        page_id = f"{prefix}_{url_hash[:6]}_{url_hash[6:12]}"
    
        # Убеждаемся, что ID валидный (только буквы, цифры, подчеркивания)
        page_id = re.sub(r'[^a-zA-Z0-9_-]', '_', page_id)
    
        return page_id.lower()

    def _check_id_uniqueness(self, generated_id: str) -> str:
        """Проверить уникальность ID и добавить суффикс если нужно"""
        local_data = self.load_local_data()
        existing_ids = set(local_data.get('pages', {}).keys())
    
        # Также проверяем в текущем списке страниц
        pages = self.load_pages_list()
        for page in pages:
            if page.get('id'):
                existing_ids.add(page['id'])
    
        # Если ID уже существует, добавляем числовой суффикс
        if generated_id in existing_ids:
            counter = 1
            while f"{generated_id}_{counter}" in existing_ids:
                counter += 1
            return f"{generated_id}_{counter}"
    
        return generated_id

    def load_config(self):
        """Загрузить конфигурацию"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
        
        self.sync_interval = self.config['sync_interval_seconds']
        self.auth_configs = self.config['auth_configs']
        self.provider_configs = self.config['providers']
        self.storage_config = self.config['storage']
    
    def _init_storage_files(self):
        """Инициализировать файлы хранилища если их нет"""
        pages_list_path = self.storage_base_path / self.storage_config['pages_list_file']
        local_data_path = self.storage_base_path / self.storage_config['local_data_file']
    
        if not pages_list_path.exists():
            with open(pages_list_path, 'w', encoding='utf-8') as f:
                json.dump({'pages': []}, f, indent=2, ensure_ascii=False)
    
        if not local_data_path.exists():
            with open(local_data_path, 'w', encoding='utf-8') as f:
                json.dump({'pages': {}}, f, indent=2, ensure_ascii=False)
    
    def get_provider(self, provider_name: str, auth_config_name: str):
        """Получить или создать провайдера"""
        cache_key = f"{provider_name}_{auth_config_name}"
        
        if cache_key not in self.providers_cache:
            if provider_name not in self.PROVIDERS:
                raise ValueError(f"Unknown provider: {provider_name}")
            
            if auth_config_name not in self.auth_configs:
                raise ValueError(f"Unknown auth config: {auth_config_name}")
            
            provider_class = self.PROVIDERS[provider_name]
            auth_config = self.auth_configs[auth_config_name]
            
            self.providers_cache[cache_key] = provider_class(auth_config)
        
        return self.providers_cache[cache_key]
    

    def load_pages_list(self) -> List[Dict]:
        """Загрузить список страниц с блокировкой файла"""
        pages_list_path = self.storage_base_path / self.storage_config['pages_list_file']
        lock_path = str(pages_list_path) + '.lock'
    
        with FileLock(lock_path, timeout=10):
            with open(pages_list_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('pages', [])

    def load_local_data(self) -> Dict:
        """Загрузить данные о локальных страницах"""
        local_data_path = self.storage_base_path / self.storage_config['local_data_file']
        lock_path = str(local_data_path) + '.lock'
    
        with FileLock(lock_path, timeout=10):
            with open(local_data_path, 'r', encoding='utf-8') as f:
                return json.load(f)

    def save_local_data(self, data: Dict):
        """Сохранить данные о локальных страницах"""
        local_data_path = self.storage_base_path / self.storage_config['local_data_file']
        lock_path = str(local_data_path) + '.lock'
    
        with FileLock(lock_path, timeout=10):
            # Создаем временный файл в той же директории
            temp_fd, temp_path = tempfile.mkstemp(
                dir=str(self.storage_base_path),
                prefix='local_data_',
                suffix='.tmp'
            )
        
            try:
                # Записываем данные во временный файл
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            
                # Перемещаем временный файл на место основного
                shutil.move(temp_path, str(local_data_path))
            except:
                # Удаляем временный файл в случае ошибки
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
   
    def _update_page_id_in_config(self, url: str, new_id: str):
        """Обновить ID страницы в конфигурационном файле"""
        pages_list_path = self.storage_base_path / self.storage_config['pages_list_file']
        lock_path = str(pages_list_path) + '.lock'
    
        with FileLock(lock_path, timeout=10):
            # Читаем текущий конфиг
            with open(pages_list_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        
            # Обновляем ID для соответствующей страницы
            for page in data.get('pages', []):
                if page.get('url') == url and (not page.get('id') or page['id'] == ""):
                    page['id'] = new_id
                    break
        
            # Сохраняем обратно
            temp_fd, temp_path = tempfile.mkstemp(
                dir=str(self.storage_base_path),
                prefix='pages_list_',
                suffix='.tmp'
            )
        
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            
                shutil.move(temp_path, str(pages_list_path))
            except:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

    def process_page(self, page_config: Dict, force_update: bool = False) -> bool:
        """
        Process a single page with support for JSON export
        Returns: True if page was updated
        """
        # Generate ID if empty
        if not page_config.get('id') or page_config['id'] == "":
            generated_id = self.generate_page_id(
                page_config['url'], 
                page_config['provider']
            )
            page_config['id'] = self._check_id_uniqueness(generated_id)
            logger.info(f"Generated ID for page: {page_config['id']}")
            self._update_page_id_in_config(page_config['url'], page_config['id'])

        if not page_config.get('enabled', True):
            logger.info(f"Skipping disabled page: {page_config['id']}")
            return False

        page_id = page_config['id']
        url = page_config['url']
        provider_name = page_config['provider']
        auth_config_name = page_config['auth_config']

        # Check export format for Google Sheets
        export_format = page_config.get('export_format')
        if not export_format:
            # Check global config for default format
            export_format = self.config.get('export_formats', {}).get('google_sheets', {}).get('default_format', 'markdown')

        logger.info(f"Processing page: {page_id} (format: {export_format})")

        try:
            # Get provider with export config if it's Google Docs
            if provider_name == 'google_docs':
                # Pass export configuration to provider
                provider = self._get_google_docs_provider_with_config(auth_config_name, export_format)

            elif provider_name == 'google_gdrive_list':
                    # Передаем конфигурацию страницы в auth_config для этого провайдера
                    enhanced_auth_config = self.auth_configs[auth_config_name].copy()
        
                    # Добавляем параметры из page_config
                    enhanced_auth_config.update({
                        'description': page_config.get('description', ''),
                        'skip_file_patterns': page_config.get('skip_file_patterns', []),
                        'skip_folder_patterns': page_config.get('skip_folder_patterns', []),
                        'include_folders': page_config.get('include_folders', True),
                        'include_file_types': page_config.get('include_file_types', True),
                        'include_modified_date': page_config.get('include_modified_date', True),
                        'include_size': page_config.get('include_size', True),
                        'sort_by': page_config.get('sort_by', 'name'),
                        'group_by_directory': page_config.get('group_by_directory', True)
                    })
        
                    provider = self.PROVIDERS[provider_name](enhanced_auth_config)
            else:
                    provider = self.get_provider(provider_name, auth_config_name)

            # Load current local data
            local_data = self.load_local_data()
            page_data = local_data.get('pages', {}).get(page_id, {})

            # Check for updates if needed
            force_update = getattr(self, 'force_update', False)

            if not force_update and page_config.get('check_updates', True) and page_data:
                last_modified_str = page_data.get('last_modified')
                if last_modified_str:
                    try:
                        last_modified = self._normalize_datetime(last_modified_str)
                        if last_modified and not provider.check_for_updates(url, last_modified):
                            logger.info(f"Page {page_id} is up to date")
                            return False
                    except Exception as e:
                        logger.warning(f"Error parsing last_modified date: {e}, will update")
            elif force_update:
                logger.info(f"Force updating page {page_id}")

            # Fetch content with export format
            if provider_name == 'google_docs' and 'spreadsheets' in url:
                content, metadata = provider.fetch_content(url, export_format)
            else:
                content, metadata = provider.fetch_content(url)

            # Determine file extension and processing based on format
            if metadata.get('_is_json'):
                # Content is already JSON
                file_extension = '.json'
                final_content = content
        
                # Optionally save as markdown too
                if self.config.get('export_formats', {}).get('google_sheets', {}).get('save_json_copy', False):
                    # Also save as markdown
                    self._save_markdown_copy(page_id, url, metadata, provider)
            
            elif metadata.get('_is_markdown', False):
                # Content is already in Markdown format
                file_extension = '.md'
                final_content = self._format_markdown_content(content, metadata, url, page_id)
            else:
                # Convert HTML to Markdown
                markdown_content = self.converter.convert(content)
                file_extension = '.md'
                final_content = self._format_markdown_content(markdown_content, metadata, url, page_id)
                logger.info(f"Converted HTML to Markdown for {page_id}")

            # Generate file name with appropriate extension
            file_name = f"{page_id}{file_extension}"
    
            # Determine directory based on file type
            if file_extension == '.json':
                json_dir = self.config.get('export_formats', {}).get('google_sheets', {}).get('json_dir', 'json_files')
                file_dir = self.storage_base_path / json_dir
                file_dir.mkdir(exist_ok=True)
            else:
                file_dir = self.storage_base_path / self.storage_config['pages_dir']
    
            file_path = file_dir / file_name

            # Save file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(final_content)

            # Update local data
            if 'pages' not in local_data:
                local_data['pages'] = {}

            # Извлекаем время модификации из метаданных
            # Приоритет полей для разных провайдеров
            modified_time = (
                metadata.get('modified_time') or      # Стандартное поле (все должны его иметь)
                metadata.get('modifiedTime') or       # Google альтернатива
                metadata.get('last_edited_time') or   # Buildin
                metadata.get('last_modified') or      # Confluence
                metadata.get('modified_at')           # Yandex
            )
        
            # ВАЖНО: НЕ используем datetime.now() как fallback!
            if not modified_time:
                logger.warning(f"No modification time found for {page_id}, document will always be updated on next sync")
                # Можем использовать last_sync из предыдущих данных если есть
                modified_time = page_data.get('last_modified')
        
            # Логируем для отладки
            logger.debug(f"Saving modification time for {page_id}: {modified_time}")

            local_data['pages'][page_id] = {
                'title': metadata.get('title', 'Untitled'),
                'url': url,
                'file_name': file_name,
                'file_path': str(file_path.relative_to(self.storage_base_path)),
                'export_format': export_format if 'spreadsheets' in url else 'markdown',
                'last_modified': modified_time,  # Используем время из источника
                'last_sync': datetime.now().isoformat(),
                'provider': provider_name
            }

            self.save_local_data(local_data)

            logger.info(f"Successfully updated page: {page_id} as {file_extension}")
            if modified_time:
                logger.info(f"  Document modified time: {modified_time}")
            return True

        except Exception as e:
            logger.error(f"Error processing page {page_id}: {e}", exc_info=True)
            return False

    def _get_google_docs_provider_with_config(self, auth_config_name: str, export_format: str):
        """Create Google Docs provider with export configuration"""
        from providers.google_docs import GoogleDocsProvider
    
        if auth_config_name not in self.auth_configs:
            raise ValueError(f"Unknown auth config: {auth_config_name}")
    
        auth_config = self.auth_configs[auth_config_name]
        export_config = self.config.get('export_formats', {})
    
        # Add export format to config
        if 'google_sheets' not in export_config:
            export_config['google_sheets'] = {}
        export_config['google_sheets']['default_format'] = export_format
    
        return GoogleDocsProvider(auth_config, export_config)

    def _format_markdown_content(self, content: str, metadata: Dict, url: str, page_id: str) -> str:
        """Format markdown content with metadata header"""
        formatted = f"# {metadata.get('title', 'Untitled')}\n\n"
        formatted += f"**Source:** {url}\n"
        formatted += f"**Updated:** {datetime.now().isoformat()}\n"
        formatted += f"**Page ID:** {page_id}\n\n"
        formatted += "---\n\n"
        formatted += content
        return formatted

    def _save_markdown_copy(self, page_id: str, url: str, metadata: Dict, provider):
        """Save a markdown copy of a JSON-exported sheet"""
        try:
            # Re-fetch as markdown
            content, _ = provider.fetch_content(url, 'markdown')
        
            if not metadata.get('_is_markdown', False):
                content = self.converter.convert(content)
        
            # Save markdown file
            md_filename = f"{page_id}.md"
            md_path = self.storage_base_path / self.storage_config['pages_dir'] / md_filename
        
            formatted_content = self._format_markdown_content(content, metadata, url, page_id)
        
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(formatted_content)
            
            logger.info(f"Saved markdown copy for {page_id}")
        
        except Exception as e:
            logger.warning(f"Failed to save markdown copy: {e}")
        

    def process_yandex_disk_folder_page(self, page_config: Dict) -> bool:
        """
        Обработать папку Yandex Disk и создать отдельные страницы для каждого файла
        Аналог process_folder_page для Google Drive
        """
        if not page_config.get('enabled', True):
            logger.info(f"Skipping disabled Yandex Disk folder: {page_config.get('url')}")
            return False
    
        url = page_config['url']
        provider_name = page_config['provider']
        auth_config_name = page_config['auth_config']
        folder_page_id = page_config.get('id')
    
        # Проверяем формат экспорта (для будущей поддержки разных форматов)
        export_format = page_config.get('export_format', 'markdown')
    
        logger.info(f"Processing Yandex Disk folder: {url} (export format: {export_format})")
    
        # Статистика обработки
        stats = {
            'total_files': 0,
            'processed_successfully': 0,
            'updated': 0,
            'unchanged': 0,
            'new': 0,
            'failed': 0,
            'skipped': 0,
            'errors': []
        }
    
        try:
            # Получаем провайдера
            provider = self.get_provider(provider_name, auth_config_name)
        
            # Загружаем текущие локальные данные
            local_data = self.load_local_data()
        
            # Создаем индекс существующих файлов по Yandex Disk path
            existing_files_index = {}
            if 'pages' in local_data:
                for page_id, page_data in local_data['pages'].items():
                    ydisk_path = page_data.get('ydisk_file_path')
                    if ydisk_path:
                        existing_files_index[ydisk_path] = {
                            'page_id': page_id,
                            'page_data': page_data
                        }
        
            # Получаем список файлов в папке
            folder_path = provider.extract_folder_path(url)
        
            # Получаем информацию о папке
            folder_info = provider._get_resource_info(folder_path)
            folder_name = folder_info.get('name', 'Yandex Disk Folder')
        
            # Получаем список файлов
            files_list = provider.get_folder_files_list(folder_path)
            stats['total_files'] = len(files_list)
        
            logger.info(f"Found {len(files_list)} files in Yandex Disk folder: {folder_name}")
        
            # Обрабатываем каждый файл
            for i, file_info in enumerate(files_list, 1):
                try:
                    file_path = file_info.get('path', '')
                    file_name = file_info['name']
                    mime_type = file_info.get('mime_type', 'unknown')
                    modified_time = file_info.get('modified')
                    file_size = file_info.get('size', 0)
                
                    logger.info(f"Processing file {i}/{len(files_list)}: {file_name}")
                
                    # Проверяем существует ли файл в локальной базе
                    existing_entry = existing_files_index.get(file_path)
                
                    needs_processing = False
                    file_page_id = None
                
                    if existing_entry:
                        # Файл уже существует
                        file_page_id = existing_entry['page_id']
                        existing_data = existing_entry['page_data']
                        stats['unchanged'] += 1
                    
                        # Проверяем нужно ли обновление
                        if page_config.get('check_updates', True) and modified_time:
                            last_sync = existing_data.get('ydisk_modified_time')
                        
                            if last_sync and modified_time:
                                try:
                                    # Преобразуем в datetime для сравнения
                                    from datetime import timezone
                                
                                    if isinstance(last_sync, str):
                                        last_sync_dt = datetime.fromisoformat(last_sync.replace('Z', '+00:00'))
                                    else:
                                        last_sync_dt = last_sync
                                
                                    if isinstance(modified_time, str):
                                        modified_dt = datetime.fromisoformat(modified_time.replace('Z', '+00:00'))
                                    else:
                                        modified_dt = modified_time
                                
                                    # Добавляем timezone если нет
                                    if last_sync_dt.tzinfo is None:
                                        last_sync_dt = last_sync_dt.replace(tzinfo=timezone.utc)
                                    if modified_dt.tzinfo is None:
                                        modified_dt = modified_dt.replace(tzinfo=timezone.utc)
                                
                                    # Сравниваем
                                    if modified_dt > last_sync_dt:
                                        needs_processing = True
                                        logger.info(f"File {file_name} was modified, will update")
                                        stats['updated'] += 1
                                        stats['unchanged'] -= 1
                                    else:
                                        logger.debug(f"File {file_name} is unchanged, skipping")
                                        continue
                                    
                                except Exception as e:
                                    logger.warning(f"Error comparing dates: {e}, will update file")
                                    needs_processing = True
                            else:
                                # Если нет last_sync, обновляем
                                needs_processing = True
                    else:
                        # Новый файл
                        needs_processing = True
                        stats['new'] += 1
                        logger.info(f"New file found: {file_name}")
                    
                        # Генерируем новый ID для файла
                        # Используем хеш от пути файла для уникальности
                        import hashlib
                        path_hash = hashlib.md5(file_path.encode()).hexdigest()[:12]
                        file_page_id = f"ydisk_{path_hash}"
                    
                        # Проверяем уникальность ID
                        if file_page_id in local_data.get('pages', {}):
                            # Если существует, добавляем счетчик
                            counter = 1
                            while f"{file_page_id}_{counter}" in local_data.get('pages', {}):
                                counter += 1
                            file_page_id = f"{file_page_id}_{counter}"
                
                    if needs_processing:
                        # Загружаем и обрабатываем файл
                        logger.info(f"Processing file: {file_name}")
                    
                        try:
                            # Получаем контент файла
                            file_metadata, file_content = provider.process_single_file(file_info)
                        
                            if file_content and file_content.strip() and not file_content.startswith('*Error:'):
                                # Определяем директорию для сохранения
                                file_extension = '.md'
                                file_dir = self.storage_base_path / self.storage_config['pages_dir']
                            
                                # Генерируем имя файла
                                file_filename = f"{file_page_id}{file_extension}"
                                file_filepath = file_dir / file_filename
                            
                                # Формируем содержимое
                                final_content = f"# {file_name}\n\n"
                                final_content += f"**Source:** Yandex Disk\n"
                                final_content += f"**Path:** {file_path}\n"
                            
                                # Добавляем URL если есть
                                if file_info.get('public_url'):
                                    final_content += f"**Public URL:** {file_info['public_url']}\n"
                            
                                final_content += f"**MIME Type:** {mime_type}\n"
                                final_content += f"**Size:** {self._format_file_size(file_size)}\n"
                                final_content += f"**Modified on Disk:** {modified_time}\n"
                                final_content += f"**Last Sync:** {datetime.now().isoformat()}\n\n"
                                final_content += "---\n\n"
                                final_content += file_content
                            
                                # Сохраняем файл
                                with open(file_filepath, 'w', encoding='utf-8') as f:
                                    f.write(final_content)
                            
                                # Обновляем локальные данные
                                if 'pages' not in local_data:
                                    local_data['pages'] = {}
                            
                                # Определяем URL для файла
                                file_url = file_info.get('public_url')
                                if not file_url:
                                    # Генерируем URL для веб-интерфейса
                                    if file_info.get('full_path'):
                                        from urllib.parse import quote
                                        encoded_path = quote(file_info['full_path'], safe='')
                                        file_url = f"https://disk.yandex.ru/client/disk?dialog=slider&idDialog=%2Fdisk{encoded_path}"
                                    else:
                                        file_url = url  # Fallback к URL папки
                            
                                local_data['pages'][file_page_id] = {
                                    'title': file_name,
                                    'url': file_url,
                                    'ydisk_file_path': file_path,
                                    'ydisk_modified_time': modified_time,
                                    'file_name': file_filename,
                                    'file_path': str(file_filepath.relative_to(self.storage_base_path)),
                                    'export_format': export_format,
                                    'mime_type': mime_type,
                                    'file_size': file_size,
                                    'last_sync': datetime.now().isoformat(),
                                    'provider': provider_name,
                                    'parent_folder': folder_page_id,
                                    'folder_url': url,
                                    'path_in_folder': file_path
                                }
                            
                                stats['processed_successfully'] += 1
                            
                            else:
                                # Если контент с ошибкой
                                if file_content and file_content.startswith('*Error:'):
                                    logger.warning(f"Error content for file: {file_name}")
                                stats['failed'] += 1
                            
                        except Exception as e:
                            logger.error(f"Error processing file {file_name}: {e}")
                            stats['failed'] += 1
                            stats['errors'].append({
                                'file': file_name,
                                'error': str(e)
                            })
                            continue
                        
                except Exception as e:
                    stats['failed'] += 1
                    stats['errors'].append({
                        'file': file_info.get('name', 'Unknown'),
                        'error': str(e)
                    })
                    logger.error(f"Error processing file entry: {e}")
                    continue
        
            # Генерируем ID для папки если его нет
            if not folder_page_id:
                folder_hash = hashlib.md5(folder_path.encode()).hexdigest()[:12]
                folder_page_id = f"ydisk_folder_{folder_hash}"
                page_config['id'] = folder_page_id
                self._update_page_id_in_config(url, folder_page_id)
        
            # Создаем сводную страницу папки
            folder_file_name = f"{folder_page_id}.md"
            folder_file_path = self.storage_base_path / self.storage_config['pages_dir'] / folder_file_name
        
            # Формируем содержимое сводной страницы
            folder_content = f"# [Folder] {folder_name}\n\n"
            folder_content += f"**Type:** Yandex Disk Folder\n"
            folder_content += f"**URL:** {url}\n"
            folder_content += f"**Path:** {folder_path}\n"
            folder_content += f"**Export Format:** {export_format}\n"
            folder_content += f"**Last Sync:** {datetime.now().isoformat()}\n\n"
            folder_content += "## Statistics\n\n"
            folder_content += f"- **Total Files:** {stats['total_files']}\n"
            folder_content += f"- **Successfully Processed:** {stats['processed_successfully']}\n"
            folder_content += f"- **New:** {stats['new']}\n"
            folder_content += f"- **Updated:** {stats['updated']}\n"
            folder_content += f"- **Unchanged:** {stats['unchanged']}\n"
            folder_content += f"- **Failed:** {stats['failed']}\n\n"
        
            if stats['errors']:
                folder_content += "## Errors\n\n"
                for error in stats['errors'][:10]:  # Показываем первые 10 ошибок
                    folder_content += f"- **{error['file']}**: {error['error']}\n"
                if len(stats['errors']) > 10:
                    folder_content += f"\n*...and {len(stats['errors']) - 10} more errors*\n"
        
            # Добавляем список обработанных файлов
            if 'pages' in local_data:
                folder_files = [
                    (page_id, page_data) 
                    for page_id, page_data in local_data['pages'].items() 
                    if page_data.get('parent_folder') == folder_page_id
                ]
            
                if folder_files:
                    folder_content += "\n## Processed Files\n\n"
                    for page_id, page_data in sorted(folder_files, key=lambda x: x[1].get('title', '')):
                        file_title = page_data.get('title', 'Untitled')
                        file_size = page_data.get('file_size', 0)
                        folder_content += f"- [{file_title}]({page_data.get('url', '#')}) "
                        folder_content += f"({self._format_file_size(file_size)})\n"
        
            # Сохраняем сводную страницу
            with open(folder_file_path, 'w', encoding='utf-8') as f:
                f.write(folder_content)
        
            # Обновляем запись о папке в local_data
            local_data['pages'][folder_page_id] = {
                'title': f"[Folder] {folder_name}",
                'url': url,
                'ydisk_folder_path': folder_path,
                'file_name': folder_file_name,
                'export_format': export_format,
                'last_sync': datetime.now().isoformat(),
                'provider': provider_name,
                'is_folder': True,
                'files_count': stats['total_files'],
                'stats': stats
            }
        
            # Сохраняем обновленные данные
            self.save_local_data(local_data)
        
            # Логируем итоговую статистику
            logger.info(
                f"Yandex Disk folder sync complete: "
                f"Total: {stats['total_files']}, "
                f"New: {stats['new']}, "
                f"Updated: {stats['updated']}, "
                f"Unchanged: {stats['unchanged']}, "
                f"Failed: {stats['failed']}"
            )
        
            # Добавляем задержку между обработкой файлов если настроена
            if provider_name in self.provider_configs:
                import time
                delay = self.provider_configs[provider_name].get('request_delay_seconds', 1)
                if delay > 0:
                    time.sleep(delay)
        
            return True
        
        except Exception as e:
            logger.error(f"Error processing Yandex Disk folder {url}: {e}", exc_info=True)
            return False

    def _format_file_size(self, size_bytes: int) -> str:
        """Форматировать размер файла (вспомогательный метод)"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    def sync_all_pages(self):
        """Синхронизировать все страницы"""
        pages = self.load_pages_list()
    
        if not pages:
            logger.warning("No pages to sync")
            return
    
        logger.info(f"Starting sync of {len(pages)} pages")
    
        updated_count = 0
        for page_config in pages:
            # Проверяем тип провайдера
            provider = page_config.get('provider')
        
            if provider == 'google_gdrive':
                # Обработка папки Google Drive
                if self.process_folder_page(page_config):
                    updated_count += 1
                
            elif provider == 'yandex_disk':
                # Обработка папки Yandex Disk (с загрузкой файлов)
                if self.process_yandex_disk_folder_page(page_config):
                    updated_count += 1
                
            elif provider == 'yandex_disk_list':
                # Обработка списка Yandex Disk (только список без загрузки)
                if self.process_page(page_config):
                    updated_count += 1
                
            else:
                # Обработка обычной страницы
                if self.process_page(page_config):
                    updated_count += 1
        
            # Задержка между запросами для конкретного провайдера
            provider_name = page_config.get('provider')
            if provider_name in self.provider_configs:
                delay = self.provider_configs[provider_name].get('request_delay_seconds', 1)
                time.sleep(delay)
    
        logger.info(f"Sync completed. Updated {updated_count} pages")

    def run_continuous(self):
        """Запустить непрерывную синхронизацию"""
        logger.info("Starting continuous sync")
        
        while True:
            try:
                self.sync_all_pages()

                txt_folder = self.storage_base_path / self.storage_config['hotfix_dir']
                md_folder = self.storage_base_path / self.storage_config['pages_dir']

                folder = md_folder  # Путь к папке
                max_size = 250*1024  # Максимальный размер в байтах (250 KB)

                results = trim_text_files(folder, max_size, ".md")
    
                print("\n=== Итоги обработки ===")
                for filename, (old_size, new_size) in results.items():
                    if old_size > new_size:
                        print(f"{filename}: обрезан с {old_size} до {new_size} байт")
                    else:
                        print(f"{filename}: размер в норме ({old_size} байт)")

                process_files(txt_folder, md_folder)

                logger.info(f"\nWaiting {self.sync_interval} seconds until next sync")
                time.sleep(self.sync_interval)
                
                # Перезагружаем конфигурацию на случай изменений
                self.load_config()
                
            except KeyboardInterrupt:
                logger.info("Sync interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error during sync: {e}")
                time.sleep(60)  # Ждем минуту при ошибке

    def process_folder_page(self, page_config: Dict) -> bool:
        """
        Обработать Google Drive папку и создать отдельные страницы для каждого файла
        с поддержкой JSON экспорта для Google Sheets
        """
        if not page_config.get('enabled', True):
            logger.info(f"Skipping disabled folder: {page_config.get('url')}")
            return False

        url = page_config['url']
        provider_name = page_config['provider']
        auth_config_name = page_config['auth_config']
        folder_page_id = page_config.get('id')

        # Check export format configuration
        export_format = page_config.get('export_format')
        if not export_format:
            export_format = self.config.get('export_formats', {}).get('google_sheets', {}).get('default_format', 'markdown')

        logger.info(f"Processing Google Drive folder: {url} (export format: {export_format})")

        # Статистика обработки
        stats = {
            'total_files': 0,
            'processed_successfully': 0,
            'updated': 0,
            'unchanged': 0,
            'new': 0,
            'failed': 0,
            'retried_429': 0,
            'json_exported': 0,
            'errors': []
        }

        try:
            # Получаем провайдера
            provider = self.get_provider(provider_name, auth_config_name)
        
            # Если нужен JSON экспорт, создаем специального провайдера для Google Sheets
            sheets_provider = None
            if export_format == 'json':
                sheets_provider = self._get_google_docs_provider_with_config(auth_config_name, export_format)
    
            # Загружаем текущие локальные данные
            local_data = self.load_local_data()
    
            # Создаем индекс существующих файлов по Google Drive ID
            existing_files_index = {}
            if 'pages' in local_data:
                for page_id, page_data in local_data['pages'].items():
                    gdrive_id = page_data.get('gdrive_file_id')
                    if gdrive_id:
                        existing_files_index[gdrive_id] = {
                            'page_id': page_id,
                            'page_data': page_data
                        }
    
            # Получаем список файлов в папке
            folder_id = provider.extract_folder_id(url)
            files_list = provider.get_folder_files_list(folder_id)
            stats['total_files'] = len(files_list)
    
            logger.info(f"Found {len(files_list)} files in folder")
    
            # Обрабатываем каждый файл
            for i, file_info in enumerate(files_list, 1):
                try:
                    gdrive_file_id = file_info['id']
                    file_name = file_info['name']
                    file_path = file_info['path']
                    mime_type = file_info.get('mime_type')
                    modified_time = file_info.get('modified_time')
            
                    logger.info(f"Checking file {i}/{len(files_list)}: {file_name}")
            
                    # Проверяем существует ли файл в локальной базе
                    existing_entry = existing_files_index.get(gdrive_file_id)
            
                    needs_processing = False
                    file_page_id = None
                    has_429_error = False
                    previous_format = None
            
                    if existing_entry:
                        # Файл уже существует
                        file_page_id = existing_entry['page_id']
                        existing_data = existing_entry['page_data']
                        previous_format = existing_data.get('export_format', 'markdown')
                
                        # Проверяем изменился ли формат экспорта для таблиц
                        format_changed = False
                        if mime_type == 'application/vnd.google-apps.spreadsheet':
                            current_format = export_format
                            if previous_format != current_format:
                                format_changed = True
                                logger.info(f"Export format changed for {file_name}: {previous_format} -> {current_format}")
                
                        # Проверяем есть ли ошибка 429 в существующем файле
                        existing_file_ext = '.json' if previous_format == 'json' else '.md'
                        existing_file_name = f"{file_page_id}{existing_file_ext}"
                    
                        if previous_format == 'json':
                            json_dir = self.config.get('export_formats', {}).get('google_sheets', {}).get('json_dir', 'json_files')
                            existing_file_path = self.storage_base_path / json_dir / existing_file_name
                        else:
                            existing_file_path = self.storage_base_path / self.storage_config['pages_dir'] / existing_file_name
                    
                        if existing_file_path.exists():
                            try:
                                with open(existing_file_path, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                    # Проверяем наличие ошибки 429
                                    if '*Error: <HttpError 429 when requesting' in content:
                                        has_429_error = True
                                        logger.info(f"File {file_name} has 429 error, will retry")
                                        stats['retried_429'] += 1
                            except Exception as e:
                                logger.warning(f"Could not check existing file for 429 error: {e}")
                
                        # Определяем нужно ли обновление
                        if has_429_error or format_changed:
                            needs_processing = True
                            if format_changed:
                                stats['updated'] += 1
                        elif page_config.get('check_updates', True) and modified_time:
                            last_sync = existing_data.get('gdrive_modified_time')
    
                            # Сравниваем как datetime объекты, а не строки
                            if last_sync and modified_time:
                                try:
                                    # Преобразуем в datetime если это строки
                                    if isinstance(last_sync, str):
                                        last_sync_dt = datetime.fromisoformat(last_sync.replace('Z', '+00:00'))
                                    else:
                                        last_sync_dt = last_sync
                
                                    if isinstance(modified_time, str):
                                        modified_dt = datetime.fromisoformat(modified_time.replace('Z', '+00:00'))
                                    else:
                                        modified_dt = modified_time
            
                                    # Сравниваем с точностью до секунды
                                    if modified_dt.replace(microsecond=0) > last_sync_dt.replace(microsecond=0):
                                        needs_processing = True
                                        logger.info(f"File {file_name} was modified, will update")
                                        stats['updated'] += 1
                                    else:
                                        stats['unchanged'] += 1
                                        logger.debug(f"File {file_name} is unchanged, skipping")
                                        continue
                                except Exception as e:
                                    logger.warning(f"Error comparing dates: {e}, will update file")
                                    needs_processing = True
                            else:
                                # Если нет last_sync, считаем что нужно обновить
                                needs_processing = True
                    else:
                        # Новый файл
                        needs_processing = True
                        stats['new'] += 1
                        logger.info(f"New file found: {file_name}")
                
                        # Генерируем новый ID только для новых файлов
                        file_page_id = f"gdrive_{gdrive_file_id[:12]}"
                
                        # Проверяем что такой ID не существует
                        if file_page_id in local_data.get('pages', {}):
                            # Если существует, добавляем хеш от полного ID
                            import hashlib
                            hash_suffix = hashlib.md5(gdrive_file_id.encode()).hexdigest()[:6]
                            file_page_id = f"gdrive_{gdrive_file_id[:8]}_{hash_suffix}"
            
                    if needs_processing:
                        # Добавляем задержку если это повторная попытка после 429
                        if has_429_error:
                            import time
                            logger.info(f"Waiting 2 seconds before retrying file with 429 error...")
                            time.sleep(2)
                
                        # Загружаем и обрабатываем файл
                        logger.info(f"Processing file: {file_name}")
                
                        try:
                            # Определяем формат экспорта для этого файла
                            file_export_format = 'markdown'
                            file_extension = '.md'
                            file_dir = self.storage_base_path / self.storage_config['pages_dir']
                        
                            if mime_type == 'application/vnd.google-apps.spreadsheet' and export_format == 'json':
                                file_export_format = 'json'
                                file_extension = '.json'
                                json_dir = self.config.get('export_formats', {}).get('google_sheets', {}).get('json_dir', 'json_files')
                                file_dir = self.storage_base_path / json_dir
                                file_dir.mkdir(exist_ok=True, parents=True)
                        
                            # Получаем контент файла
                            if mime_type == 'application/vnd.google-apps.spreadsheet' and file_export_format == 'json':
                                # Используем специальный провайдер для JSON экспорта
                                if sheets_provider:
                                    file_url = f"https://docs.google.com/spreadsheets/d/{gdrive_file_id}"
                                    file_content, file_metadata = sheets_provider.fetch_content(file_url, 'json')
                                    stats['json_exported'] += 1
                                else:
                                    # Fallback к обычному провайдеру
                                    file_metadata, file_content = provider.process_single_file_with_retry(file_info)
                            else:
                                # Обычная обработка для других типов файлов
                                file_metadata, file_content = provider.process_single_file_with_retry(file_info)
                        
                            if file_content and file_content.strip() and not file_content.startswith('*Error:'):
                                # Генерируем имя файла с правильным расширением
                                file_filename = f"{file_page_id}{file_extension}"
                                file_filepath = file_dir / file_filename
                            
                                # Удаляем старый файл если изменился формат
                                if previous_format and previous_format != file_export_format:
                                    old_ext = '.json' if previous_format == 'json' else '.md'
                                    old_filename = f"{file_page_id}{old_ext}"
                                
                                    if previous_format == 'json':
                                        old_dir = self.storage_base_path / self.config.get('export_formats', {}).get('google_sheets', {}).get('json_dir', 'json_files')
                                        old_path = old_dir / old_filename
                                    else:
                                        old_path = self.storage_base_path / self.storage_config['pages_dir'] / old_filename
                                
                                    if old_path.exists():
                                        old_path.unlink()
                                        logger.info(f"Removed old file with {previous_format} format: {old_filename}")
                            
                                # Формируем содержимое в зависимости от формата
                                if file_export_format == 'json':
                                    # Для JSON сохраняем как есть
                                    final_content = file_content
                                else:
                                    # Для Markdown добавляем метаданные
                                    final_content = f"# {file_name}\n\n"
                                    final_content += f"**Source:** Google Drive\n"
                                    final_content += f"**Path:** {file_path}\n"
                                    final_content += f"**File ID:** {gdrive_file_id}\n"
                                    final_content += f"**MIME Type:** {mime_type}\n"
                                    final_content += f"**Modified on Drive:** {modified_time}\n"
                                    final_content += f"**Last Sync:** {datetime.now().isoformat()}\n\n"
                                    final_content += "---\n\n"
                                    final_content += file_content
                        
                                # Сохраняем файл
                                with open(file_filepath, 'w', encoding='utf-8') as f:
                                    f.write(final_content)
                        
                                # Обновляем локальные данные
                                if 'pages' not in local_data:
                                    local_data['pages'] = {}
                        
                                local_data['pages'][file_page_id] = {
                                    'title': file_name,
                                    'url': f"https://drive.google.com/file/d/{gdrive_file_id}",
                                    'gdrive_file_id': gdrive_file_id,
                                    'gdrive_modified_time': modified_time,
                                    'file_name': file_filename,
                                    'file_path': str(file_filepath.relative_to(self.storage_base_path)),
                                    'export_format': file_export_format,
                                    'mime_type': mime_type,
                                    'last_sync': datetime.now().isoformat(),
                                    'provider': provider_name,
                                    'parent_folder': folder_page_id,
                                    'folder_url': url,
                                    'path_in_folder': file_path,
                                    'had_429_error': has_429_error,
                                    'successfully_recovered': has_429_error
                                }
                        
                                stats['processed_successfully'] += 1
                        
                                if has_429_error:
                                    logger.info(f"Successfully recovered file after 429 error: {file_name}")
                            
                                # Опционально сохраняем копию в другом формате
                                if mime_type == 'application/vnd.google-apps.spreadsheet' and self.config.get('export_formats', {}).get('google_sheets', {}).get('save_both_formats', False):
                                    self._save_alternate_format(file_page_id, gdrive_file_id, file_name, file_export_format, sheets_provider, provider, file_info)
                            else:
                                # Если контент все еще с ошибкой, сохраняем как есть
                                if file_content and file_content.startswith('*Error:'):
                                    logger.warning(f"Still got error for file: {file_name}")
                                    stats['failed'] += 1
                        
                        except Exception as e:
                            logger.error(f"Error processing file {file_name}: {e}")
                            stats['failed'] += 1
                            continue
                    
                except Exception as e:
                    stats['failed'] += 1
                    stats['errors'].append({
                        'file': file_info.get('name', 'Unknown'),
                        'error': str(e)
                    })
                    logger.error(f"Error processing file {file_info.get('name')}: {e}")
                    continue
    
            # Генерируем ID для папки если его нет
            if not folder_page_id:
                folder_gdrive_id = provider.extract_folder_id(url)
                folder_page_id = f"gdrive_folder_{folder_gdrive_id[:12]}"
                page_config['id'] = folder_page_id
                self._update_page_id_in_config(url, folder_page_id)
    
            # Создаем сводную страницу папки
            folder_file_name = f"{folder_page_id}.md"
            folder_file_path = self.storage_base_path / self.storage_config['pages_dir'] / folder_file_name
    
            # Формируем содержимое сводной страницы
            folder_content = f"# [Folder] {files_list[0]['path'].split('/')[0] if files_list else 'Google Drive Folder'}\n\n"
            folder_content += f"**Type:** Google Drive Folder\n"
            folder_content += f"**URL:** {url}\n"
            folder_content += f"**Export Format:** {export_format}\n"
            folder_content += f"**Last Sync:** {datetime.now().isoformat()}\n\n"
            folder_content += "## Statistics\n\n"
            folder_content += f"- **Total Files:** {stats['total_files']}\n"
            folder_content += f"- **Successfully Processed:** {stats['processed_successfully']}\n"
            folder_content += f"- **New:** {stats['new']}\n"
            folder_content += f"- **Updated:** {stats['updated']}\n"
            folder_content += f"- **Unchanged:** {stats['unchanged']}\n"
            folder_content += f"- **JSON Exported:** {stats['json_exported']}\n"
            folder_content += f"- **Retried (429 errors):** {stats['retried_429']}\n"
            folder_content += f"- **Failed:** {stats['failed']}\n\n"
    
            # Сохраняем сводную страницу
            with open(folder_file_path, 'w', encoding='utf-8') as f:
                f.write(folder_content)
    
            # Обновляем запись о папке в local_data
            local_data['pages'][folder_page_id] = {
                'title': f"[Folder] {files_list[0]['path'].split('/')[0] if files_list else 'Google Drive Folder'}",
                'url': url,
                'gdrive_folder_id': folder_gdrive_id if 'folder_gdrive_id' in locals() else provider.extract_folder_id(url),
                'file_name': folder_file_name,
                'export_format': export_format,
                'last_sync': datetime.now().isoformat(),
                'provider': provider_name,
                'is_folder': True,
                'files_count': stats['total_files'],
                'stats': stats
            }
    
            # Сохраняем обновленные данные
            self.save_local_data(local_data)
    
            # Логируем итоговую статистику
            logger.info(
                f"Folder sync complete: "
                f"Total: {stats['total_files']}, "
                f"New: {stats['new']}, "
                f"Updated: {stats['updated']}, "
                f"Unchanged: {stats['unchanged']}, "
                f"JSON Exported: {stats['json_exported']}, "
                f"Retried (429): {stats['retried_429']}, "
                f"Failed: {stats['failed']}"
            )
    
            return True
    
        except Exception as e:
            logger.error(f"Error processing folder {url}: {e}", exc_info=True)
            return False

    def _extract_gdrive_file_id(self, url: str) -> str:
        """Извлечь Google Drive file ID из URL"""
        if not url:
            return ""
    
        # Паттерны для разных типов Google Drive URL
        patterns = [
            r'/file/d/([a-zA-Z0-9_-]+)',  # https://drive.google.com/file/d/FILE_ID
            r'/folders/([a-zA-Z0-9_-]+)',  # https://drive.google.com/folders/FOLDER_ID
            r'id=([a-zA-Z0-9_-]+)',  # параметр id
            r'/d/([a-zA-Z0-9_-]+)',  # короткий формат
        ]
    
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
    
        # Если не нашли по паттернам, возможно это уже ID
        if '/' not in url and len(url) > 10:
            return url
    
        return ""

    def _extract_file_content(self, full_markdown: str, file_path: str) -> str:
        """Извлечь контент конкретного файла из общего markdown"""
        import re
    
        # Ищем секцию для этого файла
        # Экранируем специальные символы в пути файла
        escaped_path = re.escape(file_path)
        pattern = rf"## 📄 {escaped_path}\n\n.*?\n\n---"
    
        match = re.search(pattern, full_markdown, re.DOTALL)
    
        if match:
            content = match.group(0)
            # Разбираем контент на строки
            lines = content.split('\n')
        
            # Находим где заканчиваются метаданные (после пустой строки)
            content_start = 0
            for i, line in enumerate(lines):
                if i > 2 and line.strip() == '' and lines[i-1].startswith('*Type:'):
                    content_start = i + 1
                    break
        
            # Извлекаем контент без метаданных и финального разделителя
            if content_start > 0:
                content_lines = lines[content_start:]
                # Убираем последний разделитель
                if content_lines and content_lines[-1] == '---':
                    content_lines = content_lines[:-1]
                # Убираем пустые строки в конце
                while content_lines and not content_lines[-1].strip():
                    content_lines.pop()
            
                return '\n'.join(content_lines).strip()
    
        # Если не нашли по точному пути, пробуем найти по имени файла
        file_name = file_path.split('/')[-1] if '/' in file_path else file_path
        simple_pattern = rf"## 📄.*{re.escape(file_name)}\n\n.*?\n\n---"
    
        match = re.search(simple_pattern, full_markdown, re.DOTALL)
        if match:
            content = match.group(0)
            lines = content.split('\n')
        
            content_start = 0
            for i, line in enumerate(lines):
                if i > 2 and line.strip() == '' and lines[i-1].startswith('*Type:'):
                    content_start = i + 1
                    break
        
            if content_start > 0:
                content_lines = lines[content_start:]
                if content_lines and content_lines[-1] == '---':
                    content_lines = content_lines[:-1]
                while content_lines and not content_lines[-1].strip():
                    content_lines.pop()
            
                return '\n'.join(content_lines).strip()
    
        return ""


def main():
    """Главная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Document Synchronization Utility')

    parser.add_argument('--config', default='NETHACK/herocraft/config.json', help='Full path to config file')

    parser.add_argument('--once', action='store_true', help='Run sync once and exit')
    
    args = parser.parse_args()
    
    # Проверяем существование config файла
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)
    
    sync = DocumentSync(str(config_path))
    
    if args.once:
        sync.sync_all_pages()
    else:
        sync.run_continuous()

if __name__ == '__main__':
    main()