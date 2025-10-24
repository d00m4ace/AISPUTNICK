# code/agents/gdrive_downloader.py

import os
import io
import re
import json
import tempfile
import aiohttp
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Опциональный импорт Google API
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    logger.warning("Google API библиотеки не установлены. Используйте: pip install google-api-python-client google-auth")

class GoogleDriveDownloader:
    """Класс для скачивания файлов с Google Drive"""
    
    def __init__(self, api_key: str = None, service_account_file: str = None):
        """
        Инициализация загрузчика
        
        Args:
            api_key: API ключ Google (устарел, используйте service_account_file)
            service_account_file: Путь к JSON файлу service account
        """
        self.api_key = api_key
        self.service_account_file = service_account_file
        self.service = None
        
        if GOOGLE_API_AVAILABLE:
            # Приоритет: service account > api key
            if service_account_file and os.path.exists(service_account_file):
                try:
                    # Используем Service Account
                    credentials = service_account.Credentials.from_service_account_file(
                        service_account_file,
                        scopes=['https://www.googleapis.com/auth/drive.readonly']
                    )
                    self.service = build('drive', 'v3', credentials=credentials)
                    logger.info(f"Google Drive API инициализирован с Service Account: {service_account_file}")
                except Exception as e:
                    logger.error(f"Ошибка инициализации с Service Account: {e}")
                    
            elif api_key:
                try:
                    # Fallback на API key
                    self.service = build('drive', 'v3', developerKey=api_key)
                    logger.info("Google Drive API инициализирован с API ключом")
                except Exception as e:
                    logger.error(f"Ошибка инициализации с API ключом: {e}")
            else:
                logger.info("Нет учетных данных для Google Drive API, используется fallback метод")
        else:
            logger.info("Google API библиотеки не установлены, используется fallback метод")
    
    def extract_file_id(self, url: str) -> Optional[str]:
        """Извлекает ID файла из URL Google Drive"""
        patterns = [
            r'/file/d/([a-zA-Z0-9-_]+)',
            r'id=([a-zA-Z0-9-_]+)',
            r'/d/([a-zA-Z0-9-_]+)',
            r'/open\?id=([a-zA-Z0-9-_]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    async def download_file(self, url: str, max_size: int = 104857600) -> Optional[Dict[str, Any]]:
        """
        Скачивает файл с Google Drive
        
        Args:
            url: URL файла на Google Drive
            max_size: Максимальный размер файла в байтах (по умолчанию 100MB)
            
        Returns:
            Dict с информацией о файле и путём к временному файлу
        """
        if self.service and GOOGLE_API_AVAILABLE:
            return await self._download_with_api(url, max_size)
        else:
            return await self._download_fallback(url, max_size)
    
    async def _download_with_api(self, url: str, max_size: int) -> Optional[Dict[str, Any]]:
        """Скачивание через официальный API"""
        file_id = self.extract_file_id(url)
        if not file_id:
            logger.error(f"Не удалось извлечь ID из URL: {url}")
            return None
        
        try:
            # Получаем метаданные файла
            file_metadata = self.service.files().get(
                fileId=file_id,
                fields='id, name, size, mimeType, md5Checksum',
                supportsAllDrives=True  # Поддержка shared drives
            ).execute()
            
            file_name = file_metadata.get('name', f'file_{file_id}')
            file_size = int(file_metadata.get('size', 0))
            mime_type = file_metadata.get('mimeType', 'application/octet-stream')
            
            if file_size > max_size:
                logger.warning(f"Файл слишком большой: {file_size} байт (макс: {max_size})")
                return None
            
            logger.info(f"Скачивание файла: {file_name} ({file_size} байт)")
            
            # Проверяем, не является ли это Google Docs/Sheets/Slides
            google_mime_types = {
                'application/vnd.google-apps.document': ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx'),
                'application/vnd.google-apps.spreadsheet': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx'),
                'application/vnd.google-apps.presentation': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx'),
                'application/vnd.google-apps.drawing': ('application/pdf', '.pdf'),
            }
            
            if mime_type in google_mime_types:
                # Экспортируем Google документ в соответствующий формат
                export_mime_type, extension = google_mime_types[mime_type]
                request = self.service.files().export_media(
                    fileId=file_id,
                    mimeType=export_mime_type
                )
                if not file_name.endswith(extension):
                    file_name = f"{file_name}{extension}"
                logger.info(f"Экспорт Google документа как {export_mime_type}")
            else:
                # Обычный файл - скачиваем как есть
                request = self.service.files().get_media(fileId=file_id)
            
            # Создаём временный файл
            suffix = os.path.splitext(file_name)[1] if '.' in file_name else ''
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            temp_path = temp_file.name
            
            # Скачиваем по частям
            fh = io.FileIO(temp_path, 'wb')
            downloader = MediaIoBaseDownload(fh, request, chunksize=1024*1024)  # 1MB chunks
            
            done = False
            downloaded = 0
            
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    downloaded = int(status.progress() * file_size) if file_size > 0 else 0
                    if downloaded > 0:
                        logger.debug(f"Скачано {downloaded}/{file_size} байт ({int(status.progress() * 100)}%)")
                    
                    # Проверяем, не превысили ли лимит
                    if downloaded > max_size:
                        fh.close()
                        os.remove(temp_path)
                        logger.warning(f"Превышен лимит размера при скачивании")
                        return None
            
            fh.close()
            
            # Получаем реальный размер скачанного файла
            actual_size = os.path.getsize(temp_path)
            logger.info(f"Файл успешно скачан: {temp_path} ({actual_size} байт)")
            
            return {
                'path': temp_path,
                'name': file_name,
                'size': actual_size,
                'mime_type': mime_type,
                'file_id': file_id
            }
            
        except HttpError as e:
            if e.resp.status == 404:
                logger.error(f"Файл не найден: {file_id}")
            elif e.resp.status == 403:
                logger.error(f"Доступ запрещён к файлу: {file_id}. Возможно, файл не публичный или нет прав доступа")
            else:
                logger.error(f"HTTP ошибка при скачивании: {e}")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при скачивании файла через API: {e}", exc_info=True)
            return None
    
    async def _download_fallback(self, url: str, max_size: int) -> Optional[Dict[str, Any]]:
        """Fallback метод для скачивания публичных файлов без API"""
        file_id = self.extract_file_id(url)
        if not file_id:
            logger.error(f"Не удалось извлечь ID файла из URL: {url}")
            return None
        
        download_url = f'https://drive.google.com/uc?export=download&id={file_id}'
        
        timeout = aiohttp.ClientTimeout(total=60)
        cookies = aiohttp.CookieJar()
        
        async with aiohttp.ClientSession(timeout=timeout, cookie_jar=cookies) as session:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                # Первый запрос
                async with session.get(download_url, headers=headers) as response:
                    # Проверяем первые байты
                    first_chunk = await response.content.read(1024)
                    
                    if first_chunk.startswith(b'<!DOCTYPE') or b'<html' in first_chunk.lower():
                        # HTML страница - ищем токен подтверждения
                        remaining = await response.read()
                        content_str = (first_chunk + remaining).decode('utf-8', errors='ignore')
                        
                        # Ищем токен подтверждения для больших файлов
                        token_patterns = [
                            r'confirm=([0-9A-Za-z_-]+)',
                            r'"downloadWarning"[^>]*?confirm=([0-9A-Za-z_-]+)',
                            r'confirm&amp;t=([0-9A-Za-z_-]+)',
                            r'/uc\?export=download&amp;confirm=([0-9A-Za-z_-]+)',
                        ]
                        
                        confirm_token = None
                        for pattern in token_patterns:
                            match = re.search(pattern, content_str)
                            if match:
                                confirm_token = match.group(1)
                                break
                        
                        if confirm_token:
                            # Скачиваем с токеном подтверждения
                            confirmed_url = f"{download_url}&confirm={confirm_token}"
                            logger.info(f"Используем токен подтверждения: {confirm_token[:10]}...")
                            
                            async with session.get(confirmed_url, headers=headers) as conf_response:
                                if conf_response.status == 200:
                                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.tmp')
                                    temp_path = temp_file.name
                                    
                                    downloaded = 0
                                    async for chunk in conf_response.content.iter_chunked(8192):
                                        downloaded += len(chunk)
                                        if downloaded > max_size:
                                            temp_file.close()
                                            os.remove(temp_path)
                                            logger.warning(f"Превышен лимит размера: {downloaded} > {max_size}")
                                            return None
                                        temp_file.write(chunk)
                                    
                                    temp_file.close()
                                    
                                    # Получаем имя файла из заголовков
                                    file_name = self._extract_filename_from_headers(conf_response.headers)
                                    if not file_name:
                                        file_name = f"gdrive_{file_id[:8]}"
                                    
                                    logger.info(f"Файл скачан через fallback: {temp_path} ({downloaded} байт)")
                                    
                                    return {
                                        'path': temp_path,
                                        'name': file_name,
                                        'size': downloaded,
                                        'mime_type': 'application/octet-stream',
                                        'file_id': file_id
                                    }
                        else:
                            logger.error("Не найден токен подтверждения в HTML")
                        
                        return None
                    
                    else:
                        # Это не HTML - скачиваем напрямую
                        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.tmp')
                        temp_path = temp_file.name
                        
                        temp_file.write(first_chunk)
                        downloaded = len(first_chunk)
                        
                        async for chunk in response.content.iter_chunked(8192):
                            downloaded += len(chunk)
                            if downloaded > max_size:
                                temp_file.close()
                                os.remove(temp_path)
                                return None
                            temp_file.write(chunk)
                        
                        temp_file.close()
                        
                        file_name = self._extract_filename_from_headers(response.headers)
                        if not file_name:
                            file_name = f"gdrive_{file_id[:8]}"
                        
                        logger.info(f"Файл скачан напрямую: {temp_path} ({downloaded} байт)")
                        
                        return {
                            'path': temp_path,
                            'name': file_name,
                            'size': downloaded,
                            'mime_type': 'application/octet-stream',
                            'file_id': file_id
                        }
                        
            except Exception as e:
                logger.error(f"Ошибка fallback скачивания: {e}", exc_info=True)
                return None
    
    def _extract_filename_from_headers(self, headers) -> Optional[str]:
        """Извлекает имя файла из заголовков ответа"""
        content_disp = headers.get('Content-Disposition', '')
        if content_disp:
            patterns = [
                r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\n]+)',
                r'filename=([^;]+)'
            ]
            for pattern in patterns:
                match = re.search(pattern, content_disp, re.IGNORECASE)
                if match:
                    from urllib.parse import unquote
                    filename = unquote(match.group(1).strip())
                    if filename:
                        return filename
        return None