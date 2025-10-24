# code/handlers/agent_handlers/macro_handler.py

import os
import re
import logging
from datetime import datetime
from aiogram import types
from aiogram.types import BufferedInputFile
from utils.markdown_utils import escape_markdown_v2

from time import perf_counter
from user_activity_logger import activity_logger

logger = logging.getLogger(__name__)

class MacroCommandHandler:
    """Обработчик макро-команд для файлов"""
    
    def __init__(self, parent_handler):
        self.parent = parent_handler
        self.bot = parent_handler.bot
        self.last_md_files = {}
        
    async def handle_macro_command(self, message: types.Message, user_id: str, 
                                   macro_text: str) -> bool:
        """
        Обработка макро-команды. Возвращает True если команда обработана
        
        Args:
            message: Сообщение пользователя
            user_id: ID пользователя
            macro_text: Текст после @ (может содержать имя макроса и дополнительный запрос)
        """
        
        # Разбираем текст на имя макроса и дополнительный запрос
        parts = macro_text.split(None, 1)  # Разделяем по первому пробелу
        macro_name = parts[0].lower()
        additional_query = parts[1] if len(parts) > 1 else ""
        
        # Получаем информацию о макро-команде
        macro = self.parent.macro_commands.get_command(macro_name)
        if not macro:
            # Проверяем специальную команду help для макросов
            if macro_name == 'macros' or macro_name == 'macro':
                await self._show_macro_help(message)
                return True
            return False
        
        # Проверяем наличие последнего файла
        if user_id not in self.last_md_files:
            await message.reply(
                "⚠️ *Нет конвертированного файла для обработки*\n\n"
                "Сначала загрузите и конвертируйте файл:\n"
                "• PDF → Markdown\n"
                "• Аудио → Текст\n"
                "• Изображение → Текст \\(OCR\\)\n"
                "• HTML → Markdown\n"
                "• Таблицы → Markdown\n\n"
                "После конвертации вы сможете применять макро команды",
                parse_mode="MarkdownV2"
            )
            return True
        
        last_file = self.last_md_files[user_id]
        
        # Проверяем актуальность файла (не старше 2 часов)
        time_diff = datetime.now() - last_file['timestamp']
        if time_diff.total_seconds() > 7200:  # 2 часа
            hours_ago = int(time_diff.total_seconds()/3600)
            await message.reply(
                f"⚠️ Последний файл устарел \\(обработан {hours_ago} часов назад\\)\n"
                f"Загрузите новый файл для обработки",
                parse_mode="MarkdownV2"
            )
            return True
        
        # Получаем filejob агента
        if 'filejob' not in self.parent.system_agents:
            await message.reply("⚠️ Агент обработки файлов недоступен", parse_mode="MarkdownV2")
            return True
        
        filejob_agent = self.parent.system_agents['filejob']
        
        # Формируем финальный запрос
        base_query = macro['query']
        
        # Если есть дополнительный запрос, добавляем его
        if additional_query:
            final_query = f"{base_query}\n\nДополнительные инструкции от пользователя: {additional_query}"
            logger.info(f"Макро {macro_name} с дополнительным запросом: {additional_query}")
        else:
            final_query = base_query
        
        # Получаем тип файла для лучшего контекста
        file_type = last_file.get('file_type', 'text')
        
        # Адаптируем запрос под тип файла
        if file_type == 'code':
            context_prefix = "Это файл с исходным кодом. "
        elif file_type == 'config':
            context_prefix = "Это конфигурационный файл. "
        elif file_type == 'markdown':
            context_prefix = "Это документ в формате Markdown. "
        else:
            context_prefix = ""
        
        # Формируем запрос с учетом типа файла
        enhanced_query = context_prefix + final_query
        
        virtual_filename = f"content_{last_file['filename']}"
        filejob_query = f"{virtual_filename}\n{enhanced_query}"
        
        # Показываем информацию о выполнении
        info_text = f"📄 *Выполняю макро команду @{escape_markdown_v2(macro['name'])}*\n\n"
        info_text += f"📄 Файл: `{escape_markdown_v2(last_file['filename'])}`\n"
        info_text += f"📝 Тип: {escape_markdown_v2(file_type)}\n"
        info_text += f"📊 Размер: {escape_markdown_v2(str(len(last_file['content'])))} символов\n"
        
        if additional_query:
            truncated = additional_query[:50] + ('...' if len(additional_query) > 50 else '')
            info_text += f"➕ Доп\\. запрос: _{escape_markdown_v2(truncated)}_\n"
        
        info_text += f"⏱️ Обработка может занять некоторое время\\.\\.\\."
        
        processing_msg = await message.reply(
            info_text,
            parse_mode="MarkdownV2"
        )
        
        try:
            activity_logger.log(user_id, "MACRO_START", f"name={macro_name},file={last_file['filename']},add_query_len={len(additional_query)}")
            t0 = perf_counter()

            # Создаем специальный контекст с виртуальным файлом
            context = {
                'codebase_manager': self.parent.codebase_manager,
                'file_manager': self.parent.file_manager,
                'ai_interface': self.parent.ai_interface,
                'user_manager': self.parent.user_manager,
                # Передаем контент как виртуальный файл
                'virtual_files': {
                    virtual_filename: last_file['content']
                }
            }
            
            # Обрабатываем через filejob агента
            result = await filejob_agent.process(user_id, filejob_query, context)
            
            # Обрабатываем результат
            if isinstance(result, tuple) and len(result) >= 2:
                success = result[0]
                if len(result) == 3:
                    status_msg, final_result = result[1], result[2]
                else:
                    status_msg, final_result = result[1], None
            else:
                success, status_msg, final_result = False, "Неверный формат ответа", None
            
            await processing_msg.delete()

            duration = perf_counter() - t0
            activity_logger.log(user_id, "MACRO_END", f"name={macro_name},success={bool(success and final_result)},duration={duration:.2f}s")
            
            if success and final_result:
                # Сохраняем результат как новый файл
                result_filename = f"{macro['name']}_{last_file['original_filename']}.txt"
                self.parent.save_md_file_for_macros(
                    user_id,
                    result_filename,
                    final_result,
                    last_file['original_filename']
                )
                
                # Формируем содержимое файла
                file_content = f"# Результат макро команды @{macro['name']}\n\n"
                file_content += f"**Исходный файл:** {last_file['filename']}\n"
                file_content += f"**Оригинальный файл:** {last_file['original_filename']}\n"
                file_content += f"**Дата обработки:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                file_content += f"**Команда:** {macro['description']}\n"
                
                if additional_query:
                    file_content += f"**Дополнительный запрос:** {additional_query}\n"
                
                file_content += "\n---\n\n"
                file_content += final_result
                
                # Отправляем результат как файл
                file_bytes = file_content.encode('utf-8')
                output_filename = f"{macro['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                input_file = BufferedInputFile(
                    file=file_bytes,
                    filename=output_filename
                )
                
                caption = f"✅ *Макро команда @{escape_markdown_v2(macro['name'])} выполнена*\n\n"
                caption += f"📄 Исходный: `{escape_markdown_v2(last_file['filename'])}`\n"
                caption += f"📝 Результат: `{escape_markdown_v2(output_filename)}`\n"
                
                if additional_query:
                    truncated = additional_query[:30] + ('...' if len(additional_query) > 30 else '')
                    caption += f"➕ С учетом: _{escape_markdown_v2(truncated)}_\n"
                
                caption += f"\n💡 _Можете применить другую макро команду к результату_"
                
                await message.reply_document(
                    document=input_file,
                    caption=caption,
                    parse_mode="MarkdownV2"
                )
                
            else:
                error_msg = f"⚠️ *Ошибка выполнения макро команды*\n\n{escape_markdown_v2(status_msg)}"
                await message.reply(error_msg, parse_mode="MarkdownV2")
            
        except Exception as e:
            logger.error(f"Ошибка при выполнении макро команды {macro_name}: {e}", exc_info=True)
            try:
                await processing_msg.delete()
            except:
                pass
            await message.reply(
                f"⚠️ *Ошибка обработки*\n\n`{escape_markdown_v2(str(e))}`",
                parse_mode="MarkdownV2"
            )
        
        return True
    
    async def _show_macro_help(self, message: types.Message):
        """Показать справку по макро-командам"""
        help_text = "*📋 Быстрые макро команды для файлов*\n"
        help_text += "_Используйте после конвертации файла:_\n\n"
        
        all_commands = self.parent.macro_commands.get_all_commands()
        
        # Группируем команды по категориям для удобства
        text_commands = ['sum', 'analyze', 'translate', 'translate_ru', 'keywords', 
                        'questions', 'outline', 'improve', 'explain', 'tasks', 'entities']
        code_commands = ['code', 'refactor', 'comment', 'tests', 'security', 
                        'readme', 'api', 'clean', 'extract']
        
        help_text += "*📝 Обработка текста:*\n"
        for cmd_name in text_commands:
            if cmd_name in all_commands:
                cmd_info = all_commands[cmd_name]
                help_text += f"• `@{cmd_name}` \\- {escape_markdown_v2(cmd_info['description'])}\n"
        
        help_text += "\n*💻 Обработка кода:*\n"
        for cmd_name in code_commands:
            if cmd_name in all_commands:
                cmd_info = all_commands[cmd_name]
                help_text += f"• `@{cmd_name}` \\- {escape_markdown_v2(cmd_info['description'])}\n"
        
        help_text += "\n💡 *Возможности:*\n"
        help_text += "• Команды применяются к последнему загруженному файлу\n"
        help_text += "• Можно добавить свой запрос после команды:\n"
        help_text += "  `@sum с фокусом на технические детали`\n"
        help_text += "  `@translate на французский язык`\n"
        help_text += "• Результат сохраняется как новый файл\n"
        help_text += "• К результату можно применить другую команду"
        
        await message.reply(help_text, parse_mode="MarkdownV2")