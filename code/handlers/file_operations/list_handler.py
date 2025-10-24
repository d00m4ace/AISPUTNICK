# code/handlers/file_operations/list_handler.py
"""
Модуль обработки просмотра списка файлов
"""
import logging
from datetime import datetime
from typing import Optional
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .base import BaseFileHandler

from utils.markdown_utils import escape_markdown_v2

logger = logging.getLogger(__name__)


class FileListHandler(BaseFileHandler):
    """Обработчик просмотра списка файлов"""
    
    async def cmd_files(self, message: types.Message, page: int = 1):
        """Показывает список файлов в активной кодовой базе"""
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
            # Для чужих публичных баз запрещаем прямой просмотр файлов
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            base_name = escape_markdown_v2(config['name']) if config else "Неизвестная база"
        
            text = (
                "❌ *Прямой просмотр файлов недоступен\\!*\n\n"
                f"📂 База: {base_name}\n"
                f"🔒 Статус: Чужая публичная база\n\n"
                "Вы можете:\n"
                "✅ Использовать /agents для поиска по коду\n"
                "✅ Искать информацию через RAG\\-индекс\n"
                "✅ Читать содержимое через агентов\n\n"
                "Вы НЕ можете:\n"
                "❌ Просматривать список файлов напрямую\n"
                "❌ Скачивать файлы\n"
                "❌ Удалять или изменять файлы\n\n"
                "_Это ограничение защищает структуру проекта владельца_"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        # Для своих баз показываем список файлов
        await self._show_files_page(message, page, user_id=user_id)
      
    async def handle_page_callback(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка переключения страниц"""
        page_str = callback.data[11:]  # Убираем "files_page:"
    
        if page_str == "noop":
            await callback.answer()
            return
    
        try:
            page = int(page_str)
        except ValueError:
            await callback.answer()
            return
    
        # Проверяем права доступа
        user_id = str(callback.from_user.id)
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases.get("active")
        cb_info = user_codebases["codebases"].get(codebase_id, {}) if codebase_id else {}
        readonly = cb_info.get("is_public_ref", False)
    
        await self._show_files_page(
            callback.message,
            page,
            edit=True,
            user_id=user_id,
            readonly=readonly
        )
        await callback.answer()

    async def _show_files_page(self, message: types.Message, page: int = 1, edit: bool = False, *, user_id: Optional[str] = None, readonly: bool = False):
        """Показывает страницу со списком файлов"""
        uid = user_id or str(message.from_user.id)
    
        user_codebases = await self.codebase_manager.get_user_codebases(uid)
        codebase_id = user_codebases.get("active")
    
        if not codebase_id:
            txt = "❌ Нет активной кодовой базы\\.\nВыберите её командой /switch"
            return await (message.edit_text(txt, parse_mode="MarkdownV2") if edit else message.reply(txt, parse_mode="MarkdownV2"))
    
        config = await self.codebase_manager.get_codebase_config(uid, codebase_id)
        if not config:
            txt = "❌ Конфигурация активной кодовой базы не найдена\\. Выберите базу заново: /switch"
            return await (message.edit_text(txt, parse_mode="MarkdownV2") if edit else message.reply(txt, parse_mode="MarkdownV2"))
    
        files_data = await self.file_manager.list_files(uid, codebase_id, page, per_page=20)
        _, total_size = await self.codebase_manager.get_live_stats(uid, codebase_id)
    
        if files_data['total'] == 0:
            base_name = escape_markdown_v2(config['name'])
            text = (
                f"📂 *Кодовая база:* {base_name}\n"
                f"📂 *Файлов:* 0\n\n"
            )
            if readonly:
                text += "База пока пуста\\.\nВладелец еще не загрузил файлы\\."
            else:
                text += "База пока пуста\\. Отправьте файлы для загрузки\\."
            
            if edit:
                try:
                    await message.edit_text(text, parse_mode="MarkdownV2")
                except Exception:
                    await message.answer(text, parse_mode="MarkdownV2")
            else:
                await message.reply(text, parse_mode="MarkdownV2")
            return
    
        cur_page = max(1, min(files_data['page'], files_data['total_pages']))
        total_pages = files_data['total_pages']
    
        base_name = escape_markdown_v2(config['name'])
        total_files = escape_markdown_v2(str(files_data['total']))
        size_formatted = escape_markdown_v2(self.file_manager.format_size(total_size))
        cur_page_escaped = escape_markdown_v2(str(cur_page))
        total_pages_escaped = escape_markdown_v2(str(total_pages))
    
        text = (
            f"📂 *Кодовая база:* {base_name}\n"
            f"📂 *Файлов:* {total_files} \\| "
            f"💾 *Размер:* {size_formatted}\n"
            f"📄 *Страница* {cur_page_escaped}/{total_pages_escaped}\n\n"
        )
    
        # Добавляем предупреждение для readonly режима
        if readonly:
            text += "⚠️ *Режим просмотра* \\(чужая публичная база\\)\n\n"
    
        # Список файлов
        for i, file in enumerate(files_data['files'], files_data['start_idx']):
            icon = "📝" if file['is_text'] else "📦"
        
            # Экранируем имя файла для MarkdownV2
            name = file['name']
            # В моноширинном тексте нужно экранировать только обратные кавычки
            safe_name = name.replace("`", "\\`")
            name_disp = f"`{safe_name}`"
        
            size_str = escape_markdown_v2(self.file_manager.format_size(file['size']))
        
            modified_raw = file.get("modified") or ""
            try:
                dt = datetime.fromisoformat(modified_raw)
                date_str = dt.strftime("%d.%m.%y %H:%M")
            except Exception:
                date_str = "??.??.?? --:--"
            date_str_escaped = escape_markdown_v2(date_str)
        
            idx_escaped = escape_markdown_v2(str(i))
            text += f"{idx_escaped}\\. {icon} {name_disp} {size_str} {date_str_escaped}\n"
    
        # Навигация
        text += "\n📌 *Команды:*\n"
        if readonly:
            text += "/search \\- поиск файлов\n"
            text += "_Удаление и скачивание недоступны_"
        else:
            text += "/search \\- поиск файлов\n"
            text += "/download \\- скачать файлы\n"
            text += "/delete \\- удалить файлы"
    
        # Кнопки пагинации
        keyboard = self._build_pagination_keyboard(cur_page, total_pages)
    
        if edit:
            try:
                await message.edit_text(text, reply_markup=keyboard, parse_mode="MarkdownV2")
            except Exception:
                await message.answer(text, reply_markup=keyboard, parse_mode="MarkdownV2")
        else:
            await message.reply(text, reply_markup=keyboard, parse_mode="MarkdownV2")

    def _build_pagination_keyboard(self, cur_page: int, total_pages: int) -> InlineKeyboardMarkup:
        """Создает клавиатуру пагинации"""
        first_page = 1
        prev_page = max(first_page, cur_page - 1)
        next_page = min(total_pages, cur_page + 1)
        last_page = total_pages
        
        kb_rows = []
        row = []
        
        if cur_page > first_page:
            row.append(InlineKeyboardButton(text="⏮ 1", callback_data=f"files_page:{first_page}"))
            row.append(InlineKeyboardButton(text="◀️", callback_data=f"files_page:{prev_page}"))
        else:
            row.append(InlineKeyboardButton(text="⏮ 1", callback_data="files_page:noop"))
            row.append(InlineKeyboardButton(text="◀️", callback_data="files_page:noop"))
        
        if cur_page < last_page:
            row.append(InlineKeyboardButton(text="▶️", callback_data=f"files_page:{next_page}"))
            row.append(InlineKeyboardButton(text=f"{last_page} ⏭", callback_data=f"files_page:{last_page}"))
        else:
            row.append(InlineKeyboardButton(text="▶️", callback_data="files_page:noop"))
            row.append(InlineKeyboardButton(text=f"{last_page} ⏭", callback_data="files_page:noop"))
        
        kb_rows.append(row)
        return InlineKeyboardMarkup(inline_keyboard=kb_rows)