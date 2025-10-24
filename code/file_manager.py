# code/file_manager.py
"""
Менеджер файлов кодовых баз
"""
import os
import asyncio
import aiofiles

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from converters.markdown_converter import MarkdownConverterManager
from converters.encoding_converter import EncodingConverter
from config import Config

import logging
logger = logging.getLogger(__name__)


class FileManager:
    """Управление файлами в кодовых базах"""
    
    def __init__(self, codebase_manager, ai_interface=None):
        self.codebase_manager = codebase_manager
        self.ai_interface = ai_interface
        self._lock = asyncio.Lock()
        
        # Инициализация конвертеров
        self.markdown_converter = MarkdownConverterManager(ai_interface)
        self.encoding_converter = EncodingConverter()
    
    def _get_files_dir(self, user_id: str, codebase_id: str) -> str:
        """Получает путь к директории файлов"""
        codebase_dir = self.codebase_manager._get_codebase_dir(user_id, codebase_id)
        return os.path.join(codebase_dir, "files")
    
    def is_text_file(self, filename: str) -> bool:
        """
        Проверяет, является ли файл текстовым
        Использует логику из Config
        """
        return Config.is_text_file(filename)
    
    def format_size(self, size: int) -> str:
        """
        Форматирует размер файла в читаемый вид
        Использует логику из Config
        """
        return Config.format_file_size(size)
    
    async def file_exists(self, user_id: str, codebase_id: str, filename: str) -> bool:
        """Проверяет существование файла"""
        files_dir = self._get_files_dir(user_id, codebase_id)
        file_path = os.path.join(files_dir, filename)
        return os.path.exists(file_path)

    async def save_file(
        self, 
        user_id: str, 
        codebase_id: str, 
        filename: str,
        file_data: bytes, 
        encoding: Optional[str] = None,
        progress_callback=None, 
        cancel_check=None,
        skip_conversion: bool = False,
        only_convert: bool = False  # Новый параметр
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Сохраняет файл с автоматической конвертацией если возможно
    
        Args:
            only_convert: Если True, только конвертирует без сохранения
        
        Returns: (success, message, converted_filename_or_none)
        """

        # Проверяем права на запись
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        if config:
            # Запрет записи в devnull
            if config.get("is_system") or config.get("folder_name") == "devnull":
                return False, "Невозможно сохранить файлы в системную базу", None
        
            # Запрет записи в публичные базы не владельцем
            if config.get("is_readonly_for_user"):
                return False, "У вас нет прав на запись в эту публичную базу", None

        # Проверяем возможность конвертации
        converted_filename = None
        if not skip_conversion and self.markdown_converter.can_convert(filename):
            success, new_name, md_content = await self.markdown_converter.convert_to_markdown(
                user_id,
                file_data, filename, encoding, progress_callback, cancel_check
            )
        
            if success and md_content:
                converted_filename = new_name
            
                if only_convert:
                    # Только конвертируем, не сохраняем
                    ext = os.path.splitext(filename.lower())[1]
                    type_map = {
                        '.pdf': 'PDF конвертирован',
                        '.xls': 'Excel конвертирован',
                        '.xlsx': 'Excel конвертирован',
                        '.csv': 'CSV конвертирован',
                        '.doc': 'Документ конвертирован',
                        '.docx': 'Документ конвертирован',
                        '.rtf': 'RTF конвертирован',
                        '.odt': 'ODT конвертирован',
                        '.html': 'HTML конвертирован',
                        '.htm': 'HTML конвертирован',
                        '.xhtml': 'HTML конвертирован',
                        '.ppt': 'PowerPoint конвертирован',
                        '.pptx': 'PowerPoint конвертирован',
                    }
                
                    if ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp'}:
                        msg = f"Изображение распознано → .md: '{new_name}'"
                    else:
                        type_name = type_map.get(ext, 'Файл конвертирован')
                        msg = f"{type_name} → .md: '{new_name}'"
                
                    return True, msg, converted_filename
            
                # Если не only_convert, сохраняем оба файла
                async with self._lock:
                    try:
                        files_dir = self._get_files_dir(user_id, codebase_id)
                        os.makedirs(files_dir, exist_ok=True)
                    
                        # Сохраняем конвертированный файл
                        md_path = os.path.join(files_dir, new_name)
                        async with aiofiles.open(md_path, 'w', encoding='utf-8', newline='\n') as f:
                            await f.write(md_content)
                    
                        # Сохраняем оригинальный файл
                        orig_path = os.path.join(files_dir, filename)
                        async with aiofiles.open(orig_path, 'wb') as f:
                            await f.write(file_data)
                    
                        await self._update_codebase_stats(user_id, codebase_id)
                    
                        file_size = len(md_content.encode('utf-8'))
                        return True, f"Файлы сохранены ({self.format_size(file_size)})", converted_filename
                    
                    except Exception as e:
                        logger.error(f"Ошибка сохранения: {e}")
                        return False, f"Ошибка: {str(e)}", None
    
        # Обычное сохранение без конвертации
        async with self._lock:
            try:
                files_dir = self._get_files_dir(user_id, codebase_id)
                os.makedirs(files_dir, exist_ok=True)
            
                file_path = os.path.join(files_dir, filename)
            
                if self.is_text_file(filename):
                    # Конвертация кодировки для текстовых файлов
                    if encoding and encoding.lower() != 'utf-8':
                        text = await self.encoding_converter.convert_to_utf8(file_data, encoding)
                    else:
                        try:
                            text = file_data.decode('utf-8')
                        except UnicodeDecodeError:
                            detected_encoding, _ = await self.encoding_converter.detect_encoding(file_data)
                            text = await self.encoding_converter.convert_to_utf8(file_data, detected_encoding)
                
                    text = self.encoding_converter._normalize_text(text)
                    async with aiofiles.open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                        await f.write(text)
                    file_size = len(text.encode('utf-8'))
                else:
                    # Бинарные файлы
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(file_data)
                    file_size = len(file_data)
            
                await self._update_codebase_stats(user_id, codebase_id)
                return True, f"Файл сохранен ({self.format_size(file_size)})", None
            
            except Exception as e:
                logger.error(f"Ошибка сохранения файла {filename}: {e}")
                return False, f"Ошибка сохранения: {str(e)}", None

    
    async def delete_file(self, user_id: str, codebase_id: str, filename: str) -> bool:
        async with self._lock:
            try:
                # Проверяем права на удаление
                config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
                if config:
                    # Запрет удаления из devnull
                    if config.get("is_system") or config.get("folder_name") == "devnull":
                        logger.warning(f"Попытка удалить файл из системной базы devnull: {filename}")
                        return False
                
                    # Запрет удаления из публичных баз не владельцем
                    if config.get("is_readonly_for_user"):
                        logger.warning(f"Попытка удалить файл из публичной базы без прав: {filename}")
                        return False
            
                files_dir = self._get_files_dir(user_id, codebase_id)
                file_path = os.path.join(files_dir, filename)

                if os.path.exists(file_path):
                    os.remove(file_path)
                    await self._update_codebase_stats(user_id, codebase_id)
                    return True

                return False

            except Exception as e:
                logger.error(f"Ошибка удаления файла {filename}: {e}")
                return False
    
    async def delete_files(self, user_id: str, codebase_id: str, filenames: List[str]) -> Tuple[int, int]:
        # Проверяем права перед началом удаления
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        if config:
            # Запрет удаления из devnull
            if config.get("is_system") or config.get("folder_name") == "devnull":
                logger.warning(f"Попытка массового удаления из системной базы devnull")
                return 0, len(filenames)
        
            # Запрет удаления из публичных баз не владельцем
            if config.get("is_readonly_for_user"):
                logger.warning(f"Попытка массового удаления из публичной базы без прав")
                return 0, len(filenames)
    
        deleted = 0
        for filename in filenames:
            if await self.delete_file(user_id, codebase_id, filename):
                deleted += 1
        return deleted, len(filenames)
    
    async def get_file(self, user_id: str, codebase_id: str, filename: str) -> Optional[bytes]:
        """Получает содержимое файла"""
        try:
            # Проверяем, не публичная ли это база
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
            if config and config.get("is_readonly_for_user"):
                # Пользователь не может читать файлы публичной базы напрямую
                logger.warning(f"Попытка чтения файла из публичной базы пользователем {user_id}")
                return None

            files_dir = self._get_files_dir(user_id, codebase_id)
            file_path = os.path.join(files_dir, filename)
            
            if not os.path.exists(file_path):
                return None
            
            if self.is_text_file(filename):
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    return content.encode('utf-8')
            else:
                async with aiofiles.open(file_path, 'rb') as f:
                    return await f.read()
                    
        except Exception as e:
            logger.error(f"Ошибка чтения файла {filename}: {e}")
            return None
    
    async def list_files(self, user_id: str, codebase_id: str, 
                        page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        """Получает список файлов с пагинацией"""
        try:
            # Проверяем, не публичная ли это база
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
            if config and config.get("is_readonly_for_user"):
                # Пользователь не может просматривать файлы публичной базы напрямую
                return {
                    'files': [],
                    'total': 0,
                    'page': 1,
                    'total_pages': 0,
                    'per_page': per_page,
                    'start_idx': 0,
                    'end_idx': 0,
                    'error': 'Просмотр файлов публичных баз доступен только через агентов'
                }

            files_dir = self._get_files_dir(user_id, codebase_id)
            
            if not os.path.exists(files_dir):
                return {
                    'files': [],
                    'total': 0,
                    'page': 1,
                    'total_pages': 0,
                    'per_page': per_page,
                    'start_idx': 0,
                    'end_idx': 0
                }
            
            all_files = []
            for filename in os.listdir(files_dir):
                file_path = os.path.join(files_dir, filename)
                if os.path.isfile(file_path):
                    stat = os.stat(file_path)
                    all_files.append({
                        'name': filename,
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        'is_text': self.is_text_file(filename)
                    })
            
            all_files.sort(key=lambda x: x['name'].lower())
            
            total = len(all_files)
            total_pages = (total + per_page - 1) // per_page
            
            if page < 1:
                page = 1
            elif page > total_pages and total_pages > 0:
                page = total_pages
            
            start_idx = (page - 1) * per_page
            end_idx = min(start_idx + per_page, total)
            
            return {
                'files': all_files[start_idx:end_idx],
                'total': total,
                'page': page,
                'total_pages': total_pages,
                'per_page': per_page,
                'start_idx': start_idx + 1 if total > 0 else 0,
                'end_idx': end_idx
            }
            
        except Exception as e:
            logger.error(f"Ошибка получения списка файлов: {e}")
            return {
                'files': [],
                'total': 0,
                'page': 1,
                'total_pages': 0,
                'per_page': per_page
            }
    
    async def search_files(self, user_id: str, codebase_id: str, pattern: str) -> List[Dict[str, Any]]:
        """Поиск файлов по шаблону имени"""
        try:
            # Проверяем, не публичная ли это база
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
            if config and config.get("is_readonly_for_user"):
                # Пользователь не может искать в публичной базе напрямую
                logger.warning(f"Попытка поиска в публичной базе пользователем {user_id}")
                return []

            files_dir = self._get_files_dir(user_id, codebase_id)
            
            if not os.path.exists(files_dir):
                return []
            
            pattern_lower = pattern.lower()
            matched_files = []
            
            for filename in os.listdir(files_dir):
                if pattern_lower in filename.lower():
                    file_path = os.path.join(files_dir, filename)
                    if os.path.isfile(file_path):
                        stat = os.stat(file_path)
                        matched_files.append({
                            'name': filename,
                            'size': stat.st_size,
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            'is_text': self.is_text_file(filename)
                        })
            
            matched_files.sort(key=lambda x: x['name'].lower())
            return matched_files
            
        except Exception as e:
            logger.error(f"Ошибка поиска файлов: {e}")
            return []
    
    async def get_codebase_size(self, user_id: str, codebase_id: str) -> int:
        """Получает общий размер файлов в кодовой базе"""
        try:
            files_dir = self._get_files_dir(user_id, codebase_id)
            
            if not os.path.exists(files_dir):
                return 0
            
            total_size = 0
            for filename in os.listdir(files_dir):
                file_path = os.path.join(files_dir, filename)
                if os.path.isfile(file_path):
                    total_size += os.path.getsize(file_path)
            
            return total_size
            
        except Exception as e:
            logger.error(f"Ошибка подсчета размера: {e}")
            return 0
    
    async def _update_codebase_stats(self, user_id: str, codebase_id: str):
        """Обновляет статистику кодовой базы"""
        try:
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            if not config:
                return
            
            files_dir = self._get_files_dir(user_id, codebase_id)
            
            files_count = 0
            total_size = 0
            
            if os.path.exists(files_dir):
                for filename in os.listdir(files_dir):
                    file_path = os.path.join(files_dir, filename)
                    if os.path.isfile(file_path):
                        files_count += 1
                        total_size += os.path.getsize(file_path)
            
            await self.codebase_manager.update_codebase_config(
                user_id, codebase_id,
                {
                    'stats': {
                        'files_count': files_count,
                        'total_size': total_size,
                        'last_accessed': datetime.now().isoformat()
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"Ошибка обновления статистики: {e}")

    async def can_modify_codebase(self, user_id: str, codebase_id: str) -> Tuple[bool, str]:
        """Проверяет может ли пользователь модифицировать кодовую базу"""
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
    
        if not config:
            return False, "Кодовая база не найдена"
    
        # Проверка devnull
        if config.get("is_system") or config.get("folder_name") == "devnull":
            return False, "Системная база devnull защищена от изменений"
    
        # Проверка публичных баз
        if config.get("is_readonly_for_user"):
            return False, "У вас нет прав на изменение этой публичной базы"
    
        # Проверка скрытых баз
        if config.get("hidden"):
            return False, "База скрыта и недоступна для изменений"
    
        return True, "OK"

    async def list_files_for_agent(self, user_id: str, codebase_id: str, 
                                   page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        """Версия для агентов - может читать публичные базы"""
        try:
            # Для агентов разрешаем чтение публичных баз
            files_dir = self.codebase_manager._get_codebase_dir(user_id, codebase_id)
            files_dir = os.path.join(files_dir, "files")
        
            if not os.path.exists(files_dir):
                return {
                    'files': [],
                    'total': 0,
                    'page': 1,
                    'total_pages': 0,
                    'per_page': per_page,
                    'start_idx': 0,
                    'end_idx': 0
                }

            # Остальная логика как в обычном list_files
            all_files = []
            for filename in os.listdir(files_dir):
                file_path = os.path.join(files_dir, filename)
                if os.path.isfile(file_path):
                    stat = os.stat(file_path)
                    all_files.append({
                        'name': filename,
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        'is_text': self.is_text_file(filename)
                    })

            all_files.sort(key=lambda x: x['name'].lower())
        
            total = len(all_files)
            total_pages = (total + per_page - 1) // per_page
        
            if page < 1:
                page = 1
            elif page > total_pages and total_pages > 0:
                page = total_pages
            
            start_idx = (page - 1) * per_page
            end_idx = min(start_idx + per_page, total)

            return {
                'files': all_files[start_idx:end_idx],
                'total': total,
                'page': page,
                'total_pages': total_pages,
                'per_page': per_page,
                'start_idx': start_idx + 1 if total > 0 else 0,
                'end_idx': end_idx
            }

        except Exception as e:
            logger.error(f"Ошибка получения списка файлов для агента: {e}")
            return {
                'files': [],
                'total': 0,
                'page': 1,
                'total_pages': 0,
                'per_page': per_page
            }

    async def get_file_for_agent(self, user_id: str, codebase_id: str, filename: str) -> Optional[bytes]:
        """Версия для агентов - может читать из публичных баз"""
        try:
            files_dir = self.codebase_manager._get_codebase_dir(user_id, codebase_id)
            file_path = os.path.join(files_dir, "files", filename)

            if not os.path.exists(file_path):
                return None

            if self.is_text_file(filename):
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    return content.encode('utf-8')
            else:
                async with aiofiles.open(file_path, 'rb') as f:
                    return await f.read()

        except Exception as e:
            logger.error(f"Ошибка чтения файла агентом {filename}: {e}")
            return None