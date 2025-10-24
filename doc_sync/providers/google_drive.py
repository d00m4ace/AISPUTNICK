# doc_sync/providers/google_drive.py
import os
import logging
import mimetypes
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from io import BytesIO
from typing import Dict, Optional, Tuple, List
from datetime import datetime
import hashlib
import sys

# Добавляем родительскую директорию в path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from providers.base import DocumentProvider
from providers.google_docs import GoogleDocsProvider

logger = logging.getLogger(__name__)

class GoogleDriveProvider(DocumentProvider):
    """Провайдер для рекурсивного обхода Google Drive папок"""
    
    SCOPES = [
        'https://www.googleapis.com/auth/drive.readonly'
    ]
    
    # MIME типы которые нужно обрабатывать
    SUPPORTED_MIMETYPES = {
        'application/vnd.google-apps.document',
        'application/vnd.google-apps.spreadsheet',
        'application/vnd.google-apps.presentation',
        'application/pdf',
        'text/plain',
        'text/csv',
        'text/markdown',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/msword',
        'application/vnd.ms-excel'
    }
    
    def setup_auth(self):
        """Настройка авторизации для Google Drive"""
        service_account_file = self.auth_config.get('service_account_file')
        
        if not os.path.isabs(service_account_file):
            service_account_file = os.path.abspath(service_account_file)
        
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file, scopes=self.SCOPES
        )
        
        self.drive_service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
        
        # Также инициализируем GoogleDocsProvider для конвертации документов
        self.docs_provider = GoogleDocsProvider(self.auth_config)
        
        # Инициализируем конвертер для бинарных файлов
        self._init_converter()
        
        logger.info("Google Drive provider initialized")
    
    def _init_converter(self):
        """Инициализация конвертера документов"""
        try:
            from converters import HTMLToMarkdownConverter
            self.html_converter = HTMLToMarkdownConverter()
        except ImportError:
            logger.warning("HTMLToMarkdownConverter not available")
            self.html_converter = None
        
        # Пробуем импортировать конвертеры PDF
        self.pdf_converter = None
        try:
            # Импортируем конвертер PDF из markdown_converter.py
            from converters import PDFConverter as PDFConverter
            self.pdf_converter = PDFConverter()
            logger.info("PDF converter initialized")
        except ImportError as e:
            logger.warning(f"PDF converter not available: {e}")
    
    def extract_folder_id(self, url: str) -> str:
        """Извлечь ID папки из URL"""
        if 'drive.google.com' in url:
            # URL вида: https://drive.google.com/drive/u/0/folders/FOLDER_ID
            parts = url.split('/')
            for i, part in enumerate(parts):
                if part == 'folders' and i + 1 < len(parts):
                    folder_id = parts[i + 1].split('?')[0]  # Убираем query params
                    return folder_id
        return url  # Возможно, это уже ID
    
    def fetch_content(self, url: str) -> Tuple[str, Dict]:
        """
        Получить содержимое всех файлов в папке Google Drive
        Возвращает объединенный markdown всех файлов
        """
        folder_id = self.extract_folder_id(url)
        
        logger.info(f"Starting recursive scan of Google Drive folder: {folder_id}")
        
        # Получаем информацию о папке
        try:
            folder = self.drive_service.files().get(fileId=folder_id).execute()
            folder_name = folder.get('name', 'Untitled Folder')
        except Exception as e:
            logger.error(f"Failed to get folder info: {e}")
            folder_name = 'Google Drive Folder'
        
        # Собираем все файлы рекурсивно
        all_files = self._get_all_files_recursive(folder_id, folder_name)
        
        logger.info(f"Found {len(all_files)} files in folder")
        
        # Метаданные папки
        metadata = {
            'title': folder_name,
            'id': folder_id,
            'type': 'google_drive_folder',
            'last_modified': datetime.now().isoformat(),
            'files_count': len(all_files),
            '_is_folder': True,
            '_files': []  # Список обработанных файлов
        }
        
        # Обрабатываем каждый файл
        markdown_content = f"# {folder_name}\n\n"
        markdown_content += f"*Google Drive Folder - {len(all_files)} files*\n\n"
        markdown_content += "---\n\n"
        
        for file_info in all_files:
            file_metadata, file_content = self._process_file(file_info)
            
            if file_content:
                # Добавляем информацию о файле в метаданные
                metadata['_files'].append({
                    'id': file_metadata['id'],
                    'name': file_metadata['name'],
                    'path': file_metadata['path'],
                    'mime_type': file_metadata['mime_type']
                })
                
                # Добавляем контент в общий markdown
                markdown_content += f"## 📄 {file_metadata['path']}\n\n"
                markdown_content += f"*File ID: {file_metadata['id']}*\n"
                markdown_content += f"*Type: {file_metadata['mime_type']}*\n\n"
                markdown_content += file_content
                markdown_content += "\n\n---\n\n"
        
        metadata['_is_markdown'] = True
        return markdown_content, metadata
    
    def _get_all_files_recursive(self, folder_id: str, folder_path: str = "") -> List[Dict]:
        """Рекурсивно получить все файлы из папки и подпапок"""
        all_files = []
        
        try:
            # Получаем файлы в текущей папке
            query = f"'{folder_id}' in parents and trashed = false"
            response = self.drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType, modifiedTime)",
                pageSize=1000
            ).execute()
            
            items = response.get('files', [])
            
            for item in items:
                item_path = f"{folder_path}/{item['name']}" if folder_path else item['name']
                
                if item['mimeType'] == 'application/vnd.google-apps.folder':
                    # Это папка - рекурсивно обходим
                    logger.info(f"Entering subfolder: {item_path}")
                    subfolder_files = self._get_all_files_recursive(item['id'], item_path)
                    all_files.extend(subfolder_files)
                else:
                    # Это файл - проверяем, поддерживается ли
                    if self._is_supported_file(item['mimeType']):
                        logger.info(f"Found file: {item_path}")
                        all_files.append({
                            'id': item['id'],
                            'name': item['name'],
                            'path': item_path,
                            'mime_type': item['mimeType'],
                            'modified_time': item.get('modifiedTime')
                        })
                    else:
                        logger.debug(f"Skipping unsupported file: {item_path} ({item['mimeType']})")
            
            # Обработка пагинации если есть
            while 'nextPageToken' in response:
                response = self.drive_service.files().list(
                    q=query,
                    fields="files(id, name, mimeType, modifiedTime)",
                    pageSize=1000,
                    pageToken=response['nextPageToken']
                ).execute()
                
                items = response.get('files', [])
                for item in items:
                    item_path = f"{folder_path}/{item['name']}" if folder_path else item['name']
                    
                    if item['mimeType'] == 'application/vnd.google-apps.folder':
                        subfolder_files = self._get_all_files_recursive(item['id'], item_path)
                        all_files.extend(subfolder_files)
                    elif self._is_supported_file(item['mimeType']):
                        all_files.append({
                            'id': item['id'],
                            'name': item['name'],
                            'path': item_path,
                            'mime_type': item['mimeType'],
                            'modified_time': item.get('modifiedTime')
                        })
                        
        except Exception as e:
            logger.error(f"Error listing files in folder {folder_id}: {e}")
        
        return all_files
    
    def _is_supported_file(self, mime_type: str) -> bool:
        """Проверить, поддерживается ли тип файла"""
        # Расширенный список поддерживаемых MIME типов
        extended_mimetypes = self.SUPPORTED_MIMETYPES.copy()
        extended_mimetypes.update({
            'application/vnd.google-apps.shortcut',  # Ярлыки на файлы
            'application/vnd.ms-powerpoint',  # .ppt
            'application/rtf',  # .rtf
            'text/rtf',  # .rtf альтернативный
            'application/vnd.oasis.opendocument.text',  # .odt
        })
    
        return mime_type in extended_mimetypes
    
    def _process_file(self, file_info: Dict) -> Tuple[Dict, str]:
        """Обработать отдельный файл и вернуть его метаданные и контент"""
        file_id = file_info['id']
        mime_type = file_info['mime_type']
    
        metadata = {
            'id': file_id,
            'name': file_info['name'],
            'path': file_info['path'],
            'mime_type': mime_type,
            'modified_time': file_info.get('modified_time')
        }
    
        try:
            # Для ярлыков получаем оригинальный файл
            if mime_type == 'application/vnd.google-apps.shortcut':
                try:
                    shortcut_details = self.drive_service.files().get(
                        fileId=file_id,
                        fields='shortcutDetails'
                    ).execute()
                
                    target_id = shortcut_details.get('shortcutDetails', {}).get('targetId')
                    target_mime = shortcut_details.get('shortcutDetails', {}).get('targetMimeType')
                
                    if target_id and target_mime:
                        file_id = target_id
                        mime_type = target_mime
                        metadata['original_id'] = file_info['id']
                        metadata['is_shortcut'] = True
                except Exception as e:
                    logger.warning(f"Could not resolve shortcut {file_id}: {e}")
                    return metadata, f"*Shortcut could not be resolved*"
        
            # Для Google Docs/Sheets/Slides используем GoogleDocsProvider
            if mime_type.startswith('application/vnd.google-apps'):
                content = self._process_google_doc(file_id, mime_type)
            else:
                # Для остальных файлов скачиваем и конвертируем
                content = self._process_binary_file(file_id, file_info['name'], mime_type)
        
            metadata['processed_successfully'] = True
            return metadata, content
        
        except Exception as e:
                logger.error(f"Error processing file {file_info['path']}: {e}")
                metadata['processed_successfully'] = False
                metadata['error'] = str(e)
                return metadata, f"*Error processing file: {str(e)}*\n\nFile: {file_info['name']}\nType: {mime_type}"
    
    def _process_google_doc(self, file_id: str, mime_type: str) -> str:
        """Обработать Google документ"""
        try:
            # Формируем URL для документа
            if 'document' in mime_type:
                url = f"https://docs.google.com/document/d/{file_id}"
            elif 'spreadsheet' in mime_type:
                url = f"https://docs.google.com/spreadsheets/d/{file_id}"
            elif 'presentation' in mime_type:
                url = f"https://docs.google.com/presentation/d/{file_id}"
            else:
                return f"*Unsupported Google Apps type: {mime_type}*"
            
            # Используем GoogleDocsProvider для получения контента
            html_content, doc_metadata = self.docs_provider.fetch_content(url)
            
            # Конвертируем HTML в Markdown если нужно
            if self.html_converter and not doc_metadata.get('_is_markdown'):
                markdown_content = self.html_converter.convert(html_content)
            else:
                markdown_content = html_content
            
            return markdown_content
            
        except Exception as e:
            logger.error(f"Error processing Google Doc {file_id}: {e}")
            return f"*Error: {str(e)}*"
    
    def _process_binary_file(self, file_id: str, filename: str, mime_type: str) -> str:
        """Обработать бинарный файл (PDF, DOC, etc)"""
        try:
            # Скачиваем файл
            request = self.drive_service.files().get_media(fileId=file_id)
            file_bytes = BytesIO()
            downloader = MediaIoBaseDownload(file_bytes, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug(f"Download {int(status.progress() * 100)}% complete")
            
            file_bytes.seek(0)
            content_bytes = file_bytes.read()
            
            # Конвертируем в зависимости от типа
            if mime_type == 'application/pdf' and self.pdf_converter:
                return self._convert_pdf(content_bytes, filename)
            elif mime_type in ['text/plain', 'text/csv', 'text/markdown']:
                # Текстовые файлы просто декодируем
                try:
                    return content_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    return content_bytes.decode('utf-8', errors='replace')
            else:
                # Для остальных типов пробуем использовать универсальный конвертер
                return self._convert_with_fallback(content_bytes, filename, mime_type)
                
        except Exception as e:
            logger.error(f"Error downloading/converting file {file_id}: {e}")
            return f"*Error processing binary file: {str(e)}*"
    
    def _convert_pdf(self, file_bytes: bytes, filename: str) -> str:
        """Конвертировать PDF в текст"""
        try:
            # Исправленный вызов - передаем только 2 аргумента
            from converters import PDFConverter
        
            converter = PDFConverter()
            success, content = converter.convert(file_bytes, filename)
        
            if success and content:
                return content
            else:
                logger.warning(f"PDF conversion returned no content for {filename}")
                return self._extract_pdf_text_simple(file_bytes)
            
        except Exception as e:
            logger.error(f"PDF conversion error: {e}")
            # Fallback к простому извлечению текста
            return self._extract_pdf_text_simple(file_bytes)
    
    def _extract_pdf_text_simple(self, file_bytes: bytes) -> str:
        """Простое извлечение текста из PDF с несколькими методами"""
        # Метод 1: PyPDF2
        try:
            import PyPDF2
            from io import BytesIO
        
            pdf_file = BytesIO(file_bytes)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
        
            text = [f"# PDF Document\n"]
            text.append(f"*Pages: {len(pdf_reader.pages)}*\n\n")
        
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    text.append(f"### Page {page_num + 1}\n")
                    text.append(page_text)
                    text.append("\n---\n")
        
            content = "".join(text)
            if len(content) > 50:  # Если извлекли хотя бы что-то
                logger.info(f"PDF text extracted via PyPDF2")
                return content
            
        except ImportError:
            logger.warning("PyPDF2 not installed")
        except Exception as e:
            logger.warning(f"PyPDF2 extraction failed: {e}")
    
        # Метод 2: pdfplumber
        try:
            import pdfplumber
            from io import BytesIO
        
            text = [f"# PDF Document\n"]
        
            with pdfplumber.open(BytesIO(file_bytes)) as pdf:
                text.append(f"*Pages: {len(pdf.pages)}*\n\n")
            
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                
                    if page_text and page_text.strip():
                        text.append(f"### Page {i + 1}\n")
                        text.append(page_text)
                    
                        # Также извлекаем таблицы если есть
                        tables = page.extract_tables()
                        for table in tables:
                            text.append("\n")
                            for row in table:
                                if row:
                                    row_clean = [str(cell) if cell else "" for cell in row]
                                    text.append("| " + " | ".join(row_clean) + " |")
                                    if table.index(row) == 0:
                                        text.append("| " + " | ".join(["---"] * len(row)) + " |")
                            text.append("\n")
                    
                        text.append("\n---\n")
        
            content = "".join(text)
            if len(content) > 50:
                logger.info(f"PDF text extracted via pdfplumber")
                return content
            
        except ImportError:
            logger.warning("pdfplumber not installed")
        except Exception as e:
            logger.warning(f"pdfplumber extraction failed: {e}")
    
        # Если ничего не сработало
        logger.error("All PDF extraction methods failed")
        return "*Could not extract text from PDF. Please install PyPDF2 or pdfplumber: pip install PyPDF2 pdfplumber*"
    
    def _convert_with_fallback(self, file_bytes: bytes, filename: str, mime_type: str) -> str:
        """Попытка конвертации через универсальный конвертер"""
        try:
            from converters import UniversalFileConverter
        
            converter = UniversalFileConverter()
            success, content = converter.convert(file_bytes, filename)
        
            if success and content:
                return content
            else:
                return f"*File type {mime_type} could not be converted*"
            
        except ImportError:
            logger.warning("UniversalFileConverter not available")
            return f"*File type {mime_type} is not supported*"
        except Exception as e:
            logger.error(f"Fallback conversion failed: {e}")
            return f"*Conversion error: {str(e)}*"

    def check_for_updates(self, url: str, last_modified: Optional[datetime]) -> bool:
        """Проверить обновления в папке"""
        if not last_modified:
            return True
    
        folder_id = self.extract_folder_id(url)
    
        try:
            from datetime import timezone
        
            # Обрабатываем last_modified
            if isinstance(last_modified, str):
                if 'Z' in last_modified or '+' in last_modified or 'T' in last_modified:
                    last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                else:
                    last_modified = datetime.fromisoformat(last_modified)
        
            # Убеждаемся что last_modified имеет timezone
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
        
            # Формируем запрос с правильным форматом даты
            query_date = last_modified.isoformat().replace('+00:00', 'Z')
        
            # Ищем файлы измененные после last_modified
            query = f"'{folder_id}' in parents and modifiedTime > '{query_date}' and trashed = false"
        
            response = self.drive_service.files().list(
                q=query,
                fields="files(id, modifiedTime)",
                pageSize=1
            ).execute()
        
            # Если есть хотя бы один измененный файл
            if response.get('files'):
                logger.info(f"Found updated files in folder")
                return True
        
            # Также проверяем саму папку
            folder = self.drive_service.files().get(
                fileId=folder_id,
                fields='modifiedTime'
            ).execute()
        
            folder_modified_str = folder.get('modifiedTime')
            if folder_modified_str:
                folder_modified = datetime.fromisoformat(folder_modified_str.replace('Z', '+00:00'))
                # folder_modified уже с timezone, можем сравнивать
                if folder_modified > last_modified:
                    return True
                
        except Exception as e:
            logger.error(f"Error checking folder updates: {e}")
            return True  # В случае ошибки лучше обновить
    
        return False

    def get_folder_files_list(self, folder_id: str) -> List[Dict]:
        """
        Получить только список файлов без загрузки контента
        """
        return self._get_all_files_recursive(folder_id, "")

    def process_single_file(self, file_info: Dict) -> Tuple[Dict, str]:
        """
        Обработать один конкретный файл
        """
        return self._process_file(file_info)

    def process_single_file_with_retry(self, file_info: Dict, max_retries: int = 3) -> Tuple[Dict, str]:
        """
        Обработать файл с повторными попытками при ошибке rate limit
        """
        import time
    
        for attempt in range(max_retries):
            try:
                metadata, content = self._process_file(file_info)
            
                # Если получили контент без ошибок, возвращаем
                if content and not content.startswith('*Error: <HttpError 429'):
                    return metadata, content
            
                # Если это ошибка 429, ждем и пробуем еще раз
                if content and '429' in content:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 65 # Увеличиваем время ожидания
                        logger.info(f"Got 429 error, waiting {wait_time} seconds before retry {attempt + 2}/{max_retries}")
                        time.sleep(wait_time)
                        continue
            
                # Для других ошибок возвращаем как есть
                return metadata, content
            
            except Exception as e:
                if '429' in str(e) and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 65
                    logger.info(f"Got 429 exception, waiting {wait_time} seconds before retry {attempt + 2}/{max_retries}")
                    time.sleep(wait_time)
                    continue
                elif attempt == max_retries - 1:
                    # Последняя попытка не удалась
                    logger.error(f"Failed after {max_retries} attempts: {e}")
                    return file_info, f"*Error: {str(e)}*"
    
        return file_info, "*Error: Max retries exceeded*"