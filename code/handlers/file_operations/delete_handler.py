# code/handlers/file_operations/delete_handler.py
"""
Модуль обработки удаления файлов
"""
import os
import asyncio
import logging
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from agents.rag_singleton import get_rag_manager

from .states import FileStates
from .base import BaseFileHandler

from utils.markdown_utils import escape_markdown_v2

logger = logging.getLogger(__name__)

class FileDeleteHandler(BaseFileHandler):
    """Обработчик удаления файлов"""

    def __init__(self, bot, user_manager, codebase_manager, file_manager):
        super().__init__(bot, user_manager, codebase_manager, file_manager)
        self.rag_manager = get_rag_manager()
    
    async def cmd_delete_files(self, message: types.Message, state: FSMContext):
        """Начинает процесс удаления файлов"""
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
    
        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
    
        # Проверяем права на удаление
        if cb_info.get("is_public_ref"):
            text = (
                "❌ *Вы не можете удалять файлы в чужой публичной базе\\!*\n\n"
                "Только владелец базы может:\n"
                "• Добавлять файлы\n"
                "• Удалять файлы\n"
                "• Изменять файлы\n\n"
                "Вы можете только просматривать файлы и использовать их через агентов\\."
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        text = (
            "🗑️ Введите имена файлов для удаления через запятую\\.\n"
            "Пример: file1\\.txt, script\\.py, data\\.json\n\n"
            "Или введите номера файлов из списка /files\n"
            "Пример: 1, 3, 5\\-8\n\n"
            "Или отправьте '\\*' чтобы выбрать все файлы\n\n"
            "/cancel\\_file\\_job \\- отмена"
        )
        await message.reply(text, parse_mode="MarkdownV2")
        await state.set_state(FileStates.selecting_files_to_delete)
   
    async def process_files_to_delete(self, message: types.Message, state: FSMContext):
        """Обработка выбора файлов для удаления"""
        user_id = str(message.from_user.id)
        text = message.text.strip()
    
        if text.lower() == "/cancel_file_job":
            await state.clear()
            await message.reply("❌ Удаление отменено\\.", parse_mode="MarkdownV2")
            return
    
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
    
        # Дополнительная проверка на случай если состояние изменилось
        if cb_info.get("is_public_ref"):
            await state.clear()
            text_reply = (
                "❌ Операция отменена\\.\n"
                "Вы не можете удалять файлы в чужой публичной базе\\."
            )
            await message.reply(text_reply, parse_mode="MarkdownV2")
            return
    
        all_files_data = await self.file_manager.list_files(user_id, codebase_id, 1, per_page=10000)
        all_files = all_files_data['files']
    
        files_to_delete = []
        text_norm = text.replace(" ", "")
    
        if text_norm == "*":
            # Выбор всех файлов
            files_to_delete = [f['name'] for f in all_files]
        else:
            # Проверяем, содержит ли текст только цифры, запятые и дефисы (номера)
            if any(ch.isdigit() for ch in text_norm):
                parts = text_norm.split(",")
                indices = set()
                for part in parts:
                    if "-" in part:
                        try:
                            start, end = map(int, part.split("-"))
                            if start > end:
                                start, end = end, start
                            indices.update(range(start, end + 1))
                        except ValueError:
                            continue
                    else:
                        try:
                            indices.add(int(part))
                        except ValueError:
                            continue
            
                for idx in sorted(indices):
                    if 1 <= idx <= len(all_files):
                        files_to_delete.append(all_files[idx - 1]['name'])
            else:
                # Обработка имен файлов
                files_to_delete = [f.strip() for f in text.split(",") if f.strip()]
    
        if not files_to_delete:
            await message.reply("❌ Файлы не выбраны\\. Попробуйте еще раз:", parse_mode="MarkdownV2")
            return
    
        await state.update_data(files_to_delete=files_to_delete, codebase_id=codebase_id)
    
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да, удалить", callback_data="confirm_delete:yes"),
            InlineKeyboardButton(text="❌ Нет, отмена", callback_data="confirm_delete:no"),
        ]])
    
        # Формируем список файлов с экранированием
        files_list = "\n".join(f"• {escape_markdown_v2(f)}" for f in files_to_delete[:10])
        if len(files_to_delete) > 10:
            files_list += f"\n\\.\\.\\. и еще {escape_markdown_v2(str(len(files_to_delete) - 10))}"
    
        text_reply = (
            f"⚠️ Будут удалены файлы \\({escape_markdown_v2(str(len(files_to_delete)))}\\):\n"
            f"{files_list}\n\n"
            f"Подтвердите удаление кнопкой ниже:"
        )
    
        await message.reply(text_reply, reply_markup=kb, parse_mode="MarkdownV2")
   
    async def handle_confirm_callback(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка подтверждения удаления"""
        choice = callback.data.split(":", 1)[1]
        user_id = str(callback.from_user.id)
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
    
        # Финальная проверка прав перед удалением
        if cb_info.get("is_public_ref"):
            text = (
                "❌ Операция запрещена\\.\n"
                "Вы не являетесь владельцем этой публичной базы\\."
            )
            await callback.message.edit_text(text, parse_mode="MarkdownV2")
            await state.clear()
            await callback.answer("Недостаточно прав", show_alert=True)
            return
    
        if choice == "yes":
            data_state = await state.get_data()
            files_to_delete = data_state.get("files_to_delete", [])
            if not files_to_delete:
                await callback.answer("Список файлов для удаления пуст", show_alert=True)
                return
        
            # Проверяем какие из удаляемых файлов текстовые
            text_files_to_delete = [f for f in files_to_delete if self.rag_manager._is_text_file(f)]     

            deleted, total = await self.file_manager.delete_files(
                user_id, codebase_id, files_to_delete
            )

            # Если были удалены текстовые файлы - обновляем индекс
            if text_files_to_delete and deleted > 0:
                asyncio.create_task(self._update_rag_after_delete(user_id, codebase_id, text_files_to_delete))        
        
            text = (
                f"✅ Удалено файлов: {escape_markdown_v2(str(deleted))}/{escape_markdown_v2(str(total))}\n\n"
                f"/files — список файлов"
            )
            await callback.message.edit_text(text, parse_mode="MarkdownV2")
            await state.clear()
        else:
            await callback.message.edit_text("⛔ Удаление отменено\\.", parse_mode="MarkdownV2")
            await state.clear()
    
        await callback.answer()

    async def _update_rag_after_delete(self, user_id: str, codebase_id: str, deleted_files: list):
        """Обновление RAG индекса после удаления файлов"""
        try:
            # Получаем путь к файлам
            codebase_dir = self.codebase_manager._get_codebase_dir(user_id, codebase_id)
            files_dir = os.path.join(codebase_dir, "files")
        
            # Инкрементальное обновление автоматически обработает удаленные файлы
            success, msg = await self.rag_manager.update_incremental(
                user_id=user_id,
                codebase_id=codebase_id,
                files_dir=files_dir
            )
        
            if success:
                logger.info(f"RAG индекс обновлен после удаления {len(deleted_files)} файлов: {msg}")
            else:
                logger.warning(f"Не удалось обновить RAG индекс после удаления: {msg}")
            
        except Exception as e:
            logger.error(f"Ошибка обновления RAG индекса после удаления: {e}")