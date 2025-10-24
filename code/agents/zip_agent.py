# code/agents/zip_agent.py

import os
import json
import logging
import zipfile
import tempfile
import shutil
import re
import asyncio  # Add this line
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from utils.markdown_utils import escape_markdown_v2
from agents.rag_singleton import get_rag_manager  

from converters.markdown_converter import MarkdownConverterManager
from converters.encoding_converter import EncodingConverter

try:
    import py7zr
    HAS_7Z_SUPPORT = True
except ImportError:
    HAS_7Z_SUPPORT = False
    logging.warning("py7zr не установлен. Поддержка 7z архивов отключена")

logger = logging.getLogger(__name__)


class ZipAgent:
    """Агент для распаковки архивов и сохранения текстовых файлов в кодовую базу"""
    
    def __init__(self):
        self.name = "zip"
        self.config = self._load_default_config()
        self.processing_jobs = {}  # Активные задачи обработки
        self.rag_manager = get_rag_manager()
        self.markdown_converter = MarkdownConverterManager(ai_interface=None)  # Без AI
        self.encoding_converter = EncodingConverter()
        
    def _load_default_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации по умолчанию"""
        config_path = os.path.join(os.path.dirname(__file__), "configs", "zip_default.json")
        
        default_config = {
            "name": "zip",
            "type": "archive",
            "description": "Распаковка архивов и сохранение текстовых файлов в кодовую базу",
            "supported_formats": [".zip", ".7z"],
            "max_archive_size": 52428800,  # 50MB
            "max_total_extracted_size": 104857600,  # 100MB
            "max_file_size": 5242880,  # 5MB
            "max_files_count": 500
        }
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    default_config.update(loaded_config)
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига ZIP агента: {e}")
                
        return default_config
    
    async def activate(self, message: types.Message, user_id: str, agent_handler) -> bool:
        """
        Активация агента для обработки архивов
        Возвращает True если активация успешна, False если есть проблемы
        """
        from utils.markdown_utils import escape_markdown_v2
    
        # Получаем компоненты
        codebase_manager = agent_handler.codebase_manager
        user_manager = agent_handler.user_manager
    
        # Проверяем наличие активной кодовой базы
        user_codebases = await codebase_manager.get_user_codebases(user_id)
        active_codebase_id = user_codebases.get('active')
    
        if not active_codebase_id:
            await message.reply(
                "⚠️ *Нет активной кодовой базы*\n\n"
                "Создайте или выберите кодовую базу:\n"
                "/create\\_codebase \\- создать новую\n"
                "/codebases \\- список баз",
                parse_mode="MarkdownV2"
            )
            return False
    
        # Получаем информацию о базе
        codebase_info = await codebase_manager.get_codebase_config(user_id, active_codebase_id)
        codebase_name = escape_markdown_v2(codebase_info.get('name', active_codebase_id) if codebase_info else active_codebase_id)
    
        # Проверяем права доступа для публичных баз
        if codebase_info and codebase_info.get('is_public'):
            if codebase_info.get('owner_id') != user_id:
                # Получаем информацию о владельце через user_manager
                owner_data = await user_manager.get_user(codebase_info.get('owner_id'))
                owner_name = "Неизвестен"
                if owner_data:
                    first_name = owner_data.get('name', '')
                    last_name = owner_data.get('surname', '')
                    username = owner_data.get('telegram_username', '')
                
                    if first_name or last_name:
                        owner_name = f"{first_name} {last_name}".strip()
                    elif username and username != "Не указан":
                        owner_name = f"@{username}"
                    else:
                        owner_name = f"User_{codebase_info.get('owner_id', '')[:8]}"
            
                await message.reply(
                    f"⚠️ *Недостаточно прав*\n\n"
                    f"Активная база: `{codebase_name}` \\(публичная\\)\n"
                    f"Владелец: {escape_markdown_v2(owner_name)}\n\n"
                    f"Вы не можете добавлять файлы в чужую публичную базу\\.\n"
                    f"Переключитесь на свою базу или создайте новую\\.",
                    parse_mode="MarkdownV2"
                )
                return False
    
        # Формируем информацию о базе
        base_type = "📚 Публичная" if codebase_info and codebase_info.get('is_public') else "🔒 Личная"
    
        # Получаем актуальную статистику файлов
        files_count, total_size = await codebase_manager.get_live_stats(user_id, active_codebase_id)
    
        # Показываем информацию об активации
        await message.reply(
            f"📦 *Агент @{escape_markdown_v2(self.name)} активирован*\n\n"
            f"📂 *Активная кодовая база:*\n"
            f"Название: `{codebase_name}`\n"
            f"Тип: {base_type}\n"
            f"Файлов: {files_count}\n\n"
            f"*Теперь отправьте архив для обработки:*\n"
            f"• Поддерживаемые форматы: \\.zip, \\.7z\n"
            f"• Максимальный размер: {self.config.get('max_archive_size', 52428800) // (1024*1024)} МБ\n"
            f"• Будут извлечены текстовые файлы и документы\n"
            f"• Поддержка: \\.txt, \\.pdf, \\.docx, \\.xlsx и др\\.\n\n"
            f"Файлы будут сохранены в указанную базу\n"
            f"Пути преобразуются в безопасные имена\n\n"
            f"💡 Команды:\n"
            f"/codebases \\- сменить базу\n"
            f"/agent\\_stop \\- отменить",
            parse_mode="MarkdownV2"
        )
    
        return True

    def _is_text_file(self, filename: str) -> bool:
        """Проверка, является ли файл текстовым или конвертируемым"""
        from config import Config
        # Проверяем обычные текстовые файлы
        if Config.is_text_file(filename):
            return True
        # Проверяем файлы, которые можем конвертировать
        return self.markdown_converter.can_convert(filename)

    def _sanitize_path(self, path: str) -> str:
        """Преобразование пути файла в безопасное имя с сохранением русских букв"""
        import re
    
        # Нормализуем путь
        path = path.replace('\\', '/')
    
        # Убираем начальный слеш если есть
        path = path.lstrip('/')
    
        # Разделяем на путь и расширение
        base_path, ext = os.path.splitext(path)
    
        # Заменяем разделители путей на подчеркивания (flatten structure)
        flat_name = base_path.replace('/', '_')
    
        # Заменяем пробелы на подчеркивания
        flat_name = flat_name.replace(' ', '_')
    
        # Приводим к нижнему регистру
        flat_name = flat_name.lower()
        ext = ext.lower()
    
        # Удаляем опасные символы, но сохраняем русские буквы
        flat_name = re.sub(r'[^а-яёa-z0-9._-]', '_', flat_name)
    
        # Убираем множественные подчеркивания
        flat_name = re.sub(r'_{2,}', '_', flat_name)
    
        # Убираем подчеркивания в начале и конце
        flat_name = flat_name.strip('_')
    
        # Собираем полное имя
        result = flat_name + ext
    
        # Обрезаем до максимальной длины если нужно
        max_length = 255
        if len(result) > max_length:
            max_name_length = max_length - len(ext) - 10
            flat_name = flat_name[:max_name_length]
            result = flat_name + ext
    
        # Если имя пустое после обработки
        if not flat_name:
            result = f"file_{hash(path)[:8]}{ext}"
    
        return result    
    
    def _decode_content(self, content: bytes, filename: str) -> Optional[str]:
        """Декодирование содержимого файла с учетом различных кодировок"""
        encoding_config = self.config.get('encoding', {})
        
        # Сначала пробуем основную кодировку
        primary = encoding_config.get('primary', 'utf-8')
        try:
            return content.decode(primary)
        except (UnicodeDecodeError, LookupError):
            pass
        
        # Пробуем резервные кодировки
        fallback_encodings = encoding_config.get('fallback_encodings', [
            'cp1251', 'cp866', 'koi8-r', 'iso-8859-5', 'latin-1', 'ascii'
        ])
        
        for encoding in fallback_encodings:
            try:
                return content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        
        # Если ничего не подошло и включено принудительное декодирование
        if encoding_config.get('force_decode', True):
            errors = encoding_config.get('decode_errors', 'replace')
            try:
                # Пробуем с заменой некорректных символов
                return content.decode('utf-8', errors=errors)
            except:
                try:
                    return content.decode('latin-1', errors=errors)
                except:
                    logger.error(f"Не удалось декодировать файл {filename}")
                    return None
        
        return None
    
    def _should_skip_file(self, path: str, size: int) -> Tuple[bool, str]:
        """Проверка, нужно ли пропустить файл"""
        filter_config = self.config.get('file_filters', {})
        
        # Проверяем размер
        max_file_size = self.config.get('max_file_size', 5242880)
        if size > max_file_size:
            return True, f"размер превышает лимит ({size} > {max_file_size})"
        
        # Проверяем на пустой файл
        if filter_config.get('skip_empty', True) and size == 0:
            return True, "пустой файл"
        
        # Проверяем на скрытые файлы
        basename = os.path.basename(path)
        if filter_config.get('skip_hidden', True) and basename.startswith('.'):
            return True, "скрытый файл"
        
        # Проверяем системные паттерны
        if filter_config.get('skip_system', True):
            system_patterns = filter_config.get('system_patterns', [])
            for pattern in system_patterns:
                if pattern in path:
                    return True, f"системный файл/папка ({pattern})"
        
        # Проверяем на подозрительные расширения
        security_config = self.config.get('security', {})
        if security_config.get('scan_for_suspicious', True):
            _, ext = os.path.splitext(path.lower())
            suspicious_exts = security_config.get('suspicious_extensions', [])
            if ext in suspicious_exts:
                return True, f"подозрительное расширение ({ext})"
        
        # Проверяем на path traversal
        if security_config.get('block_path_traversal', True):
            if '..' in path or path.startswith('/') or ':' in path:
                return True, "попытка выхода за пределы директории"
        
        return False, ""
    
    async def _extract_zip(self, archive_path: str, temp_dir: str) -> Tuple[List[Dict], List[str]]:
        """Извлечение файлов из ZIP архива"""
        extracted_files = []
        errors = []
        
        try:
            with zipfile.ZipFile(archive_path, 'r') as zip_file:
                # Получаем список файлов
                file_list = zip_file.namelist()
                
                for file_path in file_list:
                    try:
                        # Получаем информацию о файле
                        info = zip_file.getinfo(file_path)
                        
                        # Пропускаем директории
                        if info.is_dir():
                            continue
                        
                        # Проверяем, нужно ли пропустить файл
                        should_skip, reason = self._should_skip_file(file_path, info.file_size)
                        if should_skip:
                            logger.debug(f"Пропускаем {file_path}: {reason}")
                            continue
                        
                        # Проверяем, что это текстовый файл
                        if not self._is_text_file(file_path):
                            logger.debug(f"Пропускаем нетекстовый файл: {file_path}")
                            continue
                        
                        # Читаем содержимое
                        content = zip_file.read(file_path)
                        
                        # Определяем, нужна ли конвертация
                        if self.markdown_converter.can_convert(file_path):
                            # Конвертируем документ в markdown
                            success, new_filename, text_content = await self.markdown_converter.convert_to_markdown(
                                user_id="system",  # Временный ID для конвертации
                                file_bytes=content,
                                filename=file_path
                            )
    
                            if not success or not text_content:
                                errors.append(f"Не удалось конвертировать: {file_path}")
                                continue
    
                            # Меняем расширение на .txt в safe_name
                            base_name = os.path.splitext(file_path)[0]
                            safe_name = self._sanitize_path(f"{base_name}.txt")
                        else:
                            # Обычный текстовый файл - декодируем
                            text_content = self._decode_content(content, file_path)
                            if text_content is None:
                                errors.append(f"Не удалось декодировать: {file_path}")
                                continue
    
                            # Преобразуем путь
                            safe_name = self._sanitize_path(file_path)
                        
                        extracted_files.append({
                            'original_path': file_path,
                            'safe_name': safe_name,
                            'content': text_content,
                            'size': len(text_content)
                        })
                        
                    except Exception as e:
                        error_msg = str(e) if hasattr(e, '__str__') else repr(e)
                        errors.append(f"Ошибка обработки {file_path}: {error_msg}")
                        logger.error(f"Ошибка извлечения файла {file_path}: {error_msg}")
                        
        except Exception as e:
            errors.append(f"Ошибка открытия ZIP архива: {str(e)}")
            logger.error(f"Ошибка работы с ZIP архивом: {e}")
            
        return extracted_files, errors

    async def _extract_7z(self, archive_path: str, temp_dir: str) -> Tuple[List[Dict], List[str]]:
        """Извлечение файлов из 7z архива"""
        if not HAS_7Z_SUPPORT:
            return [], ["Поддержка 7z архивов не установлена. Установите py7zr: pip install py7zr"]
    
        extracted_files = []
        errors = []
    
        try:
            with py7zr.SevenZipFile(archive_path, mode='r') as archive:
                # Извлекаем все файлы во временную директорию
                archive.extractall(path=temp_dir)
            
                # Получаем список всех файлов через getnames()
                all_files = archive.getnames()
            
                for file_path in all_files:
                    try:
                        # Полный путь к извлеченному файлу
                        full_path = os.path.join(temp_dir, file_path)
                    
                        # Пропускаем директории
                        if os.path.isdir(full_path):
                            continue
                    
                        # Проверяем существование файла
                        if not os.path.exists(full_path):
                            logger.debug(f"Файл не найден после извлечения: {full_path}")
                            continue
                    
                        # Получаем размер файла
                        file_size = os.path.getsize(full_path)
                    
                        # Проверяем, нужно ли пропустить файл
                        should_skip, reason = self._should_skip_file(file_path, file_size)
                        if should_skip:
                            logger.debug(f"Пропускаем {file_path}: {reason}")
                            continue
                    
                        # Проверяем, что это текстовый файл
                        if not self._is_text_file(file_path):
                            logger.debug(f"Пропускаем нетекстовый файл: {file_path}")
                            continue
                    
                        # Читаем содержимое
                        with open(full_path, 'rb') as f:
                            content = f.read()
                    
                        # Определяем, нужна ли конвертация
                        if self.markdown_converter.can_convert(file_path):
                            # Конвертируем документ в markdown
                            success, new_filename, text_content = await self.markdown_converter.convert_to_markdown(
                                user_id="system",
                                file_bytes=content,
                                filename=file_path
                            )
    
                            if not success or not text_content:
                                errors.append(f"Не удалось конвертировать: {file_path}")
                                continue
    
                            # Меняем расширение на .txt в safe_name
                            base_name = os.path.splitext(file_path)[0]
                            safe_name = self._sanitize_path(f"{base_name}.txt")
                        else:
                            # Обычный текстовый файл - декодируем
                            text_content = self._decode_content(content, file_path)
                            if text_content is None:
                                errors.append(f"Не удалось декодировать: {file_path}")
                                continue
    
                            # Преобразуем путь
                            safe_name = self._sanitize_path(file_path)
                    
                        extracted_files.append({
                            'original_path': file_path,
                            'safe_name': safe_name,
                            'content': text_content,
                            'size': len(text_content)
                        })
                    
                        logger.debug(f"Успешно обработан файл: {file_path} -> {safe_name}")
                    
                    except Exception as e:
                        error_msg = str(e) if hasattr(e, '__str__') else repr(e)
                        errors.append(f"Ошибка обработки {file_path}: {error_msg}")
                        logger.error(f"Ошибка извлечения файла {file_path}: {error_msg}")
                    
        except Exception as e:
            errors.append(f"Ошибка открытия 7z архива: {str(e)}")
            logger.error(f"Ошибка работы с 7z архивом: {e}", exc_info=True)
    
        finally:
            # Очищаем временные файлы (кроме самого архива)
            try:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Не удаляем сам архив
                        if file_path != archive_path:
                            try:
                                os.remove(file_path)
                            except:
                                pass
                # Удаляем пустые директории
                for root, dirs, files in os.walk(temp_dir, topdown=False):
                    for dir_name in dirs:
                        try:
                            os.rmdir(os.path.join(root, dir_name))
                        except:
                            pass
            except Exception as e:
                logger.debug(f"Ошибка очистки временных файлов: {e}")
            
        return extracted_files, errors    
  
    async def handle_document(self, message: types.Message, state: FSMContext, agent_handler):
        """Обработка загруженного архива"""
        user_id = str(message.from_user.id)
    
        if not message.document:
            await message.reply("⚠️ Документ не найден", parse_mode="MarkdownV2")
            return
    
        # Проверяем формат файла
        filename = message.document.file_name.lower()
        _, ext = os.path.splitext(filename)
    
        supported_formats = self.config.get('supported_formats', ['.zip', '.7z'])
        if ext not in supported_formats:
            await message.reply(
                f"⚠️ *Неподдерживаемый формат архива*\n\n"
                f"Поддерживаются: {escape_markdown_v2(', '.join(supported_formats))}\n"
                f"Получен: {escape_markdown_v2(ext)}",
                parse_mode="MarkdownV2"
            )
            return
    
        # Проверяем размер
        max_size = self.config.get('max_archive_size', 52428800)
        if message.document.file_size > max_size:
            await message.reply(
                f"⚠️ *Архив слишком большой*\n\n"
                f"Максимальный размер: {max_size // (1024*1024)} МБ\n"
                f"Размер вашего архива: {message.document.file_size // (1024*1024)} МБ",
                parse_mode="MarkdownV2"
            )
            return
    
        # Получаем компоненты из agent_handler
        codebase_manager = agent_handler.codebase_manager
        file_manager = agent_handler.file_manager
        user_manager = agent_handler.user_manager
    
        # Проверяем наличие активной кодовой базы
        user_codebases = await codebase_manager.get_user_codebases(user_id)
        active_codebase_id = user_codebases.get('active')
    
        if not active_codebase_id:
            await message.reply(
                "⚠️ *Нет активной кодовой базы*\n\n"
                "Создайте или выберите кодовую базу:\n"
                "/create\\_codebase \\- создать новую\n"
                "/codebases \\- список баз",
                parse_mode="MarkdownV2"
            )
            return
    
        # Проверяем права доступа для публичных баз        
        codebase_info = await codebase_manager.get_codebase_config(user_id, active_codebase_id)
        if codebase_info and codebase_info.get('is_public'):
            if codebase_info.get('owner_id') != user_id:
                await message.reply(
                    "⚠️ *Недостаточно прав*\n\n"
                    "Вы не можете добавлять файлы в чужую публичную базу\\.\n"
                    "Переключитесь на свою базу или создайте новую\\.",
                    parse_mode="MarkdownV2"
                )
                return
    
        processing_msg = await message.reply(
            f"📦 *Обработка архива*\n\n"
            f"Файл: `{escape_markdown_v2(message.document.file_name)}`\n"
            f"Размер: {message.document.file_size // 1024} КБ\n\n"
            f"⏳ Загрузка\\.\\.\\.",
            parse_mode="MarkdownV2"
        )
    
        # Создаем временную директорию
        temp_dir = None
        temp_archive = None
    
        try:
            # Создаем временную директорию
            extraction_config = self.config.get('extraction', {})
            temp_base = extraction_config.get('temp_dir', 'temp_extract')
            temp_dir = tempfile.mkdtemp(prefix=f"{temp_base}_")
        
            # Загружаем архив
            file = await message.bot.get_file(message.document.file_id)
            file_data = await message.bot.download_file(file.file_path)
        
            # Сохраняем архив во временный файл
            temp_archive = os.path.join(temp_dir, f"archive{ext}")
            with open(temp_archive, 'wb') as f:
                if hasattr(file_data, 'read'):
                    f.write(file_data.read())
                else:
                    f.write(file_data)
        
            await processing_msg.edit_text(
                f"📦 *Обработка архива*\n\n"
                f"Файл: `{escape_markdown_v2(message.document.file_name)}`\n"
                f"Размер: {message.document.file_size // 1024} КБ\n\n"
                f"📂 Распаковка\\.\\.\\.",
                parse_mode="MarkdownV2"
            )
        
            # Извлекаем файлы в зависимости от формата
            if ext == '.zip':
                extracted_files, errors = await self._extract_zip(temp_archive, temp_dir)
            elif ext == '.7z':
                extracted_files, errors = await self._extract_7z(temp_archive, temp_dir)
            else:
                extracted_files, errors = [], [f"Неподдерживаемый формат: {ext}"]
        
            if not extracted_files and errors:
                await processing_msg.edit_text(
                    f"❌ *Ошибка распаковки*\n\n"
                    f"{escape_markdown_v2(chr(10).join(errors[:5]))}",
                    parse_mode="MarkdownV2"
                )
                return
        
            # Проверяем общий размер
            total_size = sum(f['size'] for f in extracted_files)
            max_total_size = self.config.get('max_total_extracted_size', 104857600)
            if total_size > max_total_size:
                await processing_msg.edit_text(
                    f"⚠️ *Превышен лимит размера*\n\n"
                    f"Общий размер файлов: {total_size // (1024*1024)} МБ\n"
                    f"Максимальный размер: {max_total_size // (1024*1024)} МБ",
                    parse_mode="MarkdownV2"
                )
                return
        
            # Проверяем количество файлов
            max_files = self.config.get('max_files_count', 500)
            if len(extracted_files) > max_files:
                extracted_files = extracted_files[:max_files]
                errors.append(f"Превышен лимит файлов. Обработано первые {max_files}")
        
            await processing_msg.edit_text(
                f"📦 *Обработка архива*\n\n"
                f"Файл: `{escape_markdown_v2(message.document.file_name)}`\n"
                f"Найдено текстовых файлов: {len(extracted_files)}\n\n"
                f"💾 Сохранение в базу\\.\\.\\.",
                parse_mode="MarkdownV2"
            )
        
            # Сохраняем файлы в кодовую базу
            saved_count = 0
            skipped_count = 0
            save_errors = []
            saved_files = []
        
            extraction_config = self.config.get('extraction', {})
            overwrite = extraction_config.get('overwrite_existing', False)
            add_index = extraction_config.get('add_index_on_conflict', True)
        
            for file_info in extracted_files:
                try:
                    safe_name = file_info['safe_name']
    
                    # Сохраняем файл (перезапишет если существует)
                    success, message_text, _ = await file_manager.save_file(
                        user_id=user_id,
                        codebase_id=active_codebase_id,
                        filename=safe_name,
                        file_data=file_info['content'].encode('utf-8'),
                        skip_conversion=True
                    )
    
                    if success:
                        saved_count += 1
                        saved_files.append({
                            'name': safe_name,
                            'original': file_info['original_path'],
                            'size': file_info['size']
                        })
                    else:
                        save_errors.append(f"Не удалось сохранить: {safe_name}")
                    
                except Exception as e:
                    save_errors.append(f"Ошибка сохранения {file_info['safe_name']}: {str(e)}")
                    logger.error(f"Ошибка сохранения файла: {e}")
            
                # При обновлении прогресса
                if saved_count % 10 == 0:
                    try:
                        await processing_msg.edit_text(
                            f"📦 *Обработка архива*\n\n"
                            f"💾 Сохранение: {saved_count}/{len(extracted_files)}\\.\\.\\.",
                            parse_mode="MarkdownV2"
                        )
                    except TelegramBadRequest:
                        pass  # Игнорируем, если сообщение не изменилось            

            # Получаем актуальную информацию о кодовой базе для отчета
            codebase_name = codebase_info.get('name', active_codebase_id) if codebase_info else active_codebase_id
        
            # Определяем тип базы и владельца для публичных баз
            base_type = "📚 Публичная" if codebase_info and codebase_info.get('is_public') else "🔒 Личная"
        
            # Получаем общее количество файлов в базе после добавления
            files_count, total_base_size = await codebase_manager.get_live_stats(user_id, active_codebase_id)
        
            # Формируем итоговый отчет
            report_text = f"✅ Архив обработан\n\n"
        
            # Добавляем информацию о кодовой базе
            report_text += f"📂 Кодовая база: {codebase_name}\n"
            report_text += f"   └ Тип: {base_type}\n"
            report_text += f"   └ ID: {active_codebase_id}\n"
            report_text += f"\n"
        
            report_text += f"📊 Статистика распаковки:\n"
            report_text += f"• Найдено текстовых файлов: {len(extracted_files)}\n"
            report_text += f"• Сохранено: {saved_count}\n"

            if skipped_count > 0:
                report_text += f"• Пропущено (существующие): {skipped_count}\n"

            if errors:
                report_text += f"• Ошибки распаковки: {len(errors)}\n"

            if save_errors:
                report_text += f"• Ошибки сохранения: {len(save_errors)}\n"

            # Информация о базе после добавления
            report_text += f"\n📁 Состояние базы:\n"
            report_text += f"   └ Всего файлов: {files_count}\n"
            report_text += f"   └ Общий размер: {file_manager.format_size(total_base_size)}\n"

            report_text += f"\n💡 Используйте /files для просмотра файлов"
            report_text += f"\n🔄 /switch для смены активной базы"

            # Экранируем всё сообщение целиком
            report = escape_markdown_v2(report_text)

            await processing_msg.edit_text(report, parse_mode="MarkdownV2")
        
            # Запускаем инкрементальную индексацию RAG в фоне если есть сохраненные файлы
            if saved_count > 0:
                asyncio.create_task(self._update_rag_index(
                    user_id,
                    active_codebase_id,
                    codebase_manager
                ))
        
        except Exception as e:
            logger.error(f"Ошибка обработки архива: {e}", exc_info=True)
            try:
                await processing_msg.edit_text(
                    f"❌ *Ошибка обработки*\n\n"
                    f"{escape_markdown_v2(str(e))}",
                    parse_mode="MarkdownV2"
                )
            except:
                await message.reply(
                    f"❌ Ошибка: {escape_markdown_v2(str(e))}",
                    parse_mode="MarkdownV2"
                )
    
        finally:
            # Очищаем временные файлы
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Временная директория {temp_dir} удалена")
                except Exception as e:
                    logger.error(f"Ошибка удаления временной директории: {e}")  
    async def _update_rag_index(self, user_id: str, codebase_id: str, codebase_manager):
        """Обновление RAG индекса после добавления файлов"""
        try:
            # Получаем путь к файлам
            codebase_dir = codebase_manager._get_codebase_dir(user_id, codebase_id)
            files_dir = os.path.join(codebase_dir, "files")
        
            # Инкрементальное обновление
            success, msg = await self.rag_manager.update_incremental(
                user_id=user_id,
                codebase_id=codebase_id,
                files_dir=files_dir
            )
        
            if success and "обновлено 0 файлов" not in msg.lower():
                logger.info(f"RAG индекс обновлен после распаковки архива: {msg}")
            else:
                logger.debug(f"RAG индекс проверен: {msg}")
            
        except Exception as e:
            logger.error(f"Ошибка обновления RAG индекса: {e}")
    
    async def process(self, user_id: str, query: str, context: Dict[str, Any]) -> Tuple[bool, str]:
        """Обработка запроса к агенту (для совместимости)"""
        return False, "❌ Агент @zip работает только с архивами\\.\n\nОтправьте \\.zip или \\.7z файл после вызова агента\\."
    
    def get_config(self) -> Dict[str, Any]:
        """Получение конфигурации агента"""
        return self.config.copy()
    
    def set_config(self, config: Dict[str, Any]):
        """Установка новой конфигурации"""
        self.config = config