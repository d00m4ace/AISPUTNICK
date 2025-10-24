# code/handlers/file_operations/processors/table.py
"""
Процессор для обработки табличных файлов (Excel, CSV)
"""
import os
import logging
from aiogram import types
from .base_processor import BaseProcessor

logger = logging.getLogger(__name__)

class TableProcessor(BaseProcessor):
    """Обработчик табличных файлов"""
    
    async def process_table_file(self, message, processing_msg, orig_name, file_bytes, 
                                document, ext, user_id, existing_token):
        """Обработка табличных файлов Excel/CSV"""
        file_type = "Excel" if ext in {".xls", ".xlsx"} else "CSV"
        
        # Получаем активную кодовую базу
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
        
        # Сразу пробуем конвертировать
        await processing_msg.edit_text(f"⏳ Конвертирую {file_type} в Markdown...")
        
        # Конвертируем таблицу в Markdown
        success, new_name, md_content = await self.file_manager.markdown_converter.convert_to_markdown(
            user_id, file_bytes, orig_name
        )
        
        if success and md_content:
            try:
                # Отправляем конвертированный файл пользователю
                await message.reply_document(
                    types.BufferedInputFile(
                        md_content.encode('utf-8') if isinstance(md_content, str) else md_content,
                        new_name
                    ),
                    caption=f"✅ {file_type} конвертирован в Markdown!\n📎 {new_name}"
                )
                
                await processing_msg.edit_text(
                    f"✅ Таблица успешно конвертирована!\n"
                    f"📊 Исходный файл: {orig_name}\n"
                    f"📝 Результат: {new_name}\n\n"
                    f"Конвертированный файл отправлен вам"
                )

                # Сохраняем для макро-команд
                if hasattr(self.handler, 'agent_handler') and self.handler.agent_handler:
                    content_str = md_content if isinstance(md_content, str) else md_content.decode('utf-8')
                    self.handler.agent_handler.save_md_file_for_macros(
                        user_id, new_name, content_str, orig_name
                    )
                
                # Используем метод из базового класса
                await self.offer_save_converted(
                    message,
                    new_name,
                    md_content.encode('utf-8') if isinstance(md_content, str) else md_content,
                    user_id,
                    codebase_id
                )
                
            except Exception as e:
                logger.error(f"Не удалось отправить конвертированный файл: {e}")
                await processing_msg.edit_text(f"❌ Ошибка отправки: {str(e)}")
        else:
            # Если конвертация не удалась, предлагаем сохранить как есть
            keyboard, token = await self.offer_save_original(
                message, orig_name, file_bytes, document.file_size,
                user_id, codebase_id, existing_token
            )
            
            await processing_msg.edit_text(
                f"⚠️ Не удалось конвертировать {file_type} файл\n"
                f"Файл: {orig_name}\n\n"
                f"Хотите сохранить оригинальный файл?",
                reply_markup=keyboard
            )