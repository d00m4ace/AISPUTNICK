# doc_sync/providers/yandex_disk.py
import re
import os
import logging
import requests
import hashlib
from typing import Dict, Optional, Tuple, List
from datetime import datetime
from urllib.parse import urlparse, unquote
import sys

# Добавляем родительскую директорию в path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from providers.base import DocumentProvider

logger = logging.getLogger(__name__)

class YandexDiskProvider(DocumentProvider):
    """Провайдер для рекурсивного обхода папок Yandex Disk"""
    
    YANDEX_API_BASE = "https://cloud-api.yandex.net/v1/disk"
    
    # MIME типы которые нужно обрабатывать
    SUPPORTED_MIMETYPES = {
        'application/pdf',
        'text/plain',
        'text/csv',
        'text/markdown',
        'application/msword',
        'application/vnd.ms-excel',
        'application/vnd.ms-powerpoint',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'application/rtf',
        'text/rtf',
        'application/vnd.oasis.opendocument.text'
    }
    
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
        
        # Инициализируем конвертеры
        self._init_converters()
        
        logger.info("Yandex Disk provider initialized")   
    
    def _init_converters(self):
        """Инициализация конвертеров документов"""
        try:
            from converters import HTMLToMarkdownConverter
            self.html_converter = HTMLToMarkdownConverter()
        except ImportError:
            logger.warning("HTMLToMarkdownConverter not available")
            self.html_converter = None
    
        # Импортируем универсальный конвертер для различных форматов
        try:
            from converters import UniversalFileConverter
            self.universal_converter = UniversalFileConverter()
        except ImportError:
            logger.warning("UniversalFileConverter not available")
            self.universal_converter = None

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
    
    def _get_public_folder_path(self, url: str) -> str:
        """Получить путь для публичной папки"""
        # Для Yandex 360 используем полный URL как ключ
        if "disk.360" in url or "360.yandex" in url:
            return url
        
        # Для обычного disk.yandex.ru извлекаем hash
        if "/d/" in url:
            # Извлекаем часть после /d/
            parts = url.split("/d/")[-1]
            # Убираем query параметры если есть
            public_key = parts.split("?")[0].split("/")[0]
            return public_key
        
        return url
    
    def fetch_content(self, url: str) -> Tuple[str, Dict]:
        """
        Получить содержимое всех файлов в папке Yandex Disk
        Возвращает объединенный markdown всех файлов
        """
        folder_path = self.extract_folder_path(url)
        
        logger.info(f"Starting recursive scan of Yandex Disk folder: {folder_path}")
        
        # Получаем информацию о папке
        folder_info = self._get_resource_info(folder_path)
        folder_name = folder_info.get('name', 'Yandex Disk Folder')
        
        # Собираем все файлы рекурсивно
        all_files = self._get_all_files_recursive(folder_path, folder_name)
        
        logger.info(f"Found {len(all_files)} files in folder")
        
        # Метаданные папки
        metadata = {
            'title': folder_name,
            'path': folder_path,
            'type': 'yandex_disk_folder',
            'modified_time': folder_info.get('modified'),
            'last_modified': folder_info.get('modified'),
            'files_count': len(all_files),
            '_is_folder': True,
            '_files': []
        }
        
        # Обрабатываем каждый файл
        markdown_content = f"# {folder_name}\n\n"
        markdown_content += f"*Yandex Disk Folder - {len(all_files)} files*\n\n"
        markdown_content += "---\n\n"
        
        for file_info in all_files:
            file_metadata, file_content = self._process_file(file_info)
            
            if file_content:
                metadata['_files'].append({
                    'name': file_metadata['name'],
                    'path': file_metadata['path'],
                    'mime_type': file_metadata.get('mime_type', 'unknown')
                })
                
                markdown_content += f"## 📄 {file_metadata['path']}\n\n"
                markdown_content += f"*Type: {file_metadata.get('mime_type', 'unknown')}*\n"
                markdown_content += f"*Size: {self._format_size(file_metadata.get('size', 0))}*\n\n"
                markdown_content += file_content
                markdown_content += "\n\n---\n\n"
        
        metadata['_is_markdown'] = True
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
 
    def _get_all_files_recursive(self, folder_path: str, folder_name: str, level: int = 0) -> List[Dict]:
        """Рекурсивно получить все файлы из папки и подпапок"""
        all_files = []
    
        try:
            # Обработка Yandex 360 публичных папок
            if folder_path.startswith("public360:"):
                parts = folder_path[10:].split(":", 1)
                hash_id = parts[0]
                full_url = parts[1] if len(parts) > 1 else None
            
                logger.info(f"Listing Yandex 360 folder: hash={hash_id}, level={level}")
            
                # Пробуем разные варианты запроса
                response = None
            
                # Список вариантов public_key для попытки
                keys_to_try = [hash_id]
                if full_url:
                    keys_to_try.append(full_url)
            
                for public_key in keys_to_try:
                    if not public_key:
                        continue
                
                    # Сначала пробуем с авторизацией
                    temp_response = self.session.get(
                        f"{self.YANDEX_API_BASE}/public/resources",
                        params={
                            "public_key": public_key,
                            "limit": 1000,
                            "fields": "_embedded.items.name,_embedded.items.type,_embedded.items.mime_type,_embedded.items.size,_embedded.items.modified,_embedded.items.path,_embedded.items.public_key,_embedded.items.public_url"
                        }
                    )
                
                    if temp_response.status_code == 200:
                        response = temp_response
                        logger.info(f"Successfully listed with auth using key: {public_key[:20]}...")
                        break
                
                    # Если не удалось с авторизацией, пробуем без неё
                    public_session = requests.Session()
                    temp_response = public_session.get(
                        "https://cloud-api.yandex.net/v1/disk/public/resources",
                        params={
                            "public_key": public_key,
                            "limit": 1000
                        }
                    )
                
                    if temp_response.status_code == 200:
                        response = temp_response
                        logger.info(f"Successfully listed without auth using key: {public_key[:20]}...")
                        break
            
                if not response or response.status_code != 200:
                    logger.error(f"Failed to list Yandex 360 folder. Status: {response.status_code if response else 'No response'}")
                    if response:
                        logger.error(f"Response: {response.text[:500]}")
                    return all_files
        
            # Обычные публичные папки
            elif folder_path.startswith("public:"):
                public_key = folder_path[7:]
            
                logger.info(f"Listing public folder: {public_key[:30]}..., level={level}")
            
                response = self.session.get(
                    f"{self.YANDEX_API_BASE}/public/resources",
                    params={
                        "public_key": public_key,
                        "limit": 1000,
                        "fields": "_embedded.items.name,_embedded.items.type,_embedded.items.mime_type,_embedded.items.size,_embedded.items.modified,_embedded.items.path,_embedded.items.public_key,_embedded.items.public_url"
                    }
                )
            
                if response.status_code != 200:
                    logger.warning(f"Auth failed for public folder, trying without auth")
                    # Пробуем без авторизации
                    public_session = requests.Session()
                    response = public_session.get(
                        "https://cloud-api.yandex.net/v1/disk/public/resources",
                        params={
                            "public_key": public_key,
                            "limit": 1000
                        }
                    )
        
            # Приватные папки
            else:
                logger.info(f"Listing private folder: {folder_path}, level={level}")
            
                response = self.session.get(
                    f"{self.YANDEX_API_BASE}/resources",
                    params={
                        "path": folder_path,
                        "limit": 1000,
                        "fields": "_embedded.items.name,_embedded.items.type,_embedded.items.mime_type,_embedded.items.size,_embedded.items.modified,_embedded.items.path,_embedded.items.public_url"
                    }
                )
        
            if response.status_code != 200:
                logger.error(f"Failed to list folder contents: {response.status_code}")
                logger.error(f"Path: {folder_path}")
                if response.text:
                    logger.error(f"Error: {response.text[:500]}")
                return all_files
        
            data = response.json()
            items = data.get('_embedded', {}).get('items', [])
        
            logger.info(f"Found {len(items)} items at level {level} in {folder_name}")
        
            for item in items:
                item_name = item.get('name')
                item_type = item.get('type')
                item_path = f"{folder_name}/{item_name}" if level > 0 else item_name
            
                if item_type == 'dir':
                    # Это папка - рекурсивно обходим
                    logger.info(f"Entering subfolder: {item_path} (level {level + 1})")
                
                    # Определяем путь для подпапки
                    if 'public_url' in item and item['public_url']:
                        # Для публичных подпапок используем public_url
                        subfolder_path = f"public:{item['public_url']}"
                    
                    elif 'public_key' in item and item['public_key']:
                        # Или public_key если есть
                        subfolder_path = f"public:{item['public_key']}"
                    
                    elif folder_path.startswith("public360:"):
                        # Для подпапок Yandex 360
                        # Используем путь относительно родителя
                        parts = folder_path[10:].split(":", 1)
                        parent_key = parts[0]
                        # Формируем путь как родитель/подпапка
                        subfolder_path = f"public360:{parent_key}/{item_name}:{parts[1] if len(parts) > 1 else ''}"
                    
                    elif folder_path.startswith("public:"):
                        # Для обычных публичных подпапок
                        parent_key = folder_path[7:]
                        # Пробуем сформировать путь относительно родителя
                        subfolder_path = f"public:{parent_key}/{item_name}"
                    
                    else:
                        # Для приватных папок используем полный путь
                        subfolder_path = item.get('path')
                        if not subfolder_path:
                            # Если нет path, формируем из родительского пути
                            if folder_path == "/":
                                subfolder_path = f"/{item_name}"
                            else:
                                subfolder_path = f"{folder_path}/{item_name}"
                
                    logger.debug(f"Subfolder path: {subfolder_path}")
                
                    # Рекурсивный вызов
                    subfolder_files = self._get_all_files_recursive(
                        subfolder_path, 
                        item_path, 
                        level + 1
                    )
                    all_files.extend(subfolder_files)
                
                elif item_type == 'file':
                    # Это файл - проверяем, поддерживается ли
                    mime_type = item.get('mime_type', 'application/octet-stream')
                
                    if self._is_supported_file(mime_type, item_name):
                        logger.info(f"Found supported file: {item_path} ({mime_type})")
                    
                        file_info = {
                            'name': item_name,
                            'path': item_path,
                            'full_path': item.get('path'),  # Полный путь на диске
                            'mime_type': mime_type,
                            'size': item.get('size', 0),
                            'modified': item.get('modified'),
                            'public_url': item.get('public_url'),
                            'public_key': item.get('public_key')
                        }
                    
                        # Для публичных файлов добавляем информацию о родительской папке
                        if folder_path.startswith("public"):
                            file_info['parent_folder_path'] = folder_path
                    
                        all_files.append(file_info)
                    
                    else:
                        logger.debug(f"Skipping unsupported file: {item_path} ({mime_type})")
        
            # Обработка пагинации если есть
            next_page_token = data.get('_embedded', {}).get('next_page_token')
            if next_page_token:
                logger.info(f"Processing next page for folder: {folder_name}")
            
                # Формируем запрос для следующей страницы
                if folder_path.startswith("public"):
                    # Для публичных папок
                    public_key = folder_path.split(":", 1)[1]
                    page_response = self.session.get(
                        f"{self.YANDEX_API_BASE}/public/resources",
                        params={
                            "public_key": public_key,
                            "limit": 1000,
                            "offset": next_page_token,
                            "fields": "_embedded.items.name,_embedded.items.type,_embedded.items.mime_type,_embedded.items.size,_embedded.items.modified,_embedded.items.path,_embedded.items.public_key,_embedded.items.public_url"
                        }
                    )
                else:
                    # Для приватных папок
                    page_response = self.session.get(
                        f"{self.YANDEX_API_BASE}/resources",
                        params={
                            "path": folder_path,
                            "limit": 1000,
                            "offset": next_page_token,
                            "fields": "_embedded.items.name,_embedded.items.type,_embedded.items.mime_type,_embedded.items.size,_embedded.items.modified,_embedded.items.path,_embedded.items.public_url"
                        }
                    )
            
                if page_response.status_code == 200:
                    page_data = page_response.json()
                    page_items = page_data.get('_embedded', {}).get('items', [])
                
                    # Обрабатываем элементы со следующей страницы
                    for item in page_items:
                        # (Код обработки такой же как выше)
                        item_name = item.get('name')
                        item_type = item.get('type')
                        item_path = f"{folder_name}/{item_name}" if level > 0 else item_name
                    
                        if item_type == 'dir':
                            # Обработка подпапок
                            if 'public_url' in item and item['public_url']:
                                subfolder_path = f"public:{item['public_url']}"
                            elif 'public_key' in item and item['public_key']:
                                subfolder_path = f"public:{item['public_key']}"
                            else:
                                subfolder_path = item.get('path', f"{folder_path}/{item_name}")
                        
                            subfolder_files = self._get_all_files_recursive(
                                subfolder_path,
                                item_path,
                                level + 1
                            )
                            all_files.extend(subfolder_files)
                        
                        elif item_type == 'file':
                            mime_type = item.get('mime_type', 'application/octet-stream')
                        
                            if self._is_supported_file(mime_type, item_name):
                                all_files.append({
                                    'name': item_name,
                                    'path': item_path,
                                    'full_path': item.get('path'),
                                    'mime_type': mime_type,
                                    'size': item.get('size', 0),
                                    'modified': item.get('modified'),
                                    'public_url': item.get('public_url'),
                                    'public_key': item.get('public_key')
                                })
                        
        except Exception as e:
            logger.error(f"Error listing folder {folder_path}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    
        logger.info(f"Total files found in {folder_name}: {len(all_files)}")
        return all_files

    def _is_supported_file(self, mime_type: str, filename: str) -> bool:
        """Проверить, поддерживается ли тип файла"""
        # Проверяем по MIME типу
        if mime_type in self.SUPPORTED_MIMETYPES:
            return True
        
        # Проверяем по расширению файла
        supported_extensions = {
            '.txt', '.md', '.markdown', '.pdf', 
            '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
            '.rtf', '.odt', '.csv'
        }
        
        ext = os.path.splitext(filename.lower())[1]
        return ext in supported_extensions
    
    def _download_file(self, file_info: Dict) -> bytes:
        """Скачать файл с Yandex Disk"""
        try:
            # Получаем ссылку для скачивания
            if 'public_url' in file_info and file_info['public_url']:
                # Для публичных файлов используем public_url
                logger.info(f"Downloading public file: {file_info['name']}")
            
                # Пробуем получить прямую ссылку на скачивание
                public_session = requests.Session()
                response = public_session.get(
                    "https://cloud-api.yandex.net/v1/disk/public/resources/download",
                    params={"public_key": file_info['public_url']}
                )
            
            elif 'public_key' in file_info:
                # Для публичных файлов по ключу
                logger.info(f"Downloading file by public_key: {file_info['name']}")
                response = self.session.get(
                    f"{self.YANDEX_API_BASE}/public/resources/download",
                    params={"public_key": file_info['public_key']}
                )
            
            else:
                # Для приватных файлов
                file_path = file_info.get('full_path')
                if not file_path:
                    logger.error(f"No path available for file: {file_info['name']}")
                    return None
            
                logger.info(f"Downloading private file: {file_info['name']}")
                response = self.session.get(
                    f"{self.YANDEX_API_BASE}/resources/download",
                    params={"path": file_path}
                )
        
            if response.status_code != 200:
                logger.error(f"Failed to get download URL: {response.status_code}")
                logger.error(f"Response: {response.text[:500]}")
                return None
        
            download_url = response.json().get('href')
        
            if not download_url:
                logger.error("No download URL received")
                return None
        
            # Скачиваем файл
            logger.info(f"Downloading from URL for: {file_info['name']}")
            download_response = requests.get(download_url, stream=True)
        
            if download_response.status_code == 200:
                # Читаем содержимое в память
                content = download_response.content
                logger.info(f"Downloaded {len(content)} bytes for: {file_info['name']}")
                return content
            else:
                logger.error(f"Failed to download file: {download_response.status_code}")
                return None
            
        except Exception as e:
            logger.error(f"Error downloading file {file_info['name']}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None


    def _convert_to_markdown(self, file_content: bytes, filename: str, mime_type: str) -> str:
        """Конвертировать содержимое файла в Markdown"""
        try:
            logger.info(f"Converting {filename} (type: {mime_type}, size: {len(file_content)} bytes)")
        
            # Для текстовых файлов
            if mime_type in ['text/plain', 'text/csv', 'text/markdown'] or filename.endswith(('.txt', '.md', '.csv')):
                try:
                    text = file_content.decode('utf-8')
                    logger.info(f"Decoded text file: {filename}")
                    return text
                except UnicodeDecodeError:
                    text = file_content.decode('utf-8', errors='replace')
                    logger.warning(f"Decoded text file with errors: {filename}")
                    return text
                
            # Для остальных форматов используем универсальный конвертер
            if self.universal_converter:
                logger.info(f"Using universal converter for: {filename}")
                success, content = self.universal_converter.convert(file_content, filename)
                if success:
                    logger.info(f"Successfully converted: {filename}")
                    return content
                else:
                    logger.warning(f"Universal converter failed for: {filename}")
        
            # Если конвертер недоступен или не смог конвертировать
            return f"*File type {mime_type} could not be converted. Please install necessary converters.*"
        
        except Exception as e:
            logger.error(f"Error converting file {filename} to markdown: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return f"*Conversion error: {str(e)}*"




    # Также обновим метод _process_file для лучшего логирования
    def _process_file(self, file_info: Dict) -> Tuple[Dict, str]:
        """Обработать отдельный файл и вернуть его метаданные и контент"""
        metadata = {
            'name': file_info['name'],
            'path': file_info['path'],
            'mime_type': file_info.get('mime_type', 'unknown'),
            'size': file_info.get('size', 0),
            'modified': file_info.get('modified')
        }
    
        try:
            logger.info(f"Processing file: {file_info['name']} (type: {file_info.get('mime_type')})")
        
            # Скачиваем файл
            file_content = self._download_file(file_info)
        
            if not file_content:
                logger.error(f"Failed to download: {file_info['name']}")
                return metadata, "*Failed to download file*"
        
            logger.info(f"Downloaded {len(file_content)} bytes for: {file_info['name']}")
        
            # Конвертируем в Markdown
            markdown_content = self._convert_to_markdown(
                file_content, 
                file_info['name'], 
                file_info.get('mime_type', 'application/octet-stream')
            )
        
            metadata['processed_successfully'] = True
            metadata['content_length'] = len(markdown_content)
        
            logger.info(f"Successfully processed: {file_info['name']} (content: {len(markdown_content)} chars)")
        
            return metadata, markdown_content
        
        except Exception as e:
            logger.error(f"Error processing file {file_info['path']}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            metadata['processed_successfully'] = False
            metadata['error'] = str(e)
            return metadata, f"*Error processing file: {str(e)}*"    

  
    def _format_size(self, size_bytes: int) -> str:
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
                    logger.info("Folder has been modified")
                    return True
            
            # Также можно проверить отдельные файлы, но это требует много запросов
            # Для оптимизации полагаемся на дату изменения папки
            
        except Exception as e:
            logger.error(f"Error checking folder updates: {e}")
            return True
        
        return False

    def get_folder_files_list(self, folder_path: str) -> List[Dict]:
        """
        Получить только список файлов без загрузки контента
        Используется для обработки папок по файлам
        """
        return self._get_all_files_recursive(folder_path, "")

    def process_single_file(self, file_info: Dict) -> Tuple[Dict, str]:
        """
        Обработать один конкретный файл
        """
        return self._process_file(file_info)