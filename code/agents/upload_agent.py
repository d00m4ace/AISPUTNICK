# code/agents/upload_agent.py

import os
import json
import logging
import aiohttp
import asyncio
import tempfile
import mimetypes
import requests
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse, unquote
from aiogram import types
from aiogram.fsm.context import FSMContext
from utils.markdown_utils import escape_markdown_v2

# Импортируем Google Drive загрузчик
try:
    from agents.gdrive_downloader import GoogleDriveDownloader
except ImportError:
    GoogleDriveDownloader = None

logger = logging.getLogger(__name__)

class UploadAgent:
    """Агент для скачивания файлов по ссылкам и их обработки"""
    
    def __init__(self):
        self.name = "upload"
        self.config = self._load_default_config()
        self.active_downloads = {}  # Активные загрузки
        
        # Инициализируем Google Drive загрузчик если доступен
        self.gdrive_downloader = None
        if GoogleDriveDownloader:
            # Определяем путь к service account файлу
            service_account_file = self.config.get('google_service_account_file')
            if service_account_file:
                # Если это относительный путь, ищем относительно папки конфига
                if not os.path.isabs(service_account_file):
                    config_dir = os.path.dirname(__file__)
                    # Проверяем в папке agents
                    possible_paths = [
                        os.path.join(config_dir, service_account_file),
                        os.path.join(config_dir, 'configs', service_account_file),
                        os.path.join(os.path.dirname(config_dir), service_account_file),
                        service_account_file  # На случай если файл в корне проекта
                    ]
                    for path in possible_paths:
                        if os.path.exists(path):
                            service_account_file = path
                            break
            
            # Инициализация с Service Account или API ключом
            api_key = self.config.get('google_api_key')
            
            if service_account_file and os.path.exists(service_account_file):
                self.gdrive_downloader = GoogleDriveDownloader(
                    service_account_file=service_account_file
                )
                logger.info(f"Google Drive загрузчик инициализирован с Service Account: {service_account_file}")
            elif api_key:
                self.gdrive_downloader = GoogleDriveDownloader(api_key=api_key)
                logger.info("Google Drive загрузчик инициализирован с API ключом")
            else:
                self.gdrive_downloader = GoogleDriveDownloader()
                logger.info("Google Drive загрузчик работает в fallback режиме (только публичные файлы)")
        else:
            logger.warning("GoogleDriveDownloader не найден, Google Drive поддержка ограничена")
        
    def _load_default_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации по умолчанию"""
        config_path = os.path.join(os.path.dirname(__file__), "configs", "upload_default.json")
        
        default_config = {
            "name": "upload",
            "type": "downloader",
            "description": "Скачивание и обработка файлов из интернета",
            "max_file_size": 104857600,  # 100MB
            "timeout": 60,  # таймаут скачивания в секундах
            "chunk_size": 8192,  # размер чанка при скачивании
            "allowed_protocols": ["http", "https"],
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "google_api_key": os.getenv('GOOGLE_API_KEY', '')  # API ключ из переменной окружения
        }
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    default_config.update(loaded_config)
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига Upload агента: {e}")
                
        return default_config
    
    def get_config(self) -> Dict[str, Any]:
        """Получение конфигурации агента"""
        return self.config.copy()
    
    def set_config(self, config: Dict[str, Any]):
        """Установка новой конфигурации"""
        self.config = config
        # Переинициализируем Google Drive загрузчик с новым ключом
        if GoogleDriveDownloader and 'google_api_key' in config:
            self.gdrive_downloader = GoogleDriveDownloader(config['google_api_key'])
    
    async def process(self, user_id: str, query: str, context: Dict[str, Any]) -> Tuple[bool, str]:
        """Обработка запроса к агенту"""
        if not query:
            return False, "⚠️ Укажите URL файла для скачивания\n\nПример: `@upload https://example.com/file.pdf`"
        
        # Извлекаем URL из запроса
        url = self._extract_url(query)
        if not url:
            return False, "⚠️ Не найден валидный URL в запросе\n\nУкажите прямую ссылку на файл"
        
        # Преобразуем URL облачных сервисов (кроме Google Drive)
        url = self._convert_cloud_url(url)
        
        # Проверяем протокол
        parsed_url = urlparse(url)
        if parsed_url.scheme not in self.config.get('allowed_protocols', ['http', 'https']):
            return False, f"⚠️ Протокол {parsed_url.scheme} не поддерживается\n\nИспользуйте HTTP или HTTPS ссылки"
        
        # Получаем компоненты из контекста
        codebase_manager = context.get('codebase_manager')
        file_manager = context.get('file_manager')
        message = context.get('message')
        
        if not all([codebase_manager, file_manager, message]):
            return False, "⚠️ Ошибка инициализации агента"
        
        # Проверяем наличие активной кодовой базы
        user_codebases = await codebase_manager.get_user_codebases(user_id)
        active_codebase_id = user_codebases.get('active')
        
        if not active_codebase_id:
            return False, (
                "⚠️ Нет активной кодовой базы\\.\n\n"
                "Создайте или выберите кодовую базу:\n"
                "/create\\_codebase \\- создать новую\n"
                "/codebases \\- список баз"
            )
        
        # Проверяем что база не devnull и не системная
        codebase_info = await codebase_manager.get_codebase_config(user_id, active_codebase_id)
        if codebase_info:
            if codebase_info.get("is_system") or codebase_info.get("folder_name") == "devnull":
                logger.warning(f"Попытка загрузки в системную базу devnull пользователем {user_id}")
                return False, (
                    "⚠️ Недопустимая активная база\n\n"
                    "База `devnull` и другие системные базы не предназначены для сохранения файлов\\.\n"
                    "Создайте или выберите другую кодовую базу:\n"
                    "/create\\_codebase \\- создать новую\n"
                    "/codebases \\- список баз"
                )

        # Проверяем права доступа для публичных баз
        # Запрет загрузки в чужие публичные базы
        if codebase_info.get("is_public") and codebase_info.get("owner_id") != user_id:
            owner_name = "Неизвестен"
            if "user_manager" in context and context["user_manager"]:
                owner_data = await context["user_manager"].get_user(codebase_info.get("owner_id"))
                if owner_data:
                    first_name = owner_data.get("name", "")
                    last_name = owner_data.get("surname", "")
                    username = owner_data.get("telegram_username", "")
                    if first_name or last_name:
                        owner_name = f"{first_name} {last_name}".strip()
                    elif username and username != "Не указан":
                        owner_name = f"@{username}"
                    else:
                        owner_name = f"User_{codebase_info.get('owner_id', '')[:8]}"

            return False, (
                f"⚠️ Недостаточно прав\n\n"
                f"Активная база: `{escape_markdown_v2(codebase_info.get('name', active_codebase_id))}` \\(публичная\\)\n"
                f"Владелец: {escape_markdown_v2(owner_name)}\n\n"
                f"Вы не можете добавлять файлы в чужую публичную базу\\.\n"
                f"Переключитесь на свою базу или создайте новую\\."
            )

        # Скачиваем и обрабатываем файл
        success, result = await self._download_and_process(
            url, user_id, active_codebase_id, 
            context, message
        )
        
        return success, result
    
    def _extract_url(self, text: str) -> Optional[str]:
        """Извлекает URL из текста"""
        import re
        # Простой паттерн для поиска URL
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, text)
        return urls[0] if urls else None
    
    def _convert_cloud_url(self, url: str) -> str:
        """Преобразует URL облачных сервисов в прямые ссылки для скачивания"""
        import re
        
        # Google Drive - обрабатывается отдельно через API
        if 'drive.google.com' in url or 'docs.google.com' in url:
            return url  # Возвращаем как есть, обработаем через API
        
        # Dropbox
        elif 'dropbox.com' in url:
            # Заменяем dl=0 на dl=1 или добавляем dl=1
            if '?dl=0' in url:
                return url.replace('?dl=0', '?dl=1')
            elif '?' in url:
                return url + '&dl=1'
            else:
                return url + '?dl=1'
        
        # GitHub
        elif 'github.com' in url and '/blob/' in url:
            # Конвертируем blob URL в raw URL
            return url.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
        
        # Yandex.Disk
        elif 'disk.yandex' in url or 'yadi.sk' in url:
            try:
                api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
                params = {"public_key": url}
                resp = requests.get(api_url, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    href = data.get("href")
                    if href:
                        return href
            except Exception as e:
                logger.error(f"Ошибка получения прямой ссылки с Яндекс.Диска: {e}")
                # fallback – хотя часто вернёт HTML
                if '?' in url:
                    return url + '&download=1'
                else:
                    return url + '?download=1'
        
        # Если не распознан облачный сервис, возвращаем как есть
        return url
    
    def _guess_filename_from_url(self, url: str, response_headers: dict = None) -> str:
        """Пытается определить имя файла из URL или заголовков ответа"""
        import re
        from urllib.parse import unquote
        
        # Сначала пробуем получить из заголовков ответа
        if response_headers:
            # Content-Disposition header
            content_disp = response_headers.get('Content-Disposition', '')
            if content_disp:
                # filename="example.pdf" или filename*=UTF-8''example.pdf
                patterns = [
                    r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\n]+)',
                    r'filename=([^;]+)'
                ]
                for pattern in patterns:
                    match = re.search(pattern, content_disp, re.IGNORECASE)
                    if match:
                        filename = unquote(match.group(1).strip())
                        if filename:
                            return filename
        
        # Для Google Drive файлов пробуем получить имя из URL параметров
        if 'drive.google.com' in url or 'docs.google.com' in url:
            # Часто имя файла недоступно из URL Google Drive
            # Используем ID файла как временное имя
            file_id_match = re.search(r'[?&]id=([a-zA-Z0-9-_]+)', url)
            if not file_id_match:
                file_id_match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
            
            if file_id_match:
                return f"gdrive_{file_id_match.group(1)[:8]}"
        
        # Стандартный метод - из пути URL
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = os.path.basename(path)
        
        if not filename or '.' not in filename:
            # Если имя файла не определено, используем хэш URL
            import hashlib
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f"download_{url_hash}"
        
        return filename
    
    async def _download_and_process(self, url: str, user_id: str, codebase_id: str,
                                   context: Dict[str, Any], message: types.Message) -> Tuple[bool, str]:
        """Скачивает файл и обрабатывает его"""
        temp_file = None
        processing_msg = None
        
        try:
            # Отправляем уведомление о начале загрузки
            filename = self._guess_filename_from_url(url)
            processing_msg = await message.reply(
                f"🔥 *Загрузка файла*\n\n"
                f"URL: `{escape_markdown_v2(url[:50] + '...' if len(url) > 50 else url)}`\n"
                f"Файл: `{escape_markdown_v2(filename)}`\n\n"
                f"⏳ Скачивание\\.\\.\\.",
                parse_mode="MarkdownV2"
            )
            
            # Скачиваем файл
            download_result = await self._download_file(url)
            
            if isinstance(download_result, dict):
                # Если вернулся словарь (от Google Drive API)
                temp_file = download_result['path']
                filename = download_result.get('name', filename)
                file_size = download_result.get('size', 0)
                mime_type = download_result.get('mime_type', 'application/octet-stream')
                
                # Читаем файл
                with open(temp_file, 'rb') as f:
                    file_bytes = f.read()
                    
            elif download_result:
                # Если вернулся путь к файлу (обычная загрузка)
                temp_file = download_result
                file_size = os.path.getsize(temp_file)
                
                if file_size == 0:
                    if processing_msg:
                        await processing_msg.edit_text(
                            "⌛ *Скачан пустой файл*\n\n"
                            "Возможные причины:\n"
                            "• Файл защищён паролем\n"
                            "• Требуется авторизация\n"
                            "• Ссылка недействительна\n\n"
                            "Попробуйте открыть файл в браузере и убедиться что он доступен",
                            parse_mode="MarkdownV2"
                        )
                    if temp_file and os.path.exists(temp_file):
                        os.remove(temp_file)
                    return False, "Файл пустой"
                
                # Читаем содержимое файла
                with open(temp_file, 'rb') as f:
                    file_bytes = f.read()
                
                # Определяем тип по содержимому (более надежно)
                mime_type = self._detect_mime_type(file_bytes)
                
            else:
                # Ошибка загрузки
                error_msg = (
                    "⌛ *Ошибка скачивания файла*\n\n"
                    "Возможные причины:\n"
                    "• Файл защищён или требует авторизации\n"
                    "• Превышен размер файла \\(макс 50 МБ\\)\n"
                    "• Неверная или устаревшая ссылка\n"
                    "• Файл был удалён\n\n"
                )
                
                if 'drive.google.com' in url:
                    error_msg += (
                        "Для Google Drive:\n"
                        "• Убедитесь что файл открыт для всех по ссылке\n"
                        "• Попробуйте скопировать ссылку заново\n"
                    )
                
                if processing_msg:
                    await processing_msg.edit_text(error_msg, parse_mode="MarkdownV2")
                return False, "Не удалось скачать файл"
            
            # Определяем расширение на основе MIME типа
            mime_to_ext = {
                'application/pdf': '.pdf',
                'image/png': '.png',
                'image/jpeg': '.jpg',
                'image/gif': '.gif',
                'image/bmp': '.bmp',
                'image/tiff': '.tiff',
                'image/webp': '.webp',
                'audio/mpeg': '.mp3',
                'audio/ogg': '.ogg',
                'audio/wav': '.wav',
                'audio/flac': '.flac',
                'audio/mp4': '.m4a',
                'audio/x-aac': '.aac',
                'audio/aiff': '.aiff',
                'video/mp4': '.mp4',
                'video/webm': '.webm',
                'video/avi': '.avi',
                'application/zip': '.zip',
                'application/x-7z-compressed': '.7z',
                'application/x-rar-compressed': '.rar',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
                'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
                'application/msword': '.doc',
                'application/vnd.ms-excel': '.xls',
                'application/vnd.ms-powerpoint': '.ppt',
                'text/html': '.html',
                'text/xml': '.xml',
                'application/json': '.json',
                'text/plain': '.txt',
                'application/octet-stream': ''
            }
            extension = mime_to_ext.get(mime_type, '')
            
            # Корректируем имя файла если нужно
            if not filename.endswith(extension) and extension:
                # Если имя файла не имеет правильного расширения
                if '.' in filename:
                    base_name = filename.rsplit('.', 1)[0]
                else:
                    base_name = filename
                filename = f"{base_name}{extension}"
            
            # Для Google Drive файлов с временным именем
            if filename.startswith('gdrive_') and extension:
                # Генерируем более осмысленное имя
                import hashlib
                file_hash = hashlib.md5(file_bytes[:1024]).hexdigest()[:8]
                if mime_type.startswith('audio/'):
                    filename = f"audio_{file_hash}{extension}"
                elif mime_type.startswith('image/'):
                    filename = f"image_{file_hash}{extension}"
                elif mime_type.startswith('video/'):
                    filename = f"video_{file_hash}{extension}"
                elif mime_type == 'application/pdf':
                    filename = f"document_{file_hash}.pdf"
                else:
                    filename = f"file_{file_hash}{extension}"
            
            if processing_msg:
                await processing_msg.edit_text(
                    f"🔥 *Обработка файла*\n\n"
                    f"Файл: `{escape_markdown_v2(filename)}`\n"
                    f"Размер: {file_size // 1024} КБ\n"
                    f"Тип: {escape_markdown_v2(mime_type.split('/')[0] if mime_type else 'неизвестный')}\n\n"
                    f"🔄 Обработка\\.\\.\\.",
                    parse_mode="MarkdownV2"
                )
            
            # Обрабатываем файл в зависимости от типа
            result = await self._process_file_by_type(
                filename, file_bytes, mime_type,
                user_id, codebase_id, context,
                processing_msg, message
            )
            
            return result
            
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка сети при скачивании: {e}")
            error_msg = f"⌛ Ошибка сети: {str(e)}"
            if processing_msg:
                await processing_msg.edit_text(escape_markdown_v2(error_msg), parse_mode="MarkdownV2")
            return False, error_msg
            
        except Exception as e:
            logger.error(f"Ошибка обработки файла: {e}", exc_info=True)
            error_msg = f"⌛ Ошибка: {str(e)}"
            if processing_msg:
                await processing_msg.edit_text(escape_markdown_v2(error_msg), parse_mode="MarkdownV2")
            return False, str(e)
            
        finally:
            # Удаляем временный файл
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as e:
                    logger.debug(f"Не удалось удалить временный файл: {e}")
    
    async def _download_file(self, url: str) -> Optional[Any]:
        """Скачивает файл по URL во временный файл"""
        
        # Если это Google Drive и у нас есть загрузчик, используем его
        if ('drive.google.com' in url or 'docs.google.com' in url):
            if self.gdrive_downloader:
                logger.info("Используем Google Drive загрузчик")
                result = await self.gdrive_downloader.download_file(
                    url=url,
                    max_size=self.config.get('max_file_size', 52428800)
                )
                return result  # Возвращает словарь с информацией или None
            else:
                logger.warning("Google Drive загрузчик недоступен, пытаемся обычный метод")
        
        # Для всех остальных файлов (и как fallback для Google Drive)
        timeout = aiohttp.ClientTimeout(total=self.config.get('timeout', 60))
        chunk_size = self.config.get('chunk_size', 8192)
        max_size = self.config.get('max_file_size', 52428800)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                # Добавляем заголовки как у браузера
                headers = {
                    'User-Agent': self.config.get('user_agent', 'Mozilla/5.0'),
                    'Accept': '*/*',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                }
                
                async with session.get(url, headers=headers, allow_redirects=True) as response:
                    response.raise_for_status()
                    
                    # Проверяем размер файла
                    content_length = response.headers.get('Content-Length')
                    if content_length and int(content_length) > max_size:
                        logger.warning(f"Файл слишком большой: {content_length} байт")
                        return None
                    
                    # Создаем временный файл
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.tmp')
                    temp_path = temp_file.name
                    
                    # Скачиваем по частям
                    downloaded = 0
                    async for chunk in response.content.iter_chunked(chunk_size):
                        downloaded += len(chunk)
                        if downloaded > max_size:
                            temp_file.close()
                            os.remove(temp_path)
                            logger.warning(f"Превышен лимит размера при скачивании: {downloaded} байт")
                            return None
                        temp_file.write(chunk)
                    
                    temp_file.close()
                    
                    # Проверяем что файл не пустой
                    if os.path.getsize(temp_path) == 0:
                        os.remove(temp_path)
                        return None
                    
                    return temp_path
                    
            except Exception as e:
                logger.error(f"Ошибка скачивания файла: {e}", exc_info=True)
                return None
    
    def _detect_mime_type(self, file_bytes: bytes) -> str:
        """Определяет MIME тип по содержимому файла"""
        # Проверяем магические байты для различных форматов
        
        # PDF
        if file_bytes.startswith(b'%PDF'):
            return 'application/pdf'
        
        # Изображения
        elif file_bytes.startswith(b'\x89PNG'):
            return 'image/png'
        elif file_bytes.startswith(b'\xFF\xD8\xFF'):
            return 'image/jpeg'
        elif file_bytes.startswith(b'GIF8'):
            return 'image/gif'
        elif file_bytes.startswith(b'BM'):
            return 'image/bmp'
        elif file_bytes.startswith(b'II\x2A\x00') or file_bytes.startswith(b'MM\x00\x2A'):
            return 'image/tiff'
        elif file_bytes.startswith(b'RIFF') and b'WEBP' in file_bytes[:12]:
            return 'image/webp'
        
        # Аудио форматы
        elif file_bytes.startswith(b'ID3') or file_bytes.startswith(b'\xFF\xFB') or file_bytes.startswith(b'\xFF\xF3') or file_bytes.startswith(b'\xFF\xF2'):
            return 'audio/mpeg'  # MP3
        elif file_bytes.startswith(b'OggS'):
            # Проверяем, что это именно аудио Ogg
            if b'vorbis' in file_bytes[:100].lower() or b'opus' in file_bytes[:100].lower():
                return 'audio/ogg'
            else:
                return 'application/ogg'
        elif file_bytes.startswith(b'RIFF') and b'WAVE' in file_bytes[:12]:
            return 'audio/wav'
        elif file_bytes.startswith(b'fLaC'):
            return 'audio/flac'
        elif b'ftypM4A' in file_bytes[:32] or b'ftyp' in file_bytes[:12]:
            # M4A/MP4 audio
            if b'M4A' in file_bytes[:32] or b'm4a' in file_bytes[:32]:
                return 'audio/mp4'
            elif b'mp4' in file_bytes[:32] or b'isom' in file_bytes[:32]:
                return 'audio/mp4'
        
        # Видео форматы
        elif file_bytes.startswith(b'\x00\x00\x00\x14ftyp'):
            return 'video/mp4'
        elif file_bytes.startswith(b'\x1A\x45\xDF\xA3'):
            return 'video/webm'
        elif file_bytes.startswith(b'RIFF') and b'AVI ' in file_bytes[:12]:
            return 'video/avi'
        
        # Архивы
        elif file_bytes.startswith(b'PK\x03\x04'):
            # Может быть zip, docx, xlsx, pptx и др.
            content_str = str(file_bytes[:1000])
            if 'word/' in content_str:
                return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            elif 'xl/' in content_str:
                return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            elif 'ppt/' in content_str:
                return 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
            else:
                return 'application/zip'
        elif file_bytes.startswith(b'7z\xBC\xAF\x27\x1C'):
            return 'application/x-7z-compressed'
        elif file_bytes.startswith(b'Rar!'):
            return 'application/x-rar-compressed'
        
        # Microsoft Office старые форматы
        elif file_bytes.startswith(b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'):
            # OLE2 формат
            if b'Word.Document' in file_bytes[:2000]:
                return 'application/msword'
            elif b'Excel' in file_bytes[:2000] or b'Workbook' in file_bytes[:2000]:
                return 'application/vnd.ms-excel'
            elif b'PowerPoint' in file_bytes[:2000]:
                return 'application/vnd.ms-powerpoint'
            else:
                return 'application/octet-stream'
        
        # HTML
        elif file_bytes.startswith(b'<!DOCTYPE') or file_bytes.startswith(b'<html') or file_bytes.startswith(b'<HTML'):
            return 'text/html'
        
        # XML
        elif file_bytes.startswith(b'<?xml'):
            return 'text/xml'
        
        # JSON
        elif file_bytes.startswith(b'{') or file_bytes.startswith(b'['):
            try:
                import json
                json.loads(file_bytes.decode('utf-8'))
                return 'application/json'
            except:
                pass
        
        # По умолчанию пытаемся определить как текст
        try:
            file_bytes[:1000].decode('utf-8')
            return 'text/plain'
        except:
            return 'application/octet-stream'
    
    async def _process_file_by_type(self, filename: str, file_bytes: bytes,
                                   mime_type: str, user_id: str, codebase_id: str,
                                   context: Dict[str, Any], processing_msg: types.Message,
                                   original_message: types.Message) -> Tuple[bool, str]:
        """Обрабатывает файл в зависимости от его типа"""
        file_manager = context.get('file_manager')
        
        # Получаем процессоры из upload_handler если они доступны
        upload_handler = context.get('upload_handler')
        
        # Проверяем тип файла и обрабатываем соответственно
        ext = os.path.splitext(filename.lower())[1]
        
        # Аудио файлы
        if mime_type and mime_type.startswith('audio/'):
            if upload_handler and hasattr(upload_handler, 'audio_processor'):
                await processing_msg.edit_text(
                    f"🎵 *Обработка аудио*\n\n"
                    f"Файл: `{escape_markdown_v2(filename)}`\n"
                    f"Конвертация в текст\\.\\.\\.",
                    parse_mode="MarkdownV2"
                )
                
                # Используем audio processor из upload_handler
                state = FSMContext(storage=None, key=None)  # Временный state
                
                await upload_handler.audio_processor.process_audio_file(
                    original_message, processing_msg, filename, file_bytes,
                    user_id, codebase_id, state
                )
                return True, "✅ Транскрипция аудио файла сохранена"
            else:
                # Fallback - сохраняем только информацию о файле, но не сам аудио
                from datetime import datetime
                logger.warning("Аудио процессор недоступен, сохраняем информацию о файле")
                
                await processing_msg.edit_text(
                    f"💾 *Сохранение информации об аудио*\n\n"
                    f"Файл: `{escape_markdown_v2(filename)}`\n"
                    f"Размер: {len(file_bytes) // 1024} КБ\n\n"
                    f"⚠️ Транскрипция недоступна",
                    parse_mode="MarkdownV2"
                )
                
                # НЕ сохраняем сам аудио файл
                # Создаем только информационный файл
                info_filename = f"{os.path.splitext(filename)[0]}_info.txt"
                info_content = f"""Информация об аудио файле
========================

Оригинальный файл: {filename}
Размер: {len(file_bytes) // 1024} КБ ({len(file_bytes)} байт)
Тип: {mime_type}
Дата загрузки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Статус: Аудио файл НЕ сохранен в базу
Причина: Транскрипция недоступна (нет OpenAI API ключа)

Примечание: 
Для транскрипции аудио необходимо:
1. Настроить OpenAI API ключ в конфигурации бота
2. Или отправить аудио файл боту напрямую при настроенном API
3. Или использовать внешние сервисы транскрипции

Файл был скачан через @upload агент, но не сохранен для экономии места.
"""
                
                success, msg, _ = await file_manager.save_file(
                    user_id=user_id,
                    codebase_id=codebase_id,
                    filename=info_filename,
                    file_data=info_content.encode('utf-8'),
                    skip_conversion=True
                )
                
                if success:
                    await processing_msg.edit_text(
                        f"📝 *Информация об аудио сохранена*\n\n"
                        f"Оригинал: `{escape_markdown_v2(filename)}`\n"
                        f"Размер: {len(file_bytes) // 1024} КБ\n\n"
                        f"📄 Файл с информацией:\n`{escape_markdown_v2(info_filename)}`\n\n"
                        f"⚠️ *Аудио файл НЕ сохранен*\n"
                        f"Для транскрипции настройте OpenAI API",
                        parse_mode="MarkdownV2"
                    )
                    return True, "✅ Информация об аудио файле сохранена (без самого аудио)"
                else:
                    return False, f"⌛ Ошибка сохранения информации: {msg}"
        
        # PDF файлы
        elif ext == '.pdf' or mime_type == 'application/pdf':
            if upload_handler and hasattr(upload_handler, 'document_processor'):
                await processing_msg.edit_text(
                    f"📄 *Обработка PDF*\n\n"
                    f"Файл: `{escape_markdown_v2(filename)}`\n"
                    f"Извлечение текста\\.\\.\\.",
                    parse_mode="MarkdownV2"
                )
                
                state = FSMContext(storage=None, key=None)
                
                await upload_handler.document_processor.process_pdf_file(
                    original_message, processing_msg, filename, file_bytes,
                    state, user_id, codebase_id
                )
                return True, "✅ PDF документ обработан и сохранён"
        
        # Изображения
        elif mime_type and mime_type.startswith('image/'):
            if upload_handler and hasattr(upload_handler, 'image_processor'):
                await processing_msg.edit_text(
                    f"🖼️ *Обработка изображения*\n\n"
                    f"Файл: `{escape_markdown_v2(filename)}`\n"
                    f"Распознавание текста\\.\\.\\.",
                    parse_mode="MarkdownV2"
                )
                
                from types import SimpleNamespace
                document = SimpleNamespace(
                    file_name=filename,
                    file_size=len(file_bytes)
                )
                
                await upload_handler.image_processor.process_image_file(
                    original_message, processing_msg, filename, file_bytes,
                    document, user_id, None
                )
                return True, "✅ Изображение обработано"
        
        # Office документы
        elif ext in ['.docx', '.xlsx', '.pptx']:
            if upload_handler:
                await processing_msg.edit_text(
                    f"📊 *Обработка документа*\n\n"
                    f"Файл: `{escape_markdown_v2(filename)}`\n"
                    f"Конвертация в текст\\.\\.\\.",
                    parse_mode="MarkdownV2"
                )
                
                if ext == '.docx' and hasattr(upload_handler, 'document_processor'):
                    await upload_handler.document_processor.process_document_file(
                        original_message, processing_msg, filename, file_bytes,
                        user_id, codebase_id
                    )
                    return True, "✅ Документ Word обработан и сохранён"
                    
                elif ext in ['.xlsx', '.xls'] and hasattr(upload_handler, 'table_processor'):
                    from types import SimpleNamespace
                    document = SimpleNamespace(
                        file_name=filename,
                        file_size=len(file_bytes)
                    )
                    await upload_handler.table_processor.process_table_file(
                        original_message, processing_msg, filename, file_bytes,
                        document, ext, user_id, None
                    )
                    return True, "✅ Таблица Excel обработана и сохранена"
                    
                elif ext in ['.pptx', '.ppt'] and hasattr(upload_handler, 'document_processor'):
                    await upload_handler.document_processor.process_powerpoint_file(
                        original_message, processing_msg, filename, file_bytes,
                        user_id, codebase_id
                    )
                    return True, "✅ Презентация PowerPoint обработана и сохранена"
        
        # HTML файлы
        elif ext in ['.html', '.htm'] or mime_type == 'text/html':
            if upload_handler and hasattr(upload_handler, 'document_processor'):
                await processing_msg.edit_text(
                    f"🌐 *Обработка HTML*\n\n"
                    f"Файл: `{escape_markdown_v2(filename)}`\n"
                    f"Извлечение текста\\.\\.\\.",
                    parse_mode="MarkdownV2"
                )
                
                await upload_handler.document_processor.process_html_file(
                    original_message, processing_msg, filename, file_bytes,
                    user_id, codebase_id
                )
                return True, "✅ HTML документ обработан и сохранён"
        
        elif ext in ['.zip', '.7z']:
            from agents.zip_agent import ZipAgent

            zip_agent = ZipAgent()

            # Временный архив
            temp_archive = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            temp_archive.write(file_bytes)
            temp_archive.close()

            # Временная папка для распаковки
            temp_dir = tempfile.mkdtemp(prefix="upload_zip_")

            # Распаковка
            if ext == ".zip":
                extracted_files, errors = await zip_agent._extract_zip(temp_archive.name, temp_dir)
            else:
                extracted_files, errors = await zip_agent._extract_7z(temp_archive.name, temp_dir)

            # Сохраняем файлы в кодовую базу
            saved_count = 0
            for file_info in extracted_files:
                safe_name = file_info["safe_name"]
                text_content = file_info["content"]

                try:
                    await context["file_manager"].save_file(
                        user_id=user_id,
                        codebase_id=codebase_id,
                        filename=safe_name,
                        file_data=text_content.encode("utf-8")
                    )
                    saved_count += 1
                except Exception as e:
                    errors.append(f"{safe_name}: {e}")

            # Ответ
            response = f"📦 Архив `{filename}` обработан\n"
            response += f"✅ Сохранено файлов: {saved_count}\n"
            if errors:
                response += "⚠️ Ошибки:\n" + "\n".join(errors[:5])
                if len(errors) > 5:
                    response += f"\n...и ещё {len(errors)-5} ошибок"

            return True, response
        
        # Текстовые файлы и код - сохраняем как есть
        else:
            await processing_msg.edit_text(
                f"💾 *Сохранение файла*\n\n"
                f"Файл: `{escape_markdown_v2(filename)}`\n"
                f"Размер: {len(file_bytes) // 1024} КБ",
                parse_mode="MarkdownV2"
            )
            
            # Пытаемся декодировать как текст
            try:
                text_content = file_bytes.decode('utf-8')
            except UnicodeDecodeError:
                # Пробуем другие кодировки
                for encoding in ['cp1251', 'latin-1', 'cp866']:
                    try:
                        text_content = file_bytes.decode(encoding)
                        break
                    except:
                        continue
                else:
                    # Если не удалось декодировать, сохраняем как бинарный
                    success, msg, _ = await file_manager.save_file(
                        user_id=user_id,
                        codebase_id=codebase_id,
                        filename=filename,
                        file_data=file_bytes,
                        skip_conversion=True
                    )
                    
                    if success:
                        await processing_msg.edit_text(
                            f"✅ *Файл сохранён*\n\n"
                            f"Имя: `{escape_markdown_v2(filename)}`\n"
                            f"Размер: {len(file_bytes) // 1024} КБ\n\n"
                            f"Файл сохранён в активную кодовую базу",
                            parse_mode="MarkdownV2"
                        )
                        return True, "✅ Файл успешно сохранён"
                    else:
                        return False, f"⌛ Ошибка сохранения: {msg}"
            
            # Сохраняем текстовый файл
            success, msg, _ = await file_manager.save_file(
                user_id=user_id,
                codebase_id=codebase_id,
                filename=filename,
                file_data=text_content.encode('utf-8'),
                skip_conversion=True
            )
            
            if success:
                # Запускаем индексацию RAG если это текстовый файл
                from agents.rag_singleton import get_rag_manager
                rag_manager = get_rag_manager()
                
                if rag_manager._is_text_file(filename):
                    asyncio.create_task(self._update_rag_index(
                        user_id, codebase_id, filename, rag_manager, context
                    ))
                
                await processing_msg.edit_text(
                    f"✅ *Файл сохранён*\n\n"
                    f"Имя: `{escape_markdown_v2(filename)}`\n"
                    f"Размер: {len(file_bytes) // 1024} КБ\n"
                    f"Тип: текстовый файл\n\n"
                    f"Файл сохранён в активную кодовую базу",
                    parse_mode="MarkdownV2"
                )
                return True, "✅ Файл успешно загружен и сохранён"
            else:
                return False, f"⌛ Ошибка сохранения: {msg}"
        
        # Если ничего не подошло (но это не должно произойти)
        return False, "Тип файла не поддерживается"
    
    async def _update_rag_index(self, user_id: str, codebase_id: str, 
                               filename: str, rag_manager, context: Dict[str, Any]):
        """Обновление RAG индекса после загрузки файла"""
        try:
            codebase_manager = context.get('codebase_manager')
            if not codebase_manager:
                return
                
            codebase_dir = codebase_manager._get_codebase_dir(user_id, codebase_id)
            files_dir = os.path.join(codebase_dir, "files")
            
            success, msg = await rag_manager.update_incremental(
                user_id=user_id,
                codebase_id=codebase_id,
                files_dir=files_dir
            )
            
            if success:
                logger.info(f"RAG индекс обновлен после загрузки {filename}: {msg}")
            else:
                logger.debug(f"RAG индекс проверен для {filename}: {msg}")
                
        except Exception as e:
            logger.error(f"Ошибка обновления RAG индекса: {e}")