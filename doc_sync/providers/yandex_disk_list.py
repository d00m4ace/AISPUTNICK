# doc_sync/providers/yandex_disk_list.py
import os
import logging
import requests
import fnmatch
from typing import Dict, Optional, Tuple, List
from datetime import datetime
from urllib.parse import urlparse, unquote
from collections import defaultdict
import sys

# Добавляем родительскую директорию в path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from providers.base import DocumentProvider

logger = logging.getLogger(__name__)

class YandexDiskListProvider(DocumentProvider):
    """Провайдер для создания списка файлов Yandex Disk с ссылками"""
    
    YANDEX_API_BASE = "https://cloud-api.yandex.net/v1/disk"
    
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
        self.group_by_directory = auth_config.get('group_by_directory', True)
        
        # Публичные ссылки
        self.generate_public_links = auth_config.get('generate_public_links', False)
        
        logger.info(f"YandexDiskListProvider initialized with skip patterns: files={self.skip_file_patterns}, folders={self.skip_folder_patterns}")
    
    def setup_auth(self):
        """Настройка авторизации для Yandex Disk"""
        self.oauth_token = self.auth_config.get('oauth_token')
        
        if not self.oauth_token:
            raise ValueError("OAuth token is required for Yandex Disk")
        
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"OAuth {self.oauth_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        })
        
        logger.info("Yandex Disk List provider initialized")
    
    def extract_folder_path(self, url: str) -> str:
        """Извлечь путь папки из URL Yandex Disk"""
        # URL может быть вида:
        # https://disk.yandex.ru/d/HASH - публичная папка
        # https://disk.360.yandex.ru/d/HASH - публичная папка Yandex 360
        # https://360.yandex.ru/disk/d/HASH - альтернативный формат
        # https://disk.yandex.ru/client/disk/PATH - личная папка
        # disk:/path/to/folder - прямой путь
    
        if url.startswith("disk:"):
            return url[5:]  # Убираем disk:
    
        # Обработка публичных ссылок
        if any(x in url for x in ["/d/", "/disk/d/"]):
            # Извлекаем hash из URL
            if "/d/" in url:
                # Находим часть после /d/
                parts = url.split("/d/")[-1]
            else:
                # Для формата /disk/d/
                parts = url.split("/disk/d/")[-1]
        
            # Очищаем от параметров и путей
            hash_id = parts.split("?")[0].split("/")[0].strip()
        
            if hash_id:
                logger.info(f"Extracted hash from public URL: {hash_id}")
            
                # Для Yandex 360 может потребоваться полный URL
                # Пробуем оба варианта
                if "360" in url:
                    # Сначала пробуем с хешем, потом с полным URL
                    return f"public360:{hash_id}:{url}"
                else:
                    return f"public:{hash_id}"
    
        # Личная папка
        if "/client/disk/" in url:
            path = url.split("/client/disk/")[-1]
            return unquote(path) if path else "/"
    
        # Если это уже путь
        return url
     
    def _should_skip_folder(self, foldername: str) -> bool:
        """Проверить, нужно ли пропустить папку"""
        for pattern in self.skip_folder_patterns:
            if fnmatch.fnmatch(foldername, pattern) or fnmatch.fnmatch(foldername.lower(), pattern.lower()):
                logger.debug(f"Skipping folder '{foldername}' - matches pattern '{pattern}'")
                return True
        return False

    def _should_skip_file(self, filename: str) -> bool:
        """Проверить, нужно ли пропустить файл"""
        for pattern in self.skip_file_patterns:
            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(filename.lower(), pattern.lower()):
                logger.debug(f"Skipping file '{filename}' - matches pattern '{pattern}'")
                return True
        return False
    
    def fetch_content(self, url: str) -> Tuple[str, Dict]:
        """
        Получить список файлов в папке Yandex Disk с описанием
        """
        folder_path = self.extract_folder_path(url)
        
        logger.info(f"Creating file list for Yandex Disk folder: {folder_path}")
        
        # Получаем информацию о папке
        folder_info = self._get_resource_info(folder_path)
        folder_name = folder_info.get('name', 'Yandex Disk Folder')
        
        # Собираем все элементы рекурсивно
        all_items = self._get_all_items_recursive(folder_path, "", 0)
        
        # Фильтруем пропущенные элементы
        filtered_items = [item for item in all_items if not item.get('skipped', False)]
        
        logger.info(f"Found {len(filtered_items)} items (skipped {len(all_items) - len(filtered_items)})")
        
        # Метаданные
        metadata = {
            'title': f"{folder_name} - File List",
            'path': folder_path,
            'type': 'yandex_disk_list',
            'modified_time': datetime.now().isoformat(),
            'last_modified': datetime.now().isoformat(),
            'files_count': len([i for i in filtered_items if i['type'] == 'file']),
            'folders_count': len([i for i in filtered_items if i['type'] == 'folder']),
            '_is_markdown': True
        }
        
        # Генерируем markdown список
        markdown_content = self._generate_markdown_list(filtered_items, folder_name, all_items)
        
        return markdown_content, metadata
    
    def _get_resource_info(self, path: str) -> Dict:
        """Получить информацию о ресурсе"""
        try:
            # Для публичных ресурсов Yandex 360
            if path.startswith("public360:"):
                parts = path[10:].split(":", 1)
                hash_id = parts[0]
                full_url = parts[1] if len(parts) > 1 else None
            
                logger.info(f"Trying Yandex 360 public resource: hash={hash_id}")
            
                # Пробуем сначала с хешем
                response = self.session.get(
                    f"{self.YANDEX_API_BASE}/public/resources",
                    params={"public_key": hash_id}
                )
            
                if response.status_code != 200 and full_url:
                    # Пробуем с полным URL
                    logger.info(f"Hash failed, trying full URL: {full_url}")
                    response = self.session.get(
                        f"{self.YANDEX_API_BASE}/public/resources",
                        params={"public_key": full_url}
                    )
            
                if response.status_code != 200:
                    # Пробуем без авторизации
                    logger.info("Trying without authorization")
                    public_session = requests.Session()
                    response = public_session.get(
                        "https://cloud-api.yandex.net/v1/disk/public/resources",
                        params={"public_key": hash_id}
                    )
                
                    if response.status_code != 200 and full_url:
                        # Последняя попытка - полный URL без авторизации
                        response = public_session.get(
                            "https://cloud-api.yandex.net/v1/disk/public/resources",
                            params={"public_key": full_url}
                        )
            
                if response.status_code == 200:
                    logger.info("Successfully got resource info")
                    return response.json()
                else:
                    logger.error(f"All attempts failed. Status: {response.status_code}")
                    logger.error(f"Response: {response.text[:200]}")
                    return {"name": "Yandex 360 Folder"}
        
            # Для обычных публичных ресурсов
            elif path.startswith("public:"):
                public_key = path[7:]
            
                logger.info(f"Getting info for public resource: {public_key}")
            
                # Пробуем с авторизацией
                response = self.session.get(
                    f"{self.YANDEX_API_BASE}/public/resources",
                    params={"public_key": public_key}
                )
            
                if response.status_code != 200:
                    # Пробуем без авторизации
                    logger.info("Trying public API without auth")
                    public_session = requests.Session()
                    response = public_session.get(
                        "https://cloud-api.yandex.net/v1/disk/public/resources",
                        params={"public_key": public_key}
                    )
            
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Failed to get public resource. Status: {response.status_code}")
                    return {"name": "Public Folder"}
        
            else:
                # Для приватных ресурсов
                response = self.session.get(
                    f"{self.YANDEX_API_BASE}/resources",
                    params={"path": path}
                )
            
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Failed to get resource info: {response.status_code}")
                    return {"name": "Unknown"}
                
        except Exception as e:
            logger.error(f"Error getting resource info: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"name": "Unknown"}

    def _get_all_items_recursive(self, folder_path: str, parent_path: str = "", level: int = 0) -> List[Dict]:
        """Рекурсивно получить все элементы из папки"""
        all_items = []
    
        try:
            # Получаем содержимое папки
            if folder_path.startswith("public360:"):
                # Для Yandex 360 используем специальную обработку
                parts = folder_path[10:].split(":", 1)
                hash_id = parts[0]
                full_url = parts[1] if len(parts) > 1 else None
            
                # Если это вложенная папка (содержит /), используем как обычный public key
                if "/" in hash_id:
                    public_key = hash_id
                else:
                    # Для корневой папки пробуем разные варианты
                    public_key = full_url if full_url else hash_id
            
                logger.info(f"Listing Yandex 360 folder with key: {public_key[:50]}...")
            
                # Сначала пробуем с авторизацией
                response = self.session.get(
                    f"{self.YANDEX_API_BASE}/public/resources",
                    params={
                        "public_key": public_key,
                        "limit": 1000,
                        "fields": "_embedded.items"
                    }
                )
            
                if response.status_code != 200:
                    # Пробуем без авторизации
                    logger.info("Trying without authorization")
                    public_session = requests.Session()
                    response = public_session.get(
                        "https://cloud-api.yandex.net/v1/disk/public/resources",
                        params={
                            "public_key": public_key,
                            "limit": 1000
                        }
                    )
                
                    # Если все еще не работает, пробуем с хешем
                    if response.status_code != 200 and hash_id and not "/" in hash_id:
                        response = public_session.get(
                            "https://cloud-api.yandex.net/v1/disk/public/resources",
                            params={
                                "public_key": hash_id,
                                "limit": 1000
                            }
                        )
                    
            elif folder_path.startswith("public:"):
                public_key = folder_path[7:]
            
                # Пробуем с авторизацией
                response = self.session.get(
                    f"{self.YANDEX_API_BASE}/public/resources",
                    params={
                        "public_key": public_key,
                        "limit": 1000,
                        "fields": "_embedded.items"
                    }
                )
            
                if response.status_code != 200:
                    # Пробуем без авторизации
                    public_session = requests.Session()
                    response = public_session.get(
                        "https://cloud-api.yandex.net/v1/disk/public/resources",
                        params={
                            "public_key": public_key,
                            "limit": 1000
                        }
                    )
            else:
                response = self.session.get(
                    f"{self.YANDEX_API_BASE}/resources",
                    params={
                        "path": folder_path,
                        "limit": 1000,
                        "fields": "_embedded.items"
                    }
                )
        
            if response.status_code != 200:
                logger.error(f"Failed to list folder contents: {response.status_code}")
                logger.error(f"Response: {response.text[:500] if response.text else 'No response text'}")
                return all_items
        
            data = response.json()
            items = data.get('_embedded', {}).get('items', [])
        
            for item in items:
                item_name = item.get('name')
                item_type = item.get('type')
                item_path = f"{parent_path}/{item_name}" if parent_path else item_name
            
                is_folder = item_type == 'dir'
            
                # Проверяем паттерны пропуска
                should_skip = False
                if is_folder:
                    should_skip = self._should_skip_folder(item_name)
                else:
                    should_skip = self._should_skip_file(item_name)
            
                # Получаем URL для элемента
                item_url = self._get_item_url(item)
            
                # Добавляем элемент в список
                item_info = {
                    'id': item.get('resource_id', ''),
                    'name': item_name,
                    'path': item_path,
                    'directory': parent_path if parent_path else '.',
                    'type': 'folder' if is_folder else 'file',
                    'mime_type': item.get('mime_type', 'application/octet-stream'),
                    'modified_time': item.get('modified'),
                    'size': item.get('size', 0),
                    'url': item_url,
                    'level': level,
                    'skipped': should_skip
                }
            
                all_items.append(item_info)
            
                # Рекурсивно обходим подпапки (если не пропускаем)
                if is_folder and not should_skip:
                    logger.debug(f"Entering subfolder: {item_path}")
                
                    # Определяем путь для подпапки
                    if 'public_url' in item and item['public_url']:
                        # Извлекаем ключ из public_url
                        if "/d/" in item['public_url']:
                            sub_hash = item['public_url'].split("/d/")[-1].split("?")[0].split("/")[0]
                            subfolder_path = f"public:{sub_hash}"
                        else:
                            subfolder_path = f"public:{item['public_url']}"
                    elif 'public_key' in item:
                        subfolder_path = f"public:{item['public_key']}"
                    elif folder_path.startswith("public360:"):
                        # Для подпапок Yandex 360 формируем путь относительно родителя
                        parts = folder_path[10:].split(":", 1)
                        parent_key = parts[0] if "/" not in parts[0] else parts[0].split("/")[0]
                    
                        # Если родитель уже содержит путь, добавляем к нему
                        if "/" in parts[0]:
                            base_path = parts[0]
                            subfolder_path = f"public360:{base_path}/{item_name}:{parts[1] if len(parts) > 1 else ''}"
                        else:
                            # Используем полный URL с добавлением пути
                            if len(parts) > 1 and parts[1]:
                                # Формируем путь на основе полного URL
                                subfolder_path = f"public360:{parent_key}/{item_name}:{parts[1]}"
                            else:
                                subfolder_path = f"public360:{parent_key}/{item_name}:"
                    elif folder_path.startswith("public:"):
                        # Для обычных публичных подпапок используем путь относительно корня
                        parent_key = folder_path[7:]
                        subfolder_path = f"public:{parent_key}/{item_name}"
                    else:
                        subfolder_path = item.get('path', f"{folder_path}/{item_name}")
                
                    subitems = self._get_all_items_recursive(
                        subfolder_path,
                        item_path,
                        level + 1
                    )
                    all_items.extend(subitems)
                
                elif is_folder and should_skip:
                    logger.info(f"Skipped folder and its contents: {item_path}")
                
        except Exception as e:
            logger.error(f"Error listing items in folder {folder_path}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    
        return all_items        
  
    def _get_item_url(self, item: Dict) -> str:
        """Получить URL для элемента"""
        # Если есть публичная ссылка
        if item.get('public_url'):
            return item['public_url']
        
        # Если есть public_key
        if item.get('public_key'):
            return f"https://disk.yandex.ru/d/{item['public_key']}"
        
        # Для приватных файлов - генерируем ссылку на веб-интерфейс
        if item.get('path'):
            path = item['path']
            # Кодируем путь для URL
            from urllib.parse import quote
            encoded_path = quote(path, safe='')
            
            if item.get('type') == 'dir':
                return f"https://disk.yandex.ru/client/disk{path}"
            else:
                return f"https://disk.yandex.ru/client/disk?dialog=slider&idDialog=%2Fdisk{encoded_path}"
        
        return "#"
    
    def _generate_markdown_list(self, items: List[Dict], folder_name: str, all_items: List[Dict]) -> str:
        """Генерировать markdown список файлов с описанием"""
        
        # Если есть описание, используем его как главный заголовок
        if self.description:
            md = f"# {self.description}\n\n"
        else:
            md = f"# 📁 {folder_name}\n\n"
        
        # Статистика
        md += f"**Total items:** {len(items)} "
        md += f"({len([i for i in items if i['type'] == 'file'])} files, "
        md += f"{len([i for i in items if i['type'] == 'folder'])} folders)\n"
        
        if len(all_items) > len(items):
            md += f"*Skipped {len(all_items) - len(items)} items based on filter patterns*\n"
        
        md += "\n---\n\n"
        
        # Список файлов
        if self.group_by_directory:
            md += self._generate_directory_grouped_list(items)
        else:
            md += self._generate_tree_list(items)
        
        return md
    
    def _generate_directory_grouped_list(self, items: List[Dict]) -> str:
        """Генерировать список, сгруппированный по директориям"""
        md = ""
        
        # Группируем элементы по директориям
        directories = defaultdict(list)
        for item in items:
            directories[item['directory']].append(item)
        
        # Сортируем директории
        sorted_dirs = sorted(directories.keys())
        if '.' in sorted_dirs:
            sorted_dirs.remove('.')
            sorted_dirs.insert(0, '.')
        
        # Выводим каждую директорию
        for directory in sorted_dirs:
            dir_items = directories[directory]
            
            # Заголовок директории
            if directory == '.':
                md += "## 📂 Root Directory\n\n"
            else:
                level = directory.count('/')
                header_level = min(level + 2, 6)
                header = '#' * header_level
                md += f"{header} 📂 {directory}\n\n"
            
            # Сортируем элементы
            if self.sort_by == 'modified':
                dir_items.sort(key=lambda x: x.get('modified_time', ''), reverse=True)
            elif self.sort_by == 'size':
                dir_items.sort(key=lambda x: int(x.get('size', 0)), reverse=True)
            else:  # name
                dir_items.sort(key=lambda x: (x['type'] != 'folder', x['name'].lower()))
            
            # Выводим элементы
            for item in dir_items:
                line = self._format_item_line(item)
                md += line + "\n"
            
            md += "\n"
        
        return md
    
    def _generate_tree_list(self, items: List[Dict]) -> str:
        """Генерировать список в виде дерева"""
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
            line = self._format_item_line(item, indent)
            md += line + "\n"
        
        return md
    
    def _format_item_line(self, item: Dict, indent: str = "") -> str:
        """Форматировать строку для элемента"""
        # Иконка
        if item['type'] == 'folder':
            icon = "📁"
        else:
            icon = self._get_file_icon(item['mime_type'], item['name'])
        
        # Имя с ссылкой
        name_link = f"[{item['name']}]({item['url']})"
        
        # Дополнительная информация
        extra_info = []
        
        if self.include_file_types and item['type'] == 'file':
            file_type = self._get_file_type_label(item['mime_type'], item['name'])
            if file_type:
                extra_info.append(file_type)
        
        if self.include_modified_date and item.get('modified_time'):
            try:
                date = datetime.fromisoformat(item['modified_time'].replace('Z', '+00:00'))
                extra_info.append(date.strftime('%Y-%m-%d'))
            except:
                pass
        
        if self.include_size and item['type'] == 'file' and item.get('size'):
            size_str = self._format_file_size(int(item['size']))
            extra_info.append(size_str)
        
        # Формируем строку
        if indent:
            line = f"{indent}- {icon} {name_link}"
        else:
            line = f"- {icon} {name_link}"
        
        if extra_info:
            line += f" *({', '.join(extra_info)})*"
        
        return line
    
    def _get_file_icon(self, mime_type: str, filename: str = "") -> str:
        """Получить иконку для типа файла"""
        # Проверяем по расширению файла
        ext = os.path.splitext(filename.lower())[1] if filename else ""
        
        ext_icons = {
            '.doc': '📄', '.docx': '📄',
            '.xls': '📊', '.xlsx': '📊',
            '.ppt': '📽️', '.pptx': '📽️',
            '.pdf': '📕',
            '.txt': '📝', '.md': '📝', '.markdown': '📝',
            '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️',
            '.mp4': '🎬', '.avi': '🎬', '.mov': '🎬',
            '.mp3': '🎵', '.wav': '🎵', '.flac': '🎵',
            '.zip': '📦', '.rar': '📦', '.7z': '📦',
            '.json': '📋', '.xml': '📋', '.csv': '📋'
        }
        
        if ext in ext_icons:
            return ext_icons[ext]
        
        # Проверяем по MIME типу
        mime_icons = {
            'image/': '🖼️',
            'video/': '🎬',
            'audio/': '🎵',
            'text/': '📝',
            'application/pdf': '📕',
            'application/zip': '📦'
        }
        
        for pattern, icon in mime_icons.items():
            if mime_type.startswith(pattern):
                return icon
        
        return '📎'  # По умолчанию
    
    def _get_file_type_label(self, mime_type: str, filename: str = "") -> str:
        """Получить метку типа файла"""
        ext = os.path.splitext(filename.lower())[1] if filename else ""
        
        ext_labels = {
            '.doc': 'Word', '.docx': 'Word',
            '.xls': 'Excel', '.xlsx': 'Excel',
            '.ppt': 'PowerPoint', '.pptx': 'PowerPoint',
            '.pdf': 'PDF',
            '.txt': 'Text', '.md': 'Markdown',
            '.csv': 'CSV', '.json': 'JSON', '.xml': 'XML'
        }
        
        if ext in ext_labels:
            return ext_labels[ext]
        
        mime_labels = {
            'application/pdf': 'PDF',
            'text/plain': 'Text',
            'text/csv': 'CSV',
            'text/markdown': 'Markdown'
        }
        
        return mime_labels.get(mime_type, '')
    
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
        
        folder_path = self.extract_folder_path(url)
        
        try:
            from datetime import timezone
            
            # Нормализуем last_modified
            if isinstance(last_modified, str):
                last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
            
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
            
            # Получаем информацию о папке
            folder_info = self._get_resource_info(folder_path)
            
            if folder_info.get('modified'):
                folder_modified = datetime.fromisoformat(
                    folder_info['modified'].replace('Z', '+00:00')
                )
                
                # Проверяем, изменилась ли папка
                if folder_modified > last_modified:
                    return True
            
        except Exception as e:
            logger.error(f"Error checking folder updates: {e}")
            return True
        
        return False