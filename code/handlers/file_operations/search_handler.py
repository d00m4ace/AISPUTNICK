# code/handlers/file_operations/search_handler.py
"""
Модуль обработки поиска файлов
"""
import logging
from typing import List, Dict, Any
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .states import FileStates
from .base import BaseFileHandler

from utils.markdown_utils import escape_markdown_v2

logger = logging.getLogger(__name__)

class FileSearchHandler(BaseFileHandler):
    """Обработчик поиска файлов"""
    
    def __init__(self, bot, user_manager, codebase_manager, file_manager):
        super().__init__(bot, user_manager, codebase_manager, file_manager)
        # Хранилище результатов поиска для callback обработки
        self.search_results = {}  # {user_id: {'files': [...], 'pattern': '...'}}
    
    async def cmd_search_files(self, message: types.Message, state: FSMContext):
        """Начинает поиск файлов"""
        user_id = str(message.from_user.id)
    
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return
    
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if not user_codebases["active"]:
            text = (
                "❌ Нет активной кодовой базы\\.\n"
                "Выберите кодовую базу командой /switch"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        # Проверяем права доступа для публичных баз
        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
    
        if cb_info.get("is_public_ref"):
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            base_name = escape_markdown_v2(config['name']) if config else "Неизвестная база"
        
            text = (
                "❌ *Прямой поиск файлов недоступен\\!*\n\n"
                f"📂 База: {base_name}\n"
                f"🔒 Статус: Чужая публичная база\n\n"
                "Для поиска по коду используйте:\n"
                "✅ /agents \\- интеллектуальный поиск\n"
                "✅ RAG\\-индекс для семантического поиска\n\n"
                "Прямой доступ к файлам ограничен\\.\n"
                "_Это защищает структуру проекта владельца\\._"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        text = (
            "🔍 Введите часть имени файла для поиска:\n"
            "\\(или /cancel\\_file\\_job для отмены\\)"
        )
        await message.reply(text, parse_mode="MarkdownV2")
        await state.set_state(FileStates.searching_files)
    
    async def process_file_search(self, message: types.Message, state: FSMContext):
        """Обработка поиска файлов"""
        user_id = str(message.from_user.id)
        pattern = message.text.strip()
    
        if pattern.lower() == "/cancel_file_job":
            await state.clear()
            await message.reply("❌ Поиск отменён\\.", parse_mode="MarkdownV2")
            return
    
        if not pattern:
            await message.reply("❌ Пустой запрос\\. Попробуйте еще раз:", parse_mode="MarkdownV2")
            return
    
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
    
        files = await self.file_manager.search_files(user_id, codebase_id, pattern)
    
        if not files:
            pattern_escaped = escape_markdown_v2(pattern)
            text = (
                f"❌ Файлы с '{pattern_escaped}' в имени не найдены\\.\n"
                "Попробуйте другой запрос или /cancel\\_file\\_job для отмены\\."
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        # Сохраняем результаты поиска
        self.search_results[user_id] = {
            'files': files,
            'pattern': pattern,
            'codebase_id': codebase_id
        }
    
        # Формируем текст результатов
        files_count = escape_markdown_v2(str(len(files)))
        pattern_escaped = escape_markdown_v2(pattern)
    
        text = f"🔍 *Найдено файлов:* {files_count}\n"
        text += f"📝 *Запрос:* '{pattern_escaped}'\n\n"
    
        # Показываем первые 20 файлов
        for i, file in enumerate(files[:20], 1):
            icon = "📝" if file['is_text'] else "📦"
            name_escaped = escape_markdown_v2(file['name'])
            size_escaped = escape_markdown_v2(self.file_manager.format_size(file['size']))
            idx_escaped = escape_markdown_v2(str(i))
            text += f"{idx_escaped}\\. {icon} {name_escaped} \\({size_escaped}\\)\n"
    
        if len(files) > 20:
            remaining = escape_markdown_v2(str(len(files) - 20))
            text += f"\n\\.\\.\\. и еще {remaining} файлов"
    
        # Создаем клавиатуру с действиями
        keyboard = self._create_search_actions_keyboard(len(files))
    
        await message.reply(text, reply_markup=keyboard, parse_mode="MarkdownV2")
        await state.clear()
  
    def _create_search_actions_keyboard(self, files_count: int) -> InlineKeyboardMarkup:
        """Создает клавиатуру с действиями для результатов поиска"""
        buttons = []
        
        # Кнопки для скачивания
        if files_count <= 10:
            buttons.append([
                InlineKeyboardButton(
                    text=f"📥 Скачать все ({files_count} файлов)",
                    callback_data="search_download:all"
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text="📥 Скачать первые 10",
                    callback_data="search_download:first10"
                )
            ])
            if files_count > 5:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"📦 Скачать все в ZIP ({files_count} файлов)",
                        callback_data="search_download:zip"
                    )
                ])
        
        # Кнопка удаления
        buttons.append([
            InlineKeyboardButton(
                text=f"🗑️ Удалить найденные ({files_count} файлов)",
                callback_data="search_delete:confirm"
            )
        ])
        
        # Кнопки навигации
        buttons.append([
            InlineKeyboardButton(text="🔍 Новый поиск", callback_data="search_action:new"),
            InlineKeyboardButton(text="📂 Все файлы", callback_data="search_action:list")
        ])
        
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    async def handle_search_callback(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка callback кнопок поиска"""
        user_id = str(callback.from_user.id)
        action_type, action = callback.data.split(":", 1)
        
        if action_type == "search_download":
            await self._handle_download_action(callback, action)
        elif action_type == "search_delete":
            await self._handle_delete_action(callback, action)
        elif action_type == "search_action":
            await self._handle_navigation_action(callback, action, state)
        
        await callback.answer()
    
    async def _handle_download_action(self, callback: types.CallbackQuery, action: str):
        """Обработка действий скачивания"""
        user_id = str(callback.from_user.id)
        
        if user_id not in self.search_results:
            await callback.message.edit_text("❌ Результаты поиска устарели. Выполните поиск заново.")
            return
        
        search_data = self.search_results[user_id]
        files = search_data['files']
        codebase_id = search_data['codebase_id']
        
        await callback.message.edit_text("⏳ Подготовка файлов к отправке...")
        
        if action == "all":
            # Скачиваем все файлы (до 10)
            files_to_download = [f['name'] for f in files[:10]]
            await self._send_files(callback.message, user_id, codebase_id, files_to_download)
            
        elif action == "first10":
            # Скачиваем первые 10
            files_to_download = [f['name'] for f in files[:10]]
            await self._send_files(callback.message, user_id, codebase_id, files_to_download)
            
        elif action == "zip":
            # Создаем ZIP архив
            await self._send_files_as_zip(callback.message, user_id, codebase_id, files)
    

    async def _handle_delete_action(self, callback: types.CallbackQuery, action: str):
        """Обработка действий удаления"""
        user_id = str(callback.from_user.id)
    
        if user_id not in self.search_results:
            text = "❌ Результаты поиска устарели\\. Выполните поиск заново\\."
            await callback.message.edit_text(text, parse_mode="MarkdownV2")
            return
    
        search_data = self.search_results[user_id]
        files = search_data['files']
        pattern = search_data['pattern']
    
        if action == "confirm":
            # Показываем подтверждение
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Да, удалить", callback_data="search_delete:execute"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="search_delete:cancel")
                ]
            ])
        
            files_count = escape_markdown_v2(str(len(files)))
            pattern_escaped = escape_markdown_v2(pattern)
        
            text = (
                f"⚠️ *Подтверждение удаления*\n\n"
                f"Будут удалены {files_count} файлов, найденных по запросу '{pattern_escaped}'\\.\n"
                f"Это действие необратимо\\!\n\n"
                f"Вы уверены?"
            )
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="MarkdownV2")
        
        elif action == "execute":
            # Выполняем удаление
            codebase_id = search_data['codebase_id']
            files_to_delete = [f['name'] for f in files]
        
            await callback.message.edit_text("⏳ Удаление файлов\\.\\.\\.", parse_mode="MarkdownV2")
        
            deleted, total = await self.file_manager.delete_files(
                user_id, codebase_id, files_to_delete
            )
        
            # Очищаем результаты поиска
            del self.search_results[user_id]
        
            deleted_escaped = escape_markdown_v2(str(deleted))
            total_escaped = escape_markdown_v2(str(total))
        
            text = (
                f"✅ Удалено файлов: {deleted_escaped}/{total_escaped}\n\n"
                f"/files — список файлов\n"
                f"/search — новый поиск"
            )
            await callback.message.edit_text(text, parse_mode="MarkdownV2")
        
        elif action == "cancel":
            # Отмена удаления - возвращаем результаты поиска
            files_count = escape_markdown_v2(str(len(files)))
            pattern_escaped = escape_markdown_v2(pattern)
        
            text = f"🔍 *Найдено файлов:* {files_count}\n"
            text += f"📝 *Запрос:* '{pattern_escaped}'\n\n"
        
            for i, file in enumerate(files[:20], 1):
                icon = "📝" if file['is_text'] else "📦"
                name_escaped = escape_markdown_v2(file['name'])
                size_escaped = escape_markdown_v2(self.file_manager.format_size(file['size']))
                idx_escaped = escape_markdown_v2(str(i))
                text += f"{idx_escaped}\\. {icon} {name_escaped} \\({size_escaped}\\)\n"
        
            if len(files) > 20:
                remaining = escape_markdown_v2(str(len(files) - 20))
                text += f"\n\\.\\.\\. и еще {remaining} файлов"
        
            keyboard = self._create_search_actions_keyboard(len(files))
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="MarkdownV2")

    async def _handle_navigation_action(self, callback: types.CallbackQuery, action: str, state: FSMContext):
        """Обработка навигационных действий"""
        if action == "new":
            # Начинаем новый поиск
            text = (
                "🔍 Введите часть имени файла для поиска:\n"
                "\\(или /cancel\\_file\\_job для отмены\\)"
            )
            await callback.message.edit_text(text, parse_mode="MarkdownV2")
            await state.set_state(FileStates.searching_files)
        
        elif action == "list":
            # Показываем список всех файлов
            text = "📂 Используйте /files для просмотра всех файлов"
            await callback.message.edit_text(text, parse_mode="MarkdownV2")
   
   
    async def _send_files(self, message: types.Message, user_id: str, codebase_id: str, filenames: List[str]):
        """Отправляет файлы пользователю"""
        sent = 0
        not_sent = []
    
        for filename in filenames:
            file_data = await self.file_manager.get_file(user_id, codebase_id, filename)
            if file_data:
                try:
                    await message.reply_document(
                        types.BufferedInputFile(file_data, filename),
                        caption=f"📎 {filename}"
                    )
                    sent += 1
                except Exception as e:
                    logger.error(f"Ошибка отправки файла {filename}: {e}")
                    not_sent.append(filename)
    
        sent_escaped = escape_markdown_v2(str(sent))
        total_escaped = escape_markdown_v2(str(len(filenames)))
    
        result_msg = f"✅ Отправлено файлов: {sent_escaped}/{total_escaped}"
        if not_sent:
            result_msg += f"\n❌ Не удалось отправить:\n"
            for f in not_sent:
                result_msg += f"• {escape_markdown_v2(f)}\n"
        result_msg += "\n\n/search \\- новый поиск\n/files \\- список файлов"
    
        await message.reply(result_msg, parse_mode="MarkdownV2")
    
    async def _send_files_as_zip(self, message: types.Message, user_id: str, codebase_id: str, files: List[Dict[str, Any]]):
        """Отправляет файлы в виде ZIP архива"""
        import io
        import re
        from zipfile import ZipFile, ZIP_DEFLATED
        
        buf = io.BytesIO()
        total_count = len(files)
        
        with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
            for f in files:
                file_name = f['name']
                file_bytes = await self.file_manager.get_file(user_id, codebase_id, file_name)
                if file_bytes is None:
                    continue
                zf.writestr(file_name, file_bytes)
        
        buf.seek(0)
        
        # Генерируем имя архива
        search_data = self.search_results.get(user_id, {})
        pattern = search_data.get('pattern', 'search')
        safe_pattern = re.sub(r'[^A-Za-z0-9_\-]+', '_', pattern).strip('_')[:20] or "search"
        zip_name = f"search_{safe_pattern}_{total_count}files.zip"
        
        try:
            await message.reply_document(
                types.BufferedInputFile(buf.read(), zip_name),
                caption=f"📦 Результаты поиска '{pattern}' ({total_count} файлов)"
            )
            await message.reply(
                "✅ Архив отправлен!\n\n"
                "/search - новый поиск\n"
                "/files - список файлов"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки архива {zip_name}: {e}")
            await message.reply("❌ Не удалось отправить архив. Попробуйте скачать файлы по отдельности.")