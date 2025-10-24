# code/handlers/file_operations/processors/image.py
"""
Процессор для обработки изображений
"""
import os
import secrets
import logging
from datetime import datetime
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from .base_processor import BaseProcessor

logger = logging.getLogger(__name__)


class ImageProcessor(BaseProcessor):
    """Обработчик изображений"""
    
    async def handle_photo(self, message: types.Message, state: FSMContext):
        """Обработка загруженных фотографий"""
        user_id = str(message.from_user.id)
        
        # Проверяем доступ
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
        
        # Проверяем наличие активной кодовой базы
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases.get("active")
        
        if not codebase_id:
            await message.reply(
                "❌ Нет активной кодовой базы.\n"
                "Создайте или выберите кодовую базу для загрузки файлов.\n"
                "/create_codebase - создать новую\n"
                "/codebases - список баз"
            )
            return
        
        # Получаем самое большое качество фото
        photo = message.photo[-1]
        
        # Генерируем имя файла на основе времени
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp}.jpg"
        
        # Проверяем подпись к фото
        caption = message.caption or ""
        
        processing_msg = await message.reply(f"⏳ Обрабатываю изображение...")
        
        try:
            # Загружаем файл
            tg_file = await self.bot.get_file(photo.file_id)
            stream = await self.bot.download_file(tg_file.file_path)
            file_bytes = stream.getvalue() if hasattr(stream, "getvalue") else stream
            
            # Если в подписи есть ключевые слова, сразу распознаем
            auto_recognize = any(word in caption.lower() for word in [
                "распознать", "распознай", "текст", "ocr", "recognize", "text"
            ])
            
            if auto_recognize:
                await self._process_image_with_ocr(
                    message, processing_msg, filename, file_bytes, codebase_id
                )
            else:
                await self._process_image_with_options(
                    message, processing_msg, filename, file_bytes, photo, user_id
                )
                
        except Exception as e:
            logger.error(f"Ошибка обработки фото: {e}", exc_info=True)
            await processing_msg.edit_text(f"❌ Ошибка обработки изображения: {str(e)}")

    async def process_image_file(self, message, processing_msg, orig_name, file_bytes, 
                                document, user_id, existing_token):
        """Обработка файлов изображений"""
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
        
        if hasattr(self.file_manager, 'ai_interface') and self.file_manager.ai_interface:
            # Если есть AI, предлагаем варианты
            if user_id not in self.handler.pending_files:
                self.handler.pending_files[user_id] = []
            
            token = existing_token or secrets.token_urlsafe(8)
            self.handler.pending_files[user_id].append({
                "kind": "image_convert",
                "token": token,
                "file_name": orig_name,
                "file_size": document.file_size,
                "file_data": file_bytes,
                "codebase_id": codebase_id
            })
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Распознать текст через AI", callback_data=f"conv:{token}:ai_ocr")],
                [InlineKeyboardButton(text="💾 Сохранить как изображение", callback_data=f"save_as:{token}:original")]
            ])
            
            ai_provider = self.get_ai_provider_name()
            
            await processing_msg.edit_text(
                f"🖼️ Обнаружено изображение: {orig_name}\n"
                f"📏 Размер: {self.file_manager.format_size(document.file_size)}\n"
                f"🤖 Доступно распознавание через {ai_provider}\n\n"
                "Выберите действие:",
                reply_markup=keyboard
            )
        else:
            # Если нет AI, сохраняем изображение как есть
            success, msg, _ = await self.file_manager.save_file(
                user_id, codebase_id, orig_name, file_bytes,
                encoding=None, skip_conversion=True
            )
            
            if success:
                config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
                await processing_msg.edit_text(
                    f"✅ Изображение сохранено!\n"
                    f"📚 Кодовая база: {config['name']}\n"
                    f"📊 {msg}"
                )
            else:
                await processing_msg.edit_text(f"❌ Ошибка: {msg}")

    async def _process_image_with_ocr(self, message, processing_msg, filename, 
                                     file_bytes, codebase_id):
        """Обработка изображения с автоматическим OCR"""
        await processing_msg.edit_text(
            f"⏳ Распознаю текст через AI...\n"
            f"⚠️ Это может занять 10-30 секунд"
        )
        
        user_id = str(message.from_user.id)
        
        # Проверяем, что codebase_id не None
        if not codebase_id:
            user_codebases = await self.codebase_manager.get_user_codebases(user_id)
            codebase_id = user_codebases["active"]
        
        # Конвертируем изображение в Markdown через OCR
        success, new_name, md_content = await self.file_manager.markdown_converter.convert_to_markdown(
            user_id, file_bytes, filename
        )
        
        if success and md_content:
            try:
                # Отправляем распознанный текст пользователю
                await message.reply_document(
                    types.BufferedInputFile(
                        md_content.encode('utf-8') if isinstance(md_content, str) else md_content,
                        new_name
                    ),
                    caption=f"✅ Текст распознан!\n📎 {new_name}"
                )
                
                config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
                await processing_msg.edit_text(
                    f"✅ Изображение успешно распознано!\n"
                    f"🖼️ Исходный файл: {filename}\n"
                    f"📝 Результат: {new_name}\n"
                    f"📚 Кодовая база: {config['name'] if config else 'Неизвестная'}\n\n"
                    f"Распознанный текст отправлен вам"
                )

                # Сохраняем для макро-команд
                if hasattr(self.handler.handler, 'agent_handler') and self.handler.handler.agent_handler:
                    content_str = md_content if isinstance(md_content, str) else md_content.decode('utf-8')
                    self.handler.handler.agent_handler.save_md_file_for_macros(
                        user_id, new_name, content_str, filename
                    )
                
                # Предлагаем сохранить распознанный текст в базу
                if codebase_id and user_id:
                    await self.offer_save_converted(
                        message,
                        new_name,
                        md_content.encode('utf-8') if isinstance(md_content, str) else md_content,
                        user_id,
                        codebase_id
                    )
                else:
                    logger.error(f"Не удалось предложить сохранение: codebase_id={codebase_id}, user_id={user_id}")
                
            except Exception as e:
                logger.error(f"Не удалось отправить распознанный файл: {e}", exc_info=True)
                await processing_msg.edit_text(
                    f"❌ Ошибка отправки файла: {str(e)}\n"
                    f"Текст был успешно распознан, но не удалось отправить результат"
                )
        else:
            await processing_msg.edit_text(
                f"❌ Не удалось распознать текст на изображении\n"
                f"Файл: {filename}\n\n"
                f"Изображение может не содержать текста или быть нечитаемым"
            )

    async def _process_image_with_options(self, message, processing_msg, filename, 
                                         file_bytes, photo, user_id):
        """Обработка изображения с предложением вариантов"""
        # Получаем codebase_id
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases.get("active")
        
        if not codebase_id:
            await processing_msg.edit_text("❌ Нет активной кодовой базы")
            return
        
        if hasattr(self.file_manager, 'ai_interface') and self.file_manager.ai_interface:
            if user_id not in self.handler.pending_files:
                self.handler.pending_files[user_id] = []
            
            token = secrets.token_urlsafe(8)
            self.handler.pending_files[user_id].append({
                "kind": "image_convert",
                "token": token,
                "file_name": filename,
                "file_size": photo.file_size or len(file_bytes),
                "file_data": file_bytes,
                "codebase_id": codebase_id
            })
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Распознать текст через AI", callback_data=f"conv:{token}:ai_ocr")],
                [InlineKeyboardButton(text="💾 Сохранить как изображение", callback_data=f"save_as:{token}:original")]
            ])
            
            ai_provider = self.get_ai_provider_name()
            size_mb = (photo.file_size or len(file_bytes)) / 1024 / 1024
            
            await processing_msg.edit_text(
                f"🖼️ Получено изображение\n"
                f"📏 Размер: {photo.width}x{photo.height}\n"
                f"💾 Объем: {size_mb:.2f} MB\n"
                f"🤖 Доступно распознавание через {ai_provider}\n\n"
                "Выберите действие:\n"
                "💡 Подсказка: добавьте подпись со словом 'распознать' для автоматической обработки",
                reply_markup=keyboard
            )
        else:
            # Если нет AI, просто сохраняем
            await self._save_image_without_ocr(message, processing_msg, filename, file_bytes, user_id)

    async def _save_image_without_ocr(self, message, processing_msg, filename, file_bytes, user_id):
        """Сохранение изображения без OCR"""
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
        
        success, msg, _ = await self.file_manager.save_file(
            user_id, codebase_id, filename, file_bytes, encoding=None, skip_conversion=True
        )
        
        if success:
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            await processing_msg.edit_text(
                f"✅ Изображение сохранено!\n"
                f"📚 Кодовая база: {config['name']}\n"
                f"📊 {msg}"
            )
        else:
            await processing_msg.edit_text(f"❌ Ошибка: {msg}")