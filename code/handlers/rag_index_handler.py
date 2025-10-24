# code/handlers/rag_index_handler.py
"""
Обработчик команд работы с RAG индексами
"""

import os
import logging
from aiogram import types
from utils.markdown_utils import escape_markdown_v2

logger = logging.getLogger(__name__)


class RagIndexHandler:
    """Обработчик команд для RAG индексации"""
    
    def __init__(self, bot, user_manager, codebase_manager, rag_manager):
        self.bot = bot
        self.user_manager = user_manager
        self.codebase_manager = codebase_manager
        self.rag_manager = rag_manager
    
    async def cmd_index_rag(self, message: types.Message):
        """Команда для индексации RAG текущей кодовой базы"""
        user_id = str(message.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return
        
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if not user_codebases["active"]:
            await message.reply(
                "❌ Нет активной кодовой базы\\.\n"
                "Выберите кодовую базу командой /switch",
                parse_mode="MarkdownV2"
            )
            return
        
        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
        
        # Проверяем, что это не чужая публичная база
        if cb_info.get("is_public_ref"):
            text = (
                "❌ *Вы не можете индексировать чужую публичную базу\\!*\n\n"
                "RAG индекс создается и обновляется только владельцем\\.\n"
                "Вы автоматически используете индекс владельца при поиске\\."
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        if not config:
            await message.reply("❌ Ошибка: конфигурация кодовой базы не найдена", parse_mode="MarkdownV2")
            return
        
        # Получаем путь к файлам
        codebase_dir = self.codebase_manager._get_codebase_dir(user_id, codebase_id)
        files_dir = os.path.join(codebase_dir, "files")
        
        # Проверяем статус индекса
        status = await self.rag_manager.check_index_status(user_id, codebase_id, files_dir)
        
        name_escaped = escape_markdown_v2(config['name'])
        
        # Формируем сообщение о статусе
        status_msg = await message.reply(
            f"🔍 RAG индексация для базы '{name_escaped}'\n\n"
            f"📊 Статус: {'Индекс существует' if status['exists'] else 'Индекс не существует'}\n"
            f"{'⚠️ Требуется обновление: ' + status['reason'] if status.get('needs_update') else '✅ Индекс актуален'}\n\n"
            "⏳ Начинаю индексацию\\.\\.\\.",
            parse_mode="MarkdownV2"
        )
        
        try:                        
            # Выполняем полную переиндексацию с параметрами
            success, msg = await self.rag_manager.reindex_full(
                user_id=user_id,
                codebase_id=codebase_id,
                files_dir=files_dir
            )
            
            if success:
                # Получаем информацию об индексе
                index_info = await self.rag_manager.get_index_info(user_id, codebase_id)
                
                await status_msg.edit_text(
                    f"✅ RAG индексация завершена\\!\n\n"
                    f"📚 Кодовая база: {name_escaped}\n"
                    f"📁 Файлов проиндексировано: {index_info.get('files_count', 0)}\n"
                    f"📄 Всего чанков: {index_info.get('total_chunks', 0)}\n"
                    f"📤 Уникальных слов: {index_info.get('total_unique_words', 0)}\n"
                    f"📊 Размер матрицы: {escape_markdown_v2(str(index_info.get('matrix_shape', [])))}\n\n"
                    f"💬 Теперь вы можете использовать /agents для поиска по коду",
                    parse_mode="MarkdownV2"
                )
            else:
                msg_escaped = escape_markdown_v2(msg)
                await status_msg.edit_text(
                    f"❌ Ошибка индексации:\n{msg_escaped}\n\n"
                    "Попробуйте еще раз позже или обратитесь к администратору",
                    parse_mode="MarkdownV2"
                )
                
        except Exception as e:
            logger.error(f"Ошибка при индексации RAG: {e}", exc_info=True)
            error_escaped = escape_markdown_v2(str(e))
            await status_msg.edit_text(
                f"❌ Произошла ошибка при индексации:\n{error_escaped}",
                parse_mode="MarkdownV2"
            )
    
    async def cmd_update_rag(self, message: types.Message):
        """Команда для инкрементального обновления RAG индекса"""
        user_id = str(message.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return
        
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if not user_codebases["active"]:
            await message.reply(
                "❌ Нет активной кодовой базы\\.\n"
                "Выберите кодовую базу командой /switch",
                parse_mode="MarkdownV2"
            )
            return
        
        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
        
        # Проверяем, что это не чужая публичная база
        if cb_info.get("is_public_ref"):
            text = (
                "❌ *Вы не можете обновлять индекс чужой публичной базы\\!*\n\n"
                "RAG индекс обновляется только владельцем\\.\n"
                "Вы автоматически используете актуальный индекс владельца\\."
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        # Получаем путь к файлам
        codebase_dir = self.codebase_manager._get_codebase_dir(user_id, codebase_id)
        files_dir = os.path.join(codebase_dir, "files")
        
        status_msg = await message.reply("⏳ Обновляю RAG индекс\\.\\.\\.", parse_mode="MarkdownV2")
        
        try:
            # Инкрементальное обновление
            success, msg = await self.rag_manager.update_incremental(
                user_id=user_id,
                codebase_id=codebase_id,
                files_dir=files_dir
            )
            
            name_escaped = escape_markdown_v2(config['name'])
            msg_escaped = escape_markdown_v2(msg)
            
            if success:
                await status_msg.edit_text(
                    f"✅ RAG индекс обновлен\\!\n\n"
                    f"📚 База: {name_escaped}\n"
                    f"📝 Результат: {msg_escaped}",
                    parse_mode="MarkdownV2"
                )
            else:
                await status_msg.edit_text(
                    f"❌ Ошибка обновления: {msg_escaped}",
                    parse_mode="MarkdownV2"
                )
                
        except Exception as e:
            error_escaped = escape_markdown_v2(str(e))
            await status_msg.edit_text(
                f"❌ Ошибка: {error_escaped}",
                parse_mode="MarkdownV2"
            )