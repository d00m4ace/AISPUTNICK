# code/handlers/file_operations/processors/base_processor.py
"""
Базовый класс для всех процессоров файлов
"""
import secrets
import logging
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


class BaseProcessor:
    """Базовый процессор с общими методами"""
    
    def __init__(self, parent_handler):
        self.handler = parent_handler
        self.bot = parent_handler.bot
        self.user_manager = parent_handler.user_manager
        self.codebase_manager = parent_handler.codebase_manager
        self.file_manager = parent_handler.file_manager

    async def offer_save_converted(self, message, converted_filename, md_content, 
                                   user_id, codebase_id):
        """Предлагает сохранить конвертированный файл в кодовую базу"""
        # Проверяем, существует ли уже такой файл
        exists = await self.file_manager.file_exists(user_id, codebase_id, converted_filename)
        
        token = secrets.token_urlsafe(8)
        if user_id not in self.handler.pending_files:
            self.handler.pending_files[user_id] = []
        
        self.handler.pending_files[user_id].append({
            "kind": "save_converted",
            "token": token,
            "file_name": converted_filename,
            "file_data": md_content if isinstance(md_content, bytes) else md_content.encode('utf-8'),
            "codebase_id": codebase_id
        })
        
        if exists:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Перезаписать в базе", callback_data=f"save_converted:{token}:replace")],
                [InlineKeyboardButton(text="❌ Не сохранять", callback_data=f"save_converted:{token}:skip")]
            ])
            
            await message.reply(
                f"⚠️ Файл '{converted_filename}' уже существует в кодовой базе.\n"
                f"Хотите перезаписать его новой версией?",
                reply_markup=keyboard
            )
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💾 Сохранить в базе", callback_data=f"save_converted:{token}:save")],
                [InlineKeyboardButton(text="❌ Не сохранять", callback_data=f"save_converted:{token}:skip")]
            ])
            
            await message.reply(
                f"💡 Хотите сохранить '{converted_filename}' в кодовую базу?",
                reply_markup=keyboard
            )

    async def offer_save_original(self, message, orig_name, file_bytes, file_size,
                                  user_id, codebase_id, existing_token=None):
        """Предлагает сохранить оригинальный файл"""
        if user_id not in self.handler.pending_files:
            self.handler.pending_files[user_id] = []
        
        token = existing_token or secrets.token_urlsafe(8)
        self.handler.pending_files[user_id].append({
            "kind": "save_original",
            "token": token,
            "file_name": orig_name,
            "file_size": file_size,
            "file_data": file_bytes,
            "codebase_id": codebase_id
        })
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💾 Сохранить как есть", callback_data=f"save_as:{token}:original")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"save_as:{token}:cancel")]
        ])
        
        return keyboard, token

    def get_ai_provider_name(self):
        """Получение имени AI провайдера"""
        if hasattr(self.file_manager, 'ai_interface') and self.file_manager.ai_interface:
            if self.file_manager.ai_interface.has_api_key("openai"):
                return "GPT-4o"
            elif self.file_manager.ai_interface.has_api_key("anthropic"):
                return "Claude"
        return "AI"