# code/handlers/file_operations/upload_handler.py
"""
Модуль обработки загрузки файлов
"""
import asyncio
import os
import secrets
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from aiogram import types
from aiogram.fsm.context import FSMContext

from .states import FileStates
from .base import BaseFileHandler
from .processors import (
    AudioProcessor,
    ImageProcessor, 
    DocumentProcessor,
    TableProcessor,
    TextFileProcessor
)
from .callbacks import CallbackProcessor
from converters.audio_converter import AudioConverter
from agents.rag_singleton import get_rag_manager

from user_activity_logger import activity_logger

logger = logging.getLogger(__name__)


class FileUploadHandler(BaseFileHandler):
    """Обработчик загрузки файлов"""
    
    def __init__(self, bot, user_manager, codebase_manager, file_manager):
        super().__init__(bot, user_manager, codebase_manager, file_manager)
        self.rag_manager = get_rag_manager()

        # Ссылка на SimpleAgentHandler для перенаправления agent config файлов
        self.agent_handler = None

        # Инициализация аудио конвертера если есть OpenAI ключ
        from config import Config
        self.audio_converter = None
        if Config.OPENAI_API_KEY:
            self.audio_converter = AudioConverter(Config.OPENAI_API_KEY)

        # Временное хранилище для обработки файлов
        self.pending_files = {}  # {user_id: [{file_info}, ...]}
        
        # Инициализация процессоров
        self.audio_processor = AudioProcessor(self)
        self.image_processor = ImageProcessor(self)
        self.document_processor = DocumentProcessor(self)
        self.table_processor = TableProcessor(self)
        self.text_processor = TextFileProcessor(self)
        self.callback_processor = CallbackProcessor(self)

    def _is_agent_config_file(self, filename: str) -> bool:
        """Проверяет, является ли файл конфигурацией агента"""
        if not filename.endswith('.json'):
            return False
        
        # Проверяем паттерн agent_*.json
        return filename.startswith('agent_') and filename.endswith('_config.json')

    def set_agent_handler(self, agent_handler):
        """Установка ссылки на SimpleAgentHandler"""
        self.agent_handler = agent_handler
        # Добавляем обратную ссылку для Upload агента
        if hasattr(agent_handler, 'system_agents') and 'upload' in agent_handler.system_agents:
            # Передаем ссылку на upload_handler в Upload агент напрямую
            upload_agent = agent_handler.system_agents['upload']
            # Сохраняем ссылку на FileUploadHandler прямо в агенте
            upload_agent.upload_handler = self
            logger.info("Upload агент связан с FileUploadHandler")

    async def handle_voice(self, message: types.Message, state: FSMContext):
        """Обработка голосовых сообщений Telegram"""
        await self.audio_processor.handle_voice(message, state)

    async def handle_audio(self, message: types.Message, state: FSMContext):
        """Обработка аудио файлов (не голосовых сообщений)"""
        await self.audio_processor.handle_audio(message, state)

    async def handle_photo(self, message: types.Message, state: FSMContext):
        """Обработка загруженных фотографий"""
        await self.image_processor.handle_photo(message, state)

    async def handle_document(self, message: types.Message, state: FSMContext):
        """Обработка загруженных файлов"""
        user_id = str(message.from_user.id)
        
        # Проверяем доступ
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return

        # ПРОВЕРЯЕМ, НЕ ЯВЛЯЕТСЯ ЛИ ФАЙЛ КОНФИГУРАЦИЕЙ АГЕНТА
        if self._is_agent_config_file(message.document.file_name) and self.agent_handler:
            logger.info(f"Перенаправляем {message.document.file_name} в agent handler")
            await self.agent_handler.handle_agent_config_upload(message)
            return

        # ПРОВЕРЯЕМ НАЛИЧИЕ АКТИВНОГО АГЕНТА
        # Если есть активный агент (чат, filejob и т.д.), перенаправляем туда
        if self.agent_handler:
            handled = await self.agent_handler.handle_document_for_active_agent(message, state)
            if handled:
                return
        
        # ОБЫЧНАЯ ОБРАБОТКА ФАЙЛОВ (НЕТ АКТИВНОГО ЧАТА)
        # Проверяем наличие активной кодовой базы
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if not user_codebases["active"]:
            await message.reply(
                "⌠Нет активной кодовой базы.\n"
                "Создайте или выберите кодовую базу для загрузки файлов.\n"
                "/create_codebase - создать новую\n"
                "/codebases - список баз"
            )
            return
        
        document = message.document
        if not document:
            return
        
        # Проверяем размер файла
        from config import Config
        max_size = Config.get("max_file_size", 5242880)  # 5MB по умолчанию
        if document.file_size > max_size:
            await message.reply(
                f"⌠Файл слишком большой.\n"
                f"Максимальный размер: {self.file_manager.format_size(max_size)}\n"
                f"Размер вашего файла: {self.file_manager.format_size(document.file_size)}"
            )
            return
        
        # Обрабатываем загрузку
        await self._process_file_upload(message, document, state)

    async def _process_file_upload(self, message: types.Message, document: types.Document, 
                                  state: FSMContext, existing_token: Optional[str] = None):
        """Внутренний метод обработки загрузки файла"""
        user_id = str(message.from_user.id)
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
        
        processing_msg = await message.reply(f"⏳ Загружаю файл '{document.file_name}'...")
        
        try:
            tg_file = await self.bot.get_file(document.file_id)
            stream = await self.bot.download_file(tg_file.file_path)
            file_bytes = stream.getvalue() if hasattr(stream, "getvalue") else stream
            
            orig_name = document.file_name
            ext = os.path.splitext(orig_name.lower())[1]
            
            # Обработка различных типов файлов
            if ext == ".pdf":
                await self.document_processor.process_pdf_file(
                    message, processing_msg, orig_name, file_bytes, state, user_id, codebase_id
                )
            elif self._is_audio_file(orig_name) and self.audio_converter:
                await self.audio_processor.process_audio_file(
                    message, processing_msg, orig_name, file_bytes, user_id, codebase_id, state
                )
            elif ext in {".html", ".htm", ".xhtml"}:
                await self.document_processor.process_html_file(
                    message, processing_msg, orig_name, file_bytes, user_id, codebase_id
                )
            elif ext in {".ppt", ".pptx"}:
                await self.document_processor.process_powerpoint_file(
                    message, processing_msg, orig_name, file_bytes, user_id, codebase_id
                )
            elif self._is_image_file(orig_name):
                await self.image_processor.process_image_file(
                    message, processing_msg, orig_name, file_bytes, document, user_id, existing_token
                )
            elif ext in {".xls", ".xlsx", ".csv"}:
                await self.table_processor.process_table_file(
                    message, processing_msg, orig_name, file_bytes, document, ext, user_id, existing_token
                )
            elif ext in {".docx", ".rtf", ".odt"}:
                await self.document_processor.process_document_file(
                    message, processing_msg, orig_name, file_bytes, user_id, codebase_id
                )
            else:
                await self.text_processor.process_regular_file(
                    message, processing_msg, document, file_bytes, user_id, codebase_id, existing_token
                )                
            
            activity_logger.log(user_id, "FILE_UPLOAD", f"file={document.file_name},size={document.file_size}")

            # Запускаем инкрементальную индексацию в фоне
            asyncio.create_task(self._update_rag_index(user_id, codebase_id, document.file_name))       

        except Exception as e:
            logger.error(f"Ошибка загрузки файла: {e}", exc_info=True)
            await processing_msg.edit_text(f"⌠Ошибка загрузки файла: {str(e)}")

    async def _update_rag_index(self, user_id: str, codebase_id: str, filename: str):
        """Обновление RAG индекса после загрузки файла"""
        try:
            # Проверяем, является ли файл текстовым
            if not self.rag_manager._is_text_file(filename):
                logger.debug(f"Файл {filename} не текстовый, пропускаем индексацию")
                return
        
            # Получаем путь к файлам
            codebase_dir = self.codebase_manager._get_codebase_dir(user_id, codebase_id)
            files_dir = os.path.join(codebase_dir, "files")
    
            # Инкрементальное обновление
            success, msg = await self.rag_manager.update_incremental(
                user_id=user_id,
                codebase_id=codebase_id,
                files_dir=files_dir
            )
    
            if success and "обновлено 0 файлов" not in msg.lower():
                logger.info(f"RAG индекс обновлен после загрузки {filename}")
            else:
                logger.debug(f"RAG индекс проверен для {filename}: {msg}")
        
        except Exception as e:
            logger.error(f"Ошибка обновления RAG индекса: {e}")

    def _is_audio_file(self, filename: str) -> bool:
        """Проверяет, является ли файл аудио"""
        if not self.audio_converter:
            return False
        return self.audio_converter.supports(filename)

    def _is_image_file(self, filename: str) -> bool:
        """Проверяет, является ли файл изображением"""
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp'}
        ext = os.path.splitext(filename.lower())[1]
        return ext in image_extensions

    # Callback handlers
    async def handle_file_replacement_callback(self, callback: types.CallbackQuery, state: FSMContext):
        await self.callback_processor.handle_file_replacement(callback, state)

    async def handle_encoding_callback(self, callback: types.CallbackQuery, state: FSMContext):
        await self.callback_processor.handle_encoding(callback, state)

    async def handle_conversion_callback(self, callback: types.CallbackQuery, state: FSMContext):
        await self.callback_processor.handle_conversion(callback, state)

    async def handle_save_as_callback(self, callback: types.CallbackQuery, state: FSMContext):
        await self.callback_processor.handle_save_as(callback, state)

    async def handle_save_converted_callback(self, callback: types.CallbackQuery, state: FSMContext):
        await self.callback_processor.handle_save_converted(callback, state)

    async def handle_audio_save_callback(self, callback: types.CallbackQuery, state: FSMContext):
        await self.callback_processor.handle_audio_save(callback, state)