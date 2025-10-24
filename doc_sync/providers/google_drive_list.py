# doc_sync/providers/google_drive_list.py
import os
import re
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from typing import Dict, Optional, Tuple, List, Set
from datetime import datetime
import fnmatch
from collections import defaultdict

# Добавляем родительскую директорию в path
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from providers.base import DocumentProvider

logger = logging.getLogger(__name__)

class GoogleDriveListProvider(DocumentProvider):
    """Провайдер для создания списка файлов Google Drive с ссылками"""
    
    SCOPES = [
        'https://www.googleapis.com/auth/drive.readonly'
    ]
    
    def __init__(self, auth_config: Dict):
        super().__init__(auth_config)
        
        # Описание для вставки в начало
        self.description = auth_config.get('description', '')
        
        # Паттерны для пропуска файлов и папок
        self.skip_file_patterns = auth_config.get('skip_file_patterns', [])
        self.skip_folder_patterns = auth_config.get('skip_folder_patterns', [])
        
        # Опции форматирования
        self.include_folders = auth_config.get('include_folders', True)
        self.include_file_types = auth_config.get('include_file_types', True)
        self.include_modified_date = auth_config.get('include_modified_date', True)
        self.include_size = auth_config.get('include_size', True)
        self.sort_by = auth_config.get('sort_by', 'name')  # name, modified, size
        self.group_by_directory = auth_config.get('group_by_directory', True)  # Новая опция
        
        logger.info(f"GoogleDriveListProvider initialized with skip patterns: files={self.skip_file_patterns}, folders={self.skip_folder_patterns}")
    
    def setup_auth(self):
        """Настройка авторизации для Google Drive"""
        service_account_file = self.auth_config.get('service_account_file')
        
        if not os.path.isabs(service_account_file):
            service_account_file = os.path.abspath(service_account_file)
        
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file, scopes=self.SCOPES
        )
        
        self.drive_service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
        logger.info("Google Drive List provider initialized")
    
    def extract_folder_id(self, url: str) -> str:
        """Извлечь ID папки из URL"""
        if 'drive.google.com' in url:
            parts = url.split('/')
            for i, part in enumerate(parts):
                if part == 'folders' and i + 1 < len(parts):
                    folder_id = parts[i + 1].split('?')[0]
                    return folder_id
        return url
    
    def _should_skip_folder(self, foldername: str) -> bool:
        """Проверить, нужно ли пропустить папку"""
        for pattern in self.skip_folder_patterns:
            # Проверяем с учетом регистра и без него
            if fnmatch.fnmatch(foldername, pattern) or fnmatch.fnmatch(foldername.lower(), pattern.lower()):
                logger.debug(f"Skipping folder '{foldername}' - matches pattern '{pattern}'")
                return True
        return False

    def _should_skip_file(self, filename: str) -> bool:
        """Проверить, нужно ли пропустить файл"""
        for pattern in self.skip_file_patterns:
            # Проверяем с учетом регистра и без него
            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(filename.lower(), pattern.lower()):
                logger.debug(f"Skipping file '{filename}' - matches pattern '{pattern}'")
                return True
        return False
    
    def fetch_content(self, url: str) -> Tuple[str, Dict]:
        """
        Получить список файлов в папке Google Drive с описанием
        """
        folder_id = self.extract_folder_id(url)
        
        logger.info(f"Creating file list for Google Drive folder: {folder_id}")
        
        # Получаем информацию о папке
        try:
            folder = self.drive_service.files().get(fileId=folder_id).execute()
            folder_name = folder.get('name', 'Untitled Folder')
        except Exception as e:
            logger.error(f"Failed to get folder info: {e}")
            folder_name = 'Google Drive Folder'
        
        # Собираем все файлы рекурсивно
        all_items = self._get_all_items_recursive(folder_id, "")
        
        # Фильтруем пропущенные элементы
        filtered_items = [item for item in all_items if not item.get('skipped', False)]
        
        logger.info(f"Found {len(filtered_items)} items (skipped {len(all_items) - len(filtered_items)})")
        
        # Метаданные
        metadata = {
            'title': f"{folder_name} - File List",
            'id': folder_id,
            'type': 'google_drive_list',
            'modified_time': datetime.now().isoformat(),
            'last_modified': datetime.now().isoformat(),
            'files_count': len([i for i in filtered_items if i['type'] == 'file']),
            'folders_count': len([i for i in filtered_items if i['type'] == 'folder']),
            '_is_markdown': True
        }
        
        # Генерируем markdown список с описанием
        markdown_content = self._generate_markdown_list(filtered_items, folder_name, all_items)
        
        return markdown_content, metadata
    
    def _get_all_items_recursive(self, folder_id: str, folder_path: str = "", level: int = 0) -> List[Dict]:
        """Рекурсивно получить все элементы из папки"""
        all_items = []
        
        try:
            # Получаем элементы в текущей папке
            query = f"'{folder_id}' in parents and trashed = false"
            response = self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType, modifiedTime, size, webViewLink)",
                pageSize=1000,
                orderBy='folder,name'  # Сначала папки, потом файлы
            ).execute()
            
            items = response.get('files', [])
            
            for item in items:
                item_name = item['name']
                item_path = f"{folder_path}/{item_name}" if folder_path else item_name
                
                is_folder = item['mimeType'] == 'application/vnd.google-apps.folder'
                
                # Проверяем паттерны пропуска
                should_skip = False
                if is_folder:
                    should_skip = self._should_skip_folder(item_name)
                else:
                    should_skip = self._should_skip_file(item_name)
                
                # Добавляем элемент в список
                item_info = {
                    'id': item['id'],
                    'name': item_name,
                    'path': item_path,
                    'directory': folder_path if folder_path else '.',  # Директория для группировки
                    'type': 'folder' if is_folder else 'file',
                    'mime_type': item['mimeType'],
                    'modified_time': item.get('modifiedTime'),
                    'size': item.get('size', 0),
                    'url': item.get('webViewLink', f"https://drive.google.com/file/d/{item['id']}"),
                    'level': level,
                    'skipped': should_skip
                }
                
                all_items.append(item_info)
                
                # Рекурсивно обходим подпапки (если не пропускаем)
                if is_folder and not should_skip:
                    logger.debug(f"Entering subfolder: {item_path}")
                    subitems = self._get_all_items_recursive(item['id'], item_path, level + 1)
                    all_items.extend(subitems)
                elif is_folder and should_skip:
                    logger.info(f"Skipped folder and its contents: {item_path}")
            
            # Обработка пагинации
            while 'nextPageToken' in response:
                response = self.drive_service.files().list(
                    q=query,
                    fields="files(id, name, mimeType, modifiedTime, size, webViewLink)",
                    pageSize=1000,
                    pageToken=response['nextPageToken'],
                    orderBy='folder,name'
                ).execute()
                
                for item in response.get('files', []):
                    item_name = item['name']
                    item_path = f"{folder_path}/{item_name}" if folder_path else item_name
                    is_folder = item['mimeType'] == 'application/vnd.google-apps.folder'
                    
                    should_skip = False
                    if is_folder:
                        should_skip = self._should_skip_folder(item_name)
                    else:
                        should_skip = self._should_skip_file(item_name)
                    
                    item_info = {
                        'id': item['id'],
                        'name': item_name,
                        'path': item_path,
                        'directory': folder_path if folder_path else '.',
                        'type': 'folder' if is_folder else 'file',
                        'mime_type': item['mimeType'],
                        'modified_time': item.get('modifiedTime'),
                        'size': item.get('size', 0),
                        'url': item.get('webViewLink', f"https://drive.google.com/file/d/{item['id']}"),
                        'level': level,
                        'skipped': should_skip
                    }
                    
                    all_items.append(item_info)
                    
                    if is_folder and not should_skip:
                        subitems = self._get_all_items_recursive(item['id'], item_path, level + 1)
                        all_items.extend(subitems)
                    
        except Exception as e:
            logger.error(f"Error listing items in folder {folder_id}: {e}")
        
        return all_items
    
    def _generate_markdown_list(self, items: List[Dict], folder_name: str, all_items: List[Dict]) -> str:
        """Генерировать markdown список файлов с описанием"""
    
        # Если есть описание, используем его как главный заголовок
        if self.description:
            md = f"# {self.description}\n\n"
        else:
            # Если описания нет, используем имя папки
            md = f"# 📁 {folder_name}\n\n"
    
        # Сразу переходим к списку файлов
        if self.group_by_directory:
            md += self._generate_directory_grouped_list(items)
        else:
            md += self._generate_tree_list(items)
    
        return md  

    def _generate_directory_grouped_list(self, items: List[Dict]) -> str:
        """Генерировать список, сгруппированный по директориям"""
        md = ""  # Убираем заголовок "Files and Folders"
    
        # Группируем элементы по директориям
        directories = defaultdict(list)
        for item in items:
            directories[item['directory']].append(item)
    
        # Сортируем директории по алфавиту (корень первым)
        sorted_dirs = sorted(directories.keys())
        if '.' in sorted_dirs:
            sorted_dirs.remove('.')
            sorted_dirs.insert(0, '.')
    
        # Выводим каждую директорию
        for directory in sorted_dirs:
            dir_items = directories[directory]
        
            # Заголовок директории
            if directory == '.':
                md += "## 📂 Root Directory\n\n"  # Изменено с ### на ##
            else:
                # Определяем уровень вложенности
                level = directory.count('/')
                # Используем ## для первого уровня, ### для второго и т.д.
                header_level = min(level + 2, 6)  # Начинаем с ##, максимум ######
                header = '#' * header_level
                md += f"{header} 📂 {directory}\n\n"
        
            # Сортируем элементы в директории
            if self.sort_by == 'modified':
                dir_items.sort(key=lambda x: x.get('modified_time', ''), reverse=True)
            elif self.sort_by == 'size':
                dir_items.sort(key=lambda x: int(x.get('size', 0)), reverse=True)
            else:  # name
                # Сначала папки, потом файлы, внутри каждой группы по алфавиту
                dir_items.sort(key=lambda x: (x['type'] != 'folder', x['name'].lower()))
        
            # Выводим элементы
            for item in dir_items:
                # Иконка
                if item['type'] == 'folder':
                    icon = "📁"
                else:
                    icon = self._get_file_icon(item['mime_type'])
            
                # Имя с ссылкой
                name_link = f"[{item['name']}]({item['url']})"
            
                # Дополнительная информация
                extra_info = []
            
                if self.include_file_types and item['type'] == 'file':
                    file_type = self._get_file_type_label(item['mime_type'])
                    if file_type:
                        extra_info.append(file_type)
            
                if self.include_modified_date and item.get('modified_time'):
                    date = datetime.fromisoformat(item['modified_time'].replace('Z', '+00:00'))
                    extra_info.append(date.strftime('%Y-%m-%d'))
            
                if self.include_size and item['type'] == 'file' and item.get('size'):
                    size_str = self._format_file_size(int(item['size']))
                    extra_info.append(size_str)
            
                # Формируем строку
                line = f"- {icon} {name_link}"
                if extra_info:
                    line += f" *({', '.join(extra_info)})*"
            
                md += line + "\n"
        
            md += "\n"  # Пустая строка после каждой директории
    
        return md

    def _generate_tree_list(self, items: List[Dict]) -> str:
        """Генерировать список в виде дерева (старая версия)"""
        md = ""
        
        # Сортируем элементы
        if self.sort_by == 'modified':
            items.sort(key=lambda x: x.get('modified_time', ''), reverse=True)
        elif self.sort_by == 'size':
            items.sort(key=lambda x: int(x.get('size', 0)), reverse=True)
        else:  # name
            items.sort(key=lambda x: (x.get('level', 0), x.get('path', '').lower()))
        
        for item in items:
            indent = "  " * item.get('level', 0)
            
            # Иконка
            if item['type'] == 'folder':
                icon = "📁"
            else:
                icon = self._get_file_icon(item['mime_type'])
            
            # Имя с ссылкой
            name_link = f"[{item['name']}]({item['url']})"
            
            # Дополнительная информация
            extra_info = []
            
            if self.include_file_types and item['type'] == 'file':
                file_type = self._get_file_type_label(item['mime_type'])
                if file_type:
                    extra_info.append(file_type)
            
            if self.include_modified_date and item.get('modified_time'):
                date = datetime.fromisoformat(item['modified_time'].replace('Z', '+00:00'))
                extra_info.append(date.strftime('%Y-%m-%d'))
            
            if self.include_size and item['type'] == 'file' and item.get('size'):
                size_str = self._format_file_size(int(item['size']))
                extra_info.append(size_str)
            
            # Формируем строку
            line = f"{indent}- {icon} {name_link}"
            if extra_info:
                line += f" *({', '.join(extra_info)})*"
            
            md += line + "\n"
        
        return md
    
    def _get_file_icon(self, mime_type: str) -> str:
        """Получить иконку для типа файла"""
        icons = {
            'application/vnd.google-apps.document': '📄',
            'application/vnd.google-apps.spreadsheet': '📊',
            'application/vnd.google-apps.presentation': '📽️',
            'application/pdf': '📕',
            'image/': '🖼️',
            'video/': '🎬',
            'audio/': '🎵',
            'text/': '📝',
            'application/zip': '📦',
            'application/json': '📋',
        }
        
        for pattern, icon in icons.items():
            if mime_type.startswith(pattern):
                return icon
        
        return '📎'  # По умолчанию
    
    def _get_file_type_label(self, mime_type: str) -> str:
        """Получить метку типа файла"""
        labels = {
            'application/vnd.google-apps.document': 'Google Doc',
            'application/vnd.google-apps.spreadsheet': 'Google Sheet',
            'application/vnd.google-apps.presentation': 'Google Slides',
            'application/pdf': 'PDF',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel',
            'text/plain': 'Text',
            'text/csv': 'CSV',
            'text/markdown': 'Markdown',
        }
        
        return labels.get(mime_type, '')
    
    def _format_file_size(self, size_bytes: int) -> str:
        """Форматировать размер файла"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"
    
    def check_for_updates(self, url: str, last_modified: Optional[datetime]) -> bool:
        """Проверить обновления в папке"""
        if not last_modified:
            return True
        
        folder_id = self.extract_folder_id(url)
        
        try:
            from datetime import timezone
            
            # Нормализуем last_modified
            if isinstance(last_modified, str):
                last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
            
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
            
            # Ищем файлы измененные после last_modified
            query_date = last_modified.isoformat().replace('+00:00', 'Z')
            query = f"'{folder_id}' in parents and modifiedTime > '{query_date}' and trashed = false"
            
            response = self.drive_service.files().list(
                q=query,
                fields="files(id)",
                pageSize=1
            ).execute()
            
            # Если есть хотя бы один измененный файл
            if response.get('files'):
                return True
                
        except Exception as e:
            logger.error(f"Error checking folder updates: {e}")
            return True
        
        return False