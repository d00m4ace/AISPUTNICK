# code/handlers/file_operations/processors/text.py
"""
Процессор для обработки обычных текстовых файлов
"""
import os
import secrets
import logging
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from .base_processor import BaseProcessor

logger = logging.getLogger(__name__)


class TextFileProcessor(BaseProcessor):
    """Обработчик текстовых файлов"""
    
    async def process_regular_file(self, message, processing_msg, document, file_bytes, 
                                  user_id, codebase_id, existing_token):
        """Обработка обычных текстовых файлов"""
        is_text = self.file_manager.is_text_file(document.file_name)
        
        # Если файл не текстовый - не поддерживается
        if not is_text:
            ext = os.path.splitext(document.file_name.lower())[1]
            await processing_msg.edit_text(
                f"❌ Тип файла '{ext}' не поддерживается\n"
                f"Файл: {document.file_name}\n\n"
                f"Поддерживаются:\n"
                f"• Текстовые файлы (.txt, .md, .c, .py, .js, .json, .xml и др.)\n"
                f"• Документы (.docx, .rtf, .odt)\n"
                f"• Таблицы (.xlsx, .xls, .csv)\n"
                f"• Презентации (.pptx, .ppt)\n"
                f"• PDF файлы\n"
                f"• HTML файлы\n"
                f"• Изображения (.jpg, .png, .gif и др.)\n"
                f"• Аудио файлы (.mp3, .wav, .ogg, .m4a и др.)"
            )
            return
       
        # Далее обработка только текстовых файлов
        encoding, confidence = await self.file_manager.encoding_converter.detect_encoding(file_bytes)
        selected_encoding = encoding

        # Сохраняем текстовый файл для макро-команд
        if hasattr(self.handler, 'agent_handler') and self.handler.agent_handler:
            try:
                # Декодируем контент с правильной кодировкой
                if selected_encoding and selected_encoding != 'utf-8':
                    try:
                        text_content = file_bytes.decode(selected_encoding)
                    except:
                        text_content = file_bytes.decode('utf-8', errors='ignore')
                else:
                    text_content = file_bytes.decode('utf-8', errors='ignore')
        
                # Сохраняем для макро-команд
                self.handler.agent_handler.save_md_file_for_macros(
                    user_id, 
                    document.file_name,
                    text_content,
                    document.file_name
                )
                logger.info(f"Текстовый файл {document.file_name} сохранен для макро-команд")
            except Exception as e:
                logger.warning(f"Не удалось сохранить файл для макро-команд: {e}")
        
        if self.file_manager.encoding_converter.needs_conversion(encoding, confidence):
            # Используем self.handler.pending_files вместо self.pending_files
            if user_id not in self.handler.pending_files:
                self.handler.pending_files[user_id] = []
            
            token = existing_token or secrets.token_urlsafe(8)
            self.handler.pending_files[user_id].append({
                "kind": "encoding_prompt",
                "token": token,
                "file_name": document.file_name,
                "file_size": document.file_size,
                "file_data": file_bytes,
            })
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"✅ {encoding} (авто)", callback_data=f"enc:{token}:{encoding}")],
                [InlineKeyboardButton(text="CP1251 (Windows)", callback_data=f"enc:{token}:cp1251")],
                [InlineKeyboardButton(text="CP866 (DOS)", callback_data=f"enc:{token}:cp866")],
                [InlineKeyboardButton(text="KOI8-R", callback_data=f"enc:{token}:koi8-r")],
                [InlineKeyboardButton(text="UTF-8", callback_data=f"enc:{token}:utf-8")],
            ])
            
            await processing_msg.edit_text(
                f"📤 Обнаружена кодировка: {encoding} (уверенность: {confidence:.0%})\n"
                f"Файл: {document.file_name}\n\n"
                "Выберите кодировку для правильного преобразования:",
                reply_markup=keyboard
            )
            return
        
        # Проверяем существование файла
        exists = await self.file_manager.file_exists(user_id, codebase_id, document.file_name)
        if exists:
            if user_id not in self.handler.pending_files:
                self.handler.pending_files[user_id] = []
            
            token = existing_token or secrets.token_urlsafe(8)
            self.handler.pending_files[user_id].append({
                "kind": "replace_after_encoding",
                "token": token,
                "file_name": document.file_name,
                "file_size": document.file_size,
                "file_data": file_bytes,
                "selected_encoding": selected_encoding,
            })
            
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Заменить", callback_data=f"replace_file:{token}"),
                InlineKeyboardButton(text="❌ Пропустить", callback_data=f"skip_file:{token}")
            ]])
            
            await processing_msg.edit_text(
                f"⚠️ Файл '{document.file_name}' уже существует.\n"
                f"Выбранная кодировка: {selected_encoding or '—'}\n"
                f"Заменить существующий файл?",
                reply_markup=kb
            )
            return
        
        # Файл не существует - спрашиваем о сохранении нового файла
        if user_id not in self.handler.pending_files:
            self.handler.pending_files[user_id] = []
        
        token = existing_token or secrets.token_urlsafe(8)
        self.handler.pending_files[user_id].append({
            "kind": "save_new_file",
            "token": token,
            "file_name": document.file_name,
            "file_size": document.file_size,
            "file_data": file_bytes,
            "selected_encoding": selected_encoding,
            "codebase_id": codebase_id,
        })
        
        # Получаем информацию о кодовой базе для отображения
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        # Форматируем размер файла
        if document.file_size < 1024:
            size_str = f"{document.file_size} байт"
        elif document.file_size < 1024 * 1024:
            size_str = f"{document.file_size / 1024:.1f} КБ"
        else:
            size_str = f"{document.file_size / (1024 * 1024):.1f} МБ"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Сохранить", callback_data=f"save_new_file:{token}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_new_file:{token}")
        ]])
        
        await processing_msg.edit_text(
            f"📁 Новый файл: {document.file_name}\n"
            f"📊 Размер: {size_str}\n"
            f"📤 Кодировка: {selected_encoding or 'UTF-8'}\n"
            f"📚 Кодовая база: {config['name']}\n\n"
            f"Сохранить файл?",
            reply_markup=kb
        )