# code/handlers/file_operations/callbacks.py
"""
Обработчик callback запросов для файловых операций
"""
import logging
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import asyncio
import os
from agents.rag_singleton import get_rag_manager

logger = logging.getLogger(__name__)

class CallbackProcessor:
    """Обработчик callback запросов"""
    
    def __init__(self, parent_handler):
        self.handler = parent_handler
        self.bot = parent_handler.bot
        self.user_manager = parent_handler.user_manager
        self.codebase_manager = parent_handler.codebase_manager
        self.file_manager = parent_handler.file_manager
        self.rag_manager = get_rag_manager()

    async def _update_rag_index_if_needed(self, user_id: str, codebase_id: str, filename: str):
        """Обновление RAG индекса если файл текстовый"""
        try:
            # Проверяем, является ли файл текстовым
            if not self.rag_manager._is_text_file(filename):
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
        
            if success:
                logger.info(f"RAG индекс обновлен после сохранения {filename}: {msg}")
            else:
                logger.warning(f"Не удалось обновить RAG индекс: {msg}")
            
        except Exception as e:
            logger.error(f"Ошибка обновления RAG индекса: {e}")

    async def handle_file_replacement(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка callback замены файла"""
        token = callback.data.split(":")[1]
        replace = callback.data.startswith("replace_file:")
        
        await callback.answer()
        
        user_id = str(callback.from_user.id)
        entry = next((f for f in self.handler.pending_files.get(user_id, []) 
                     if f.get("token") == token), None)
        
        if not entry:
            await callback.message.edit_text("❌ Файл не найден в очереди обработки")
            return
        
        if not replace:
            try:
                self.handler.pending_files[user_id].remove(entry)
            except ValueError:
                pass
            await callback.message.edit_text("⭕️ Файл пропущен.")
            return
        
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
        
        success, msg, _ = await self.file_manager.save_file(
            user_id, codebase_id, entry["file_name"], entry["file_data"], 
            entry.get("selected_encoding")
        )
        
        if success:
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            enc_info = f"📤 Кодировка: {entry.get('selected_encoding')} → UTF-8\n" if entry.get("selected_encoding") else ""
            await callback.message.edit_text(
                f"✅ Файл '{entry['file_name']}' заменён!\n"
                f"📂 Кодовая база: {config['name']}\n"
                f"{enc_info}"
                f"📊 {msg}"
            )

            asyncio.create_task(self._update_rag_index_if_needed(user_id, codebase_id, entry['file_name']))

            try:
                self.handler.pending_files[user_id].remove(entry)
            except ValueError:
                pass
        else:
            await callback.message.edit_text(f"❌ Ошибка: {msg}")

    async def handle_encoding(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка выбора кодировки"""
        await callback.answer()
        
        try:
            _, token, encoding = callback.data.split(":", 2)
        except ValueError:
            await callback.answer("Некорректные данные кнопки", show_alert=True)
            return
        
        user_id = str(callback.from_user.id)
        file_info = next((f for f in self.handler.pending_files.get(user_id, []) 
                         if f.get("token") == token and f.get("kind") == "encoding_prompt"), None)
        
        if not file_info:
            await callback.message.edit_text("❌ Файл не найден в очереди обработки")
            return
        
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
        
        exists = await self.file_manager.file_exists(user_id, codebase_id, file_info["file_name"])
        
        if exists:
            # Файл существует - спрашиваем о замене
            file_info["kind"] = "replace_after_encoding"
            file_info["selected_encoding"] = encoding
            
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Заменить", callback_data=f"replace_file:{token}"),
                InlineKeyboardButton(text="❌ Пропустить", callback_data=f"skip_file:{token}")
            ]])
            
            await callback.message.edit_text(
                f"⚠️ Файл '{file_info['file_name']}' уже существует.\n"
                f"Выбранная кодировка: {encoding}\n"
                f"Заменить существующий файл?",
                reply_markup=kb
            )
            return
        
        # Файл НЕ существует - спрашиваем о сохранении нового файла
        file_info["kind"] = "save_new_after_encoding"
        file_info["selected_encoding"] = encoding
        file_info["codebase_id"] = codebase_id
        
        # Получаем информацию о кодовой базе
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        # Форматируем размер файла
        file_size = file_info.get("file_size", 0)
        if file_size < 1024:
            size_str = f"{file_size} байт"
        elif file_size < 1024 * 1024:
            size_str = f"{file_size / 1024:.1f} КБ"
        else:
            size_str = f"{file_size / (1024 * 1024):.1f} МБ"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Сохранить", callback_data=f"save_new_after_enc:{token}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_new_after_enc:{token}")
        ]])
        
        await callback.message.edit_text(
            f"📁 Новый файл: {file_info['file_name']}\n"
            f"📊 Размер: {size_str}\n"
            f"📤 Кодировка: {encoding} → UTF-8\n"
            f"📚 Кодовая база: {config['name']}\n\n"
            f"Сохранить файл?",
            reply_markup=kb
        )


    async def handle_save_new_after_encoding(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка подтверждения сохранения нового файла после выбора кодировки"""
        await callback.answer()
        
        user_id = str(callback.from_user.id)
        token = callback.data.split(":", 1)[1]
        
        # Ищем файл в pending_files
        file_info = next((f for f in self.handler.pending_files.get(user_id, [])
                         if f.get("token") == token and f.get("kind") == "save_new_after_encoding"), None)
        
        if not file_info:
            await callback.message.edit_text("❌ Данные файла не найдены")
            return
        
        # Сохраняем файл с выбранной кодировкой
        codebase_id = file_info["codebase_id"]
        success, msg, _ = await self.file_manager.save_file(
            user_id, codebase_id, file_info["file_name"], file_info["file_data"], 
            file_info.get("selected_encoding")
        )
        
        if success:
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            await callback.message.edit_text(
                f"✅ Файл '{file_info['file_name']}' успешно сохранен!\n"
                f"📚 Кодовая база: {config['name']}\n"
                f"📤 Кодировка: {file_info.get('selected_encoding')} → UTF-8\n"
                f"📊 {msg}"
            )
            
            # Обновляем RAG индекс если файл текстовый
            asyncio.create_task(self._update_rag_index_if_needed(
                user_id, codebase_id, file_info['file_name']
            ))
            
            await callback.answer("✅ Файл сохранен")
            
            # Удаляем из pending_files
            try:
                self.handler.pending_files[user_id].remove(file_info)
            except ValueError:
                pass
        else:
            await callback.message.edit_text(f"❌ Ошибка: {msg}")
            await callback.answer("❌ Ошибка сохранения", show_alert=True)

    async def handle_cancel_new_after_encoding(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка отмены сохранения нового файла после выбора кодировки"""
        await callback.answer()
        
        user_id = str(callback.from_user.id)
        token = callback.data.split(":", 1)[1]
        
        # Ищем и удаляем файл из pending_files
        if user_id in self.handler.pending_files:
            for pending in self.handler.pending_files[user_id]:
                if pending.get("token") == token and pending.get("kind") == "save_new_after_encoding":
                    self.handler.pending_files[user_id].remove(pending)
                    break
        
        await callback.message.edit_text(
            "❌ Загрузка файла отменена.\n"
            "Файл не был сохранен в кодовую базу."
        )
        await callback.answer("Загрузка отменена")

    async def handle_conversion(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка выбора формата конвертации"""
        await callback.answer()
        
        try:
            _, token, target = callback.data.split(":", 2)
        except ValueError:
            await callback.answer("Некорректные данные кнопки", show_alert=True)
            return
        
        user_id = str(callback.from_user.id)
        entry = None
        
        for f in self.handler.pending_files.get(user_id, []):
            if f.get("token") == token:
                entry = f
                break
        
        if not entry:
            await callback.message.edit_text("❌ Файл не найден в очереди обработки")
            return
        
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
        
        file_bytes = entry["file_data"]
        orig_name = entry["file_name"]
        
        if target == "ai_ocr" and entry.get("kind") == "image_convert":
            await callback.message.edit_text(
                f"⏳ Распознаю текст через AI...\n"
                f"🖼️ Файл: {orig_name}\n"
                f"⚠️ Это может занять 10-30 секунд"
            )
            
            # Конвертируем изображение в Markdown через OCR
            success, new_name, md_content = await self.file_manager.markdown_converter.convert_to_markdown(
                user_id, file_bytes, orig_name
            )
            
            if success and md_content:
                try:

                # Сохраняем для макро-команд
                    if hasattr(self.handler, 'agent_handler') and self.handler.agent_handler:
                        self.handler.agent_handler.save_md_file_for_macros(
                            user_id, new_name, md_content, new_name
                        )

                    # Отправляем распознанный текст пользователю
                    await callback.message.reply_document(
                        types.BufferedInputFile(
                            md_content.encode('utf-8') if isinstance(md_content, str) else md_content,
                            new_name
                        ),
                        caption=f"✅ Текст распознан!\n📎 {new_name}"
                    )
                    
                    await callback.message.edit_text(
                        f"✅ Изображение успешно распознано!\n"
                        f"🖼️ Исходный файл: {orig_name}\n"
                        f"📝 Результат: {new_name}\n\n"
                        f"Распознанный текст отправлен вам"
                    )
                    
                    # Предлагаем сохранить распознанный текст
                    from .processors.base_processor import BaseProcessor
                    base_processor = BaseProcessor(self.handler)
                    
                    codebase_id = entry.get("codebase_id")
                    if not codebase_id:
                        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
                        codebase_id = user_codebases.get("active")
                    
                    if codebase_id:
                        await base_processor.offer_save_converted(
                            callback.message,
                            new_name,
                            md_content.encode('utf-8') if isinstance(md_content, str) else md_content,
                            user_id,
                            codebase_id
                        )
                    
                except Exception as e:
                    logger.error(f"Не удалось отправить распознанный файл: {e}")
                    await callback.message.edit_text(f"❌ Ошибка: {str(e)}")
            else:
                await callback.message.edit_text(
                    f"❌ Не удалось распознать текст на изображении\n"
                    f"Файл: {orig_name}\n\n"
                    f"Изображение может не содержать текста или быть нечитаемым"
                )
        
        elif target == "md" and entry.get("kind") == "table_convert":
            await callback.message.edit_text(f"⏳ Конвертирую в Markdown...")
            
            success, msg, converted_filename = await self.file_manager.save_file(
                user_id, codebase_id, orig_name, file_bytes
            )
            
            if success:
                config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
                
                if converted_filename:
                    asyncio.create_task(self._update_rag_index_if_needed(user_id, codebase_id, converted_filename))
    
                    md_content = await self.file_manager.get_file(user_id, codebase_id, converted_filename)
                    if md_content:
                        try:
                            await callback.message.reply_document(
                                types.BufferedInputFile(md_content, converted_filename),
                                caption=f"✅ Таблица конвертирована в Markdown!\n📎 {converted_filename}"
                            )
                            
                            from .processors.base_processor import BaseProcessor
                            base_processor = BaseProcessor(self.handler)
                            await base_processor.offer_save_converted(
                                callback.message, converted_filename, md_content, user_id, codebase_id
                            )
                            
                        except Exception as e:
                            logger.error(f"Не удалось отправить конвертированный файл: {e}")
                
                await callback.message.edit_text(
                    f"✅ Файл конвертирован!\n"
                    f"📂 Кодовая база: {config['name']}\n"
                    f"📊 {msg}"
                )
            else:
                await callback.message.edit_text(f"❌ Ошибка: {msg}")
        
        try:
            self.handler.pending_files[user_id].remove(entry)
        except ValueError:
            pass

    async def handle_save_as(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка сохранения файла как есть"""
        await callback.answer()
        
        try:
            _, token, save_type = callback.data.split(":", 2)
        except ValueError:
            await callback.answer("Некорректные данные кнопки", show_alert=True)
            return
        
        user_id = str(callback.from_user.id)
        entry = None
        
        for f in self.handler.pending_files.get(user_id, []):
            if f.get("token") == token:
                entry = f
                break
        
        if not entry:
            await callback.message.edit_text("❌ Файл не найден в очереди обработки")
            return
        
        if save_type == "cancel":
            await callback.message.edit_text("⭕ Операция отменена")
            try:
                self.handler.pending_files[user_id].remove(entry)
            except ValueError:
                pass
            return
        
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
        
        success, msg, _ = await self.file_manager.save_file(
            user_id, codebase_id, entry["file_name"], entry["file_data"], 
            encoding=None, skip_conversion=True
        )
        
        if success:
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            await callback.message.edit_text(
                f"✅ Файл '{entry['file_name']}' сохранен как есть!\n"
                f"📂 Кодовая база: {config['name']}\n"
                f"📊 {msg}"
            )

            asyncio.create_task(self._update_rag_index_if_needed(user_id, codebase_id, entry['file_name']))
        else:
            await callback.message.edit_text(f"❌ Ошибка: {msg}")
        
        try:
            self.handler.pending_files[user_id].remove(entry)
        except ValueError:
            pass

    async def handle_save_converted(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка сохранения конвертированного файла"""
        await callback.answer()
        
        try:
            _, token, action = callback.data.split(":", 2)
        except ValueError:
            await callback.answer("Некорректные данные кнопки", show_alert=True)
            return
        
        user_id = str(callback.from_user.id)
        entry = None
        
        for f in self.handler.pending_files.get(user_id, []):
            if f.get("token") == token and f.get("kind") == "save_converted":
                entry = f
                break
        
        if not entry:
            await callback.message.edit_text("❌ Данные файла не найдены")
            return
        
        if action == "skip":
            await callback.message.edit_text("⭕ Файл не сохранен в базу")
            try:
                self.handler.pending_files[user_id].remove(entry)
            except ValueError:
                pass
            return
        
        codebase_id = entry["codebase_id"]
        filename = entry["file_name"]
        file_data = entry["file_data"]
        
        # Сохраняем файл
        success, msg, _ = await self.file_manager.save_file(
            user_id, codebase_id, filename, file_data,
            encoding="utf-8", skip_conversion=True
        )
        
        if success:
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            action_text = "перезаписан" if action == "replace" else "сохранен"
            await callback.message.edit_text(
                f"✅ Файл '{filename}' {action_text} в кодовой базе!\n"
                f"📚 База: {config['name']}\n"
                f"📊 {msg}"
            )

            asyncio.create_task(self._update_rag_index_if_needed(user_id, codebase_id, filename))
        else:
            await callback.message.edit_text(f"❌ Ошибка сохранения: {msg}")
        
        try:
            self.handler.pending_files[user_id].remove(entry)
        except ValueError:
            pass

    async def handle_audio_save(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка callback сохранения аудио"""
        await callback.answer()
        
        try:
            _, token, action = callback.data.split(":", 2)
        except ValueError:
            await callback.answer("Некорректные данные кнопки", show_alert=True)
            return
        
        user_id = str(callback.from_user.id)
        entry = None
        
        for f in self.handler.pending_files.get(user_id, []):
            if f.get("token") == token and f.get("kind") in ["audio_save", "voice_save"]:
                entry = f
                break
        
        if not entry:
            await callback.message.edit_text("❌ Данные файла не найдены")
            return
        
        if action == "skip":
            await callback.message.edit_text("⭕ Транскрипция не сохранена в базу")
            try:
                self.handler.pending_files[user_id].remove(entry)
            except ValueError:
                pass
            return
        
        codebase_id = entry["codebase_id"]
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        # Сохраняем транскрипцию
        text_filename = entry.get("text_filename")
        text_data = entry.get("text_data")
        
        if text_filename and text_data:
            success, msg, _ = await self.file_manager.save_file(
                user_id, codebase_id, text_filename, text_data,
                encoding="utf-8", skip_conversion=True
            )
            
            if success:
                await callback.message.edit_text(
                    f"✅ Транскрипция сохранена в базу {config['name']}\n"
                    f"📝 Файл: {text_filename}\n"
                    f"📊 {msg}"
                )

                asyncio.create_task(self._update_rag_index_if_needed(user_id, codebase_id, text_filename))
            else:
                await callback.message.edit_text(
                    f"❌ Не удалось сохранить транскрипцию\n"
                    f"Ошибка: {msg}"
                )
        else:
            await callback.message.edit_text("❌ Нет данных для сохранения")
        
        try:
            self.handler.pending_files[user_id].remove(entry)
        except ValueError:
            pass



    async def handle_save_new_file(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка подтверждения сохранения нового файла"""
        await callback.answer()
        
        user_id = str(callback.from_user.id)
        token = callback.data.split(":", 1)[1]
        
        # Ищем файл в pending_files
        if user_id not in self.handler.pending_files:
            await callback.answer("❌ Данные файла не найдены", show_alert=True)
            await callback.message.delete()
            return
        
        file_info = None
        for pending in self.handler.pending_files[user_id]:
            if pending.get("token") == token and pending.get("kind") == "save_new_file":
                file_info = pending
                break
        
        if not file_info:
            await callback.answer("❌ Данные файла не найдены", show_alert=True)
            await callback.message.delete()
            return
        
        # Удаляем из pending_files
        self.handler.pending_files[user_id].remove(file_info)
        
        # Сохраняем файл
        success, msg, _ = await self.file_manager.save_file(
            user_id, 
            file_info["codebase_id"], 
            file_info["file_name"], 
            file_info["file_data"],
            encoding=file_info.get("selected_encoding")
        )
        
        if success:
            config = await self.codebase_manager.get_codebase_config(user_id, file_info["codebase_id"])
            
            await callback.message.edit_text(
                f"✅ Файл '{file_info['file_name']}' успешно сохранен!\n"
                f"📚 Кодовая база: {config['name']}\n"
                f"📤 Кодировка: {file_info.get('selected_encoding', 'UTF-8')} → UTF-8\n"
                f"📊 {msg}"
            )
            
            # Обновляем RAG индекс если файл текстовый
            asyncio.create_task(self._update_rag_index_if_needed(
                user_id, file_info["codebase_id"], file_info['file_name']
            ))
            
            await callback.answer("✅ Файл сохранен")
        else:
            await callback.message.edit_text(f"❌ Ошибка при сохранении: {msg}")
            await callback.answer("❌ Ошибка сохранения", show_alert=True)

    async def handle_cancel_new_file(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка отмены сохранения нового файла"""
        await callback.answer()
        
        user_id = str(callback.from_user.id)
        token = callback.data.split(":", 1)[1]
        
        # Ищем и удаляем файл из pending_files
        if user_id in self.handler.pending_files:
            for pending in self.handler.pending_files[user_id]:
                if pending.get("token") == token and pending.get("kind") == "save_new_file":
                    self.handler.pending_files[user_id].remove(pending)
                    break
        
        await callback.message.edit_text(
            "❌ Загрузка файла отменена.\n"
            "Файл не был сохранен в кодовую базу."
        )
        await callback.answer("Загрузка отменена")