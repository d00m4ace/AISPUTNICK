# code/handlers/file_operations/processors/document.py
"""
Процессор для обработки документов (PDF, Word, PowerPoint, HTML)
"""
import os
import logging
from aiogram import types
from aiogram.fsm.context import FSMContext
from ..states import FileStates
from .base_processor import BaseProcessor

logger = logging.getLogger(__name__)

class DocumentProcessor(BaseProcessor):
    """Обработчик документов"""
    
    async def process_pdf_file(self, message, processing_msg, orig_name, file_bytes, 
                              state, user_id, codebase_id):
        """Обработка PDF файла"""
        await state.set_state(FileStates.processing_pdf)
        await state.update_data(
            processing_pdf=True,
            cancel_requested=False,
            pdf_filename=orig_name,
            pdf_data=file_bytes,
            progress_msg=processing_msg
        )
        
        await processing_msg.edit_text(
            f"📄 Обрабатываю PDF файл '{orig_name}'...\n"
            f"⏳ Анализирую структуру документа..."
        )
        
        async def update_progress(text: str):
            try:
                await processing_msg.edit_text(text)
            except Exception as e:
                logger.warning(f"Не удалось обновить прогресс: {e}")
        
        async def check_cancel():
            data = await state.get_data()
            return data.get("cancel_requested", False)
        
        # Конвертируем PDF в Markdown
        success, new_name, md_content = await self.file_manager.markdown_converter.convert_to_markdown(
            user_id,
            file_bytes, orig_name,
            progress_callback=update_progress,
            cancel_check=check_cancel
        )
        
        await state.clear()
        
        if success and md_content:
            try:
                # Отправляем конвертированный файл пользователю
                await message.reply_document(
                    types.BufferedInputFile(
                        md_content.encode('utf-8') if isinstance(md_content, str) else md_content,
                        new_name
                    ),
                    caption=f"✅ PDF конвертирован в Markdown!\n📎 {new_name}"
                )
                
                await processing_msg.edit_text(
                    f"✅ PDF успешно конвертирован!\n"
                    f"📄 Исходный файл: {orig_name}\n"
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
                await processing_msg.edit_text(
                    f"❌ Ошибка отправки конвертированного файла: {str(e)}"
                )
        else:
            # Конвертация не удалась
            await processing_msg.edit_text(
                f"❌ Не удалось конвертировать PDF в Markdown\n"
                f"Файл: {orig_name}\n\n"
                f"Попробуйте другой PDF или проверьте, что файл не поврежден"
            )

    async def process_html_file(self, message, processing_msg, orig_name, file_bytes, user_id, codebase_id):
        """Обработка HTML файлов"""
        await processing_msg.edit_text(f"⏳ Конвертирую HTML в Markdown...")
    
        # Конвертируем HTML в Markdown
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
                    caption=f"✅ HTML конвертирован в Markdown!\n📎 {new_name}"
                )
            
                await processing_msg.edit_text(
                    f"✅ HTML успешно конвертирован!\n"
                    f"🌐 Исходный файл: {orig_name}\n"
                    f"📝 Результат: {new_name}\n\n"
                    f"Конвертированный файл отправлен вам"
                )

                # Сохраняем для макро-команд
                if hasattr(self.handler, 'agent_handler') and self.handler.agent_handler:
                    content_str = md_content if isinstance(md_content, str) else md_content.decode('utf-8')
                    self.handler.agent_handler.save_md_file_for_macros(
                        user_id, new_name, content_str, orig_name
                    )
            
                # Предлагаем сохранить конвертированную версию в базу
                await self.offer_save_converted(
                    message,
                    new_name,
                    md_content.encode('utf-8') if isinstance(md_content, str) else md_content,
                    user_id,
                    codebase_id
                )
            
            except Exception as e:
                logger.error(f"Не удалось отправить конвертированный файл: {e}")
                await processing_msg.edit_text(
                    f"❌ Ошибка отправки конвертированного файла: {str(e)}"
                )
        else:
            await processing_msg.edit_text(
                f"❌ Не удалось конвертировать HTML в Markdown\n"
                f"Файл: {orig_name}\n\n"
                f"Возможные причины:\n"
                f"• Файл поврежден или имеет некорректную структуру\n"
                f"• Слишком сложная структура HTML\n"
                f"• Отсутствуют необходимые библиотеки для конвертации"
            )

    async def process_powerpoint_file(self, message, processing_msg, orig_name, file_bytes, user_id, codebase_id):
        """Обработка PowerPoint файлов"""
        ext = os.path.splitext(orig_name.lower())[1]
        file_type = "PowerPoint" if ext == ".pptx" else "PowerPoint 97-2003"
    
        await processing_msg.edit_text(f"⏳ Конвертирую {file_type} в Markdown...")
    
        # Конвертируем PowerPoint в Markdown
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
                    f"✅ {file_type} успешно конвертирован!\n"
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
            
                # Предлагаем сохранить конвертированную версию в базу
                await self.offer_save_converted(
                    message,
                    new_name,
                    md_content.encode('utf-8') if isinstance(md_content, str) else md_content,
                    user_id,
                    codebase_id
                )
            
            except Exception as e:
                logger.error(f"Не удалось отправить конвертированный файл: {e}")
                await processing_msg.edit_text(
                    f"❌ Ошибка отправки конвертированного файла: {str(e)}"
                )
        else:
            # Конвертация не удалась
            await processing_msg.edit_text(
                f"❌ Не удалось конвертировать {file_type} в Markdown\n"
                f"Файл: {orig_name}\n\n"
                f"Возможные причины:\n"
                f"• Файл защищен паролем\n"
                f"• Презентация повреждена\n"
                f"• Используются несовместимые элементы\n"
                f"• Требуется установка python-pptx или других библиотек"
            )

    async def process_document_file(self, message, processing_msg, orig_name, file_bytes, user_id, codebase_id):
        """Обработка документов Word/RTF/ODT"""
        ext = os.path.splitext(orig_name.lower())[1]
        doc_type = {
            '.docx': 'Word',
            '.doc': 'Word 97-2003',
            '.rtf': 'RTF',
            '.odt': 'OpenDocument'
        }.get(ext, 'Документ')
    
        await processing_msg.edit_text(f"⏳ Конвертирую {doc_type} в Markdown...")
    
        # Конвертируем документ в Markdown
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
                    caption=f"✅ {doc_type} конвертирован в Markdown!\n📎 {new_name}"
                )
            
                await processing_msg.edit_text(
                    f"✅ Документ успешно конвертирован!\n"
                    f"📄 Исходный файл: {orig_name}\n"
                    f"📝 Результат: {new_name}\n\n"
                    f"Конвертированный файл отправлен вам"
                )

                # Сохраняем для макро-команд
                if hasattr(self.handler, 'agent_handler') and self.handler.agent_handler:
                    content_str = md_content if isinstance(md_content, str) else md_content.decode('utf-8')
                    self.handler.agent_handler.save_md_file_for_macros(
                        user_id, new_name, content_str, orig_name
                    )
            
                # Предлагаем сохранить конвертированную версию в базу
                await self.offer_save_converted(
                    message,
                    new_name,
                    md_content.encode('utf-8') if isinstance(md_content, str) else md_content,
                    user_id,
                    codebase_id
                )
            
            except Exception as e:
                logger.error(f"Не удалось отправить конвертированный файл: {e}")
                await processing_msg.edit_text(
                    f"❌ Ошибка отправки конвертированного файла: {str(e)}"
                )
        else:
            # Конвертация не удалась
            await processing_msg.edit_text(
                f"❌ Не удалось конвертировать {doc_type} в Markdown\n"
                f"Файл: {orig_name}\n\n"
                f"Возможные причины:\n"
                f"• Файл поврежден или защищен паролем\n"
                f"• Несовместимый формат документа\n"
                f"• Отсутствует pandoc или python-docx для конвертации\n"
                f"• Документ содержит сложное форматирование"
            )

