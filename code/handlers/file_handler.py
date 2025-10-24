# code/handlers/file_handler.py
"""
Основной модуль обработки операций с файлами
Координирует работу всех подмодулей
"""
import logging
from aiogram import types, F
from aiogram.fsm.context import FSMContext

from .file_operations.upload_handler import FileUploadHandler
from .file_operations.download_handler import FileDownloadHandler
from .file_operations.delete_handler import FileDeleteHandler
from .file_operations.search_handler import FileSearchHandler
from .file_operations.list_handler import FileListHandler
from .file_operations.states import FileStates

logger = logging.getLogger(__name__)


class FileHandler:
    """Главный обработчик операций с файлами"""
    
    def __init__(self, bot, user_manager, codebase_manager, file_manager):
        self.bot = bot
        self.user_manager = user_manager
        self.codebase_manager = codebase_manager
        self.file_manager = file_manager
        self.agent_handler = None
        
        # Инициализация подмодулей
        self.upload_handler = FileUploadHandler(bot, user_manager, codebase_manager, file_manager)
        self.download_handler = FileDownloadHandler(bot, user_manager, codebase_manager, file_manager)
        self.delete_handler = FileDeleteHandler(bot, user_manager, codebase_manager, file_manager)
        self.search_handler = FileSearchHandler(bot, user_manager, codebase_manager, file_manager)
        self.list_handler = FileListHandler(bot, user_manager, codebase_manager, file_manager)
    
    def set_agent_handler(self, agent_handler):
        """Установить ссылку на agent_handler для макро-команд"""
        self.agent_handler = agent_handler
        self.upload_handler.agent_handler = agent_handler

    def register_handlers(self, dp):
        """Регистрация обработчиков в диспетчере"""
        # Команды для файлов
        dp.message.register(self.list_handler.cmd_files, F.text == "/files")
        dp.message.register(self.search_handler.cmd_search_files, F.text == "/search")
        dp.message.register(self.delete_handler.cmd_delete_files, F.text == "/delete")
        dp.message.register(self.download_handler.cmd_download_files, F.text == "/download")
        dp.message.register(self.cmd_cancel_file_job, F.text == "/cancel_file_job")
        
        # Обработчики состояний для файлов
        dp.message.register(self.search_handler.process_file_search, FileStates.searching_files)
        dp.message.register(self.delete_handler.process_files_to_delete, FileStates.selecting_files_to_delete)
        dp.message.register(self.download_handler.process_files_to_download, FileStates.selecting_files_to_download)
        
        # Callback обработчики для файлов
        dp.callback_query.register(
            self.handle_file_callback,
            F.data.startswith("replace_file:")
            | F.data.startswith("skip_file:")
            | F.data.startswith("enc:")
            | F.data.startswith("files_page:")
            | F.data.startswith("confirm_delete:")
            | F.data.startswith("conv:")
            | F.data.startswith("save_as:")
            | F.data.startswith("save_converted:")
            | F.data.startswith("search_download:")
            | F.data.startswith("search_delete:")
            | F.data.startswith("search_action:")
            | F.data.startswith("save_audio:")  
            | F.data.startswith("save_voice:")
            | F.data.startswith("save_new_file:")      
            | F.data.startswith("cancel_new_file:")    
            | F.data.startswith("save_new_after_enc:")
            | F.data.startswith("cancel_new_after_enc:")
        )
        
        # Обработка загрузки документов
        dp.message.register(self.upload_handler.handle_document, F.document)
        
        # Обработка загрузки фотографий
        dp.message.register(self.upload_handler.handle_photo, F.photo)

        # Обработка голосовых сообщений
        dp.message.register(self.upload_handler.handle_voice, F.voice)
        # Обработка аудио файлов
        dp.message.register(self.upload_handler.handle_audio, F.audio)
    
    async def cmd_cancel_file_job(self, message: types.Message, state: FSMContext):
        """Обработка команды отмены файловых операций"""
        user_id = str(message.from_user.id)
        current_state = await state.get_state()
        
        if current_state == FileStates.processing_pdf.state:
            # Отмена обработки PDF
            await state.update_data(cancel_requested=True)
            await message.reply(
                "⚠️ Запрос на отмену сканирования PDF...\n"
                "Будет сохранено то, что уже распознано."
            )
        elif current_state in [
            FileStates.searching_files.state,
            FileStates.selecting_files_to_delete.state,
            FileStates.selecting_files_to_download.state
        ]:
            # Отмена других файловых операций
            await state.clear()
            await message.reply("❌ Операция отменена.")
        else:
            await message.reply("Нет активных файловых операций для отмены.")
    
    async def handle_file_callback(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка callback для файлов"""
        data = callback.data
        
        if data.startswith("replace_file:") or data.startswith("skip_file:"):
            await self.upload_handler.handle_file_replacement_callback(callback, state)
            
        elif data.startswith("enc:"):
            await self.upload_handler.handle_encoding_callback(callback, state)
        
        elif data.startswith("conv:"):
            await self.upload_handler.handle_conversion_callback(callback, state)
        
        elif data.startswith("save_as:"):
            await self.upload_handler.handle_save_as_callback(callback, state)
        
        elif data.startswith("save_converted:"):
            await self.upload_handler.handle_save_converted_callback(callback, state)

        elif data.startswith("save_audio:") or data.startswith("save_voice:"):
            await self.upload_handler.handle_audio_save_callback(callback, state)
        
        elif data.startswith("save_new_file:"):
            await self.upload_handler.callback_processor.handle_save_new_file(callback, state)
    
        elif data.startswith("cancel_new_file:"):
            await self.upload_handler.callback_processor.handle_cancel_new_file(callback, state)

        elif data.startswith("save_new_after_enc:"):
            await self.upload_handler.callback_processor.handle_save_new_after_encoding(callback, state)
    
        elif data.startswith("cancel_new_after_enc:"):
            await self.upload_handler.callback_processor.handle_cancel_new_after_encoding(callback, state)

        elif data.startswith("files_page:"):
            await self.list_handler.handle_page_callback(callback, state)
        
        elif data.startswith("confirm_delete:"):
            await self.delete_handler.handle_confirm_callback(callback, state)
        
        elif data.startswith("search_download:") or data.startswith("search_delete:") or data.startswith("search_action:"):
            await self.search_handler.handle_search_callback(callback, state)