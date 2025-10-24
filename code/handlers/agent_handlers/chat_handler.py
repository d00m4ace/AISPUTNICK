# code/handlers/agent_handlers/chat_handler.py

import logging
from datetime import datetime
from typing import Dict, Any, Tuple
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile
from utils.markdown_utils import escape_markdown_v2
from utils.info_utils import info_welcome_chat_message, info_cmd_chat_message, info_chat_help_message

from time import perf_counter
from user_activity_logger import activity_logger

logger = logging.getLogger(__name__)

class ChatStates(StatesGroup):
    """Состояния для работы с чат агентами"""
    active_chat = State()

class ChatAgentHandler:
    """Обработчик для чат-агентов"""
    
    def __init__(self, parent_handler):
        self.parent = parent_handler
        self.bot = parent_handler.bot
        self.active_chat_sessions = {}
        self.user_file_contexts = {}
        
    async def activate_chat_mode(self, message: types.Message, state: FSMContext,
                                 user_id: str, agent_name: str, initial_query: str):
        """Активация чат-режима с расширенной информацией о работе с файлами"""
        self.active_chat_sessions[user_id] = {
            'agent_name': agent_name,
            'started_at': datetime.now().isoformat()
        }
        
        await state.set_state(ChatStates.active_chat)
        
        agent = await self.parent._get_agent_instance(user_id, agent_name)
        
        # Собираем информацию о настройках агента
        history_info = ""
        file_info = ""
        
        if agent and hasattr(agent, 'get_config'):
            config = agent.get_config()
            
            # Информация об истории
            if config.get('history', {}).get('enabled', False):
                history_config = config.get('history', {})
                history_info = "\n\n📄 *История сообщений:* ✅ *Включена*"
                history_info += f" \\(макс\\. {escape_markdown_v2(str(history_config.get('max_messages', 20)))} сообщений\\)"
                
                if history_config.get('clear_files_on_history_clear', True):
                    history_info += "\n• При очистке истории удаляются и файлы"
                    
            # Информация о работе с файлами
            file_config = config.get('file_context', {})
            if file_config.get('enabled', True):
                file_info = "\n📎 *Работа с файлами:*"
                
                multi_mode = file_config.get('multi_file_mode', 'merge')
                if multi_mode == 'merge':
                    file_info += "\n• 📚 *Режим:* объединение всех файлов"
                    file_info += "\n• Можно загрузить несколько файлов"
                    file_info += "\n• Все файлы будут объединены в один контекст"
                else:
                    file_info += "\n• 📄 *Режим:* только последний файл"
                    file_info += "\n• Новый файл заменяет предыдущий"
                
                max_size = file_config.get('max_content_length', 200000)
                if max_size >= 1024*1024:
                    size_str = f"{max_size/(1024*1024):.1f} МБ"
                elif max_size >= 1024:
                    size_str = f"{max_size/1024:.0f} КБ"
                else:
                    size_str = f"{max_size} символов"
                file_info += f"\n• Макс\\. размер: {escape_markdown_v2(size_str)}"
                
        welcome_msg = info_welcome_chat_message(escape_markdown_v2(agent_name))
        
        if file_info:
            welcome_msg += file_info
        
        if history_info:
            welcome_msg += history_info
            welcome_msg += "\n\n" + info_cmd_chat_message()

        welcome_msg += "\n" + info_chat_help_message()
        
        # Проверяем, есть ли уже загруженные файлы
        if hasattr(agent, 'get_user_files_info'):
            files_info = agent.get_user_files_info(user_id)
            if files_info['files_count'] > 0:
                welcome_msg += f"\n\n📂 *Уже загружено файлов:* {files_info['files_count']}"
                if files_info['total_size'] >= 1024*1024:
                    size_str = f"{files_info['total_size']/(1024*1024):.1f} МБ"
                elif files_info['total_size'] >= 1024:
                    size_str = f"{files_info['total_size']/1024:.1f} КБ"
                else:
                    size_str = f"{files_info['total_size']} байт"
                welcome_msg += f"\n📊 *Общий размер:* {escape_markdown_v2(size_str)}"
                
        await message.reply(welcome_msg, parse_mode="MarkdownV2")
        
        # Если есть начальный запрос, обрабатываем его
        if initial_query:
            await self.process_chat_query(message, state, user_id, agent_name, initial_query)
            
    async def process_chat_query(self, original_message: types.Message, state: FSMContext,
                                 user_id: str, agent_name: str, query_text: str):
        """Обработка запроса в чат-режиме"""
        
        # Проверяем активность сессии
        if user_id not in self.active_chat_sessions:
            await state.clear()
            await original_message.reply(
                "Чат сессия завершена\\. Используйте @chat или другого агента для начала нового чата\\.",
                parse_mode="MarkdownV2"
            )
            return
        
        session = self.active_chat_sessions[user_id]
        agent_name = session.get('agent_name', agent_name)
        
        # Получаем агента
        agent = await self.parent._get_agent_instance(user_id, agent_name)
        if not agent:
            await original_message.reply(
                f"❌ Агент @{escape_markdown_v2(agent_name)} не найден",
                parse_mode="MarkdownV2"
            )
            await state.clear()
            del self.active_chat_sessions[user_id]
            return
        
        # Подготавливаем контекст с последним файлом пользователя
        context = {
            'codebase_manager': self.parent.codebase_manager,
            'file_manager': self.parent.file_manager,
            'ai_interface': self.parent.ai_interface,
            'user_manager': self.parent.user_manager
        }
        
        # Добавляем контекст файла если есть
        if user_id in self.user_file_contexts:
            context['last_file_content'] = self.user_file_contexts[user_id]
        
        # Обрабатываем сообщение через чат агента
        processing_msg = await original_message.reply(f"💭 *@{escape_markdown_v2(agent_name)}* обрабатывает запрос\\.\\.\\.", parse_mode="MarkdownV2")
        
        t0 = perf_counter()
        activity_logger.log(user_id, "AGENT_CALL_START", f"agent={agent_name},type=chat,query_len={len(query_text)}")

        try:
            success, response = await agent.process(user_id, query_text, context)
            
            duration = perf_counter() - t0
            activity_logger.log(user_id, "AGENT_CALL_END", f"agent={agent_name},type=chat,success={success},duration={duration:.2f}s,response_len={len(response) if isinstance(response,str) else 0}")

            await processing_msg.delete()
            
            if success:
                # Проверяем длину ответа
                if len(response) > 4000:
                    # Создаем файл с ответом
                    file_content = f"# Ответ агента @{agent_name}\n\n"
                    file_content += f"**Запрос:** {query_text}\n\n"
                    file_content += f"**Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    file_content += "---\n\n"
                    clean_response = response.replace("\\", "")
                    file_content += clean_response
                    
                    file_bytes = file_content.encode('utf-8')
                    input_file = BufferedInputFile(
                        file=file_bytes,
                        filename=f"chat_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    )
                    
                    await original_message.reply_document(
                        document=input_file,
                        caption="💬 Ответ слишком большой и сохранен в файл",
                        parse_mode=None
                    )
                else:
                    try:
                        await original_message.reply(response, parse_mode="MarkdownV2")
                    except:
                        # Если ошибка форматирования, отправляем без форматирования
                        await original_message.reply(response.replace("\\", ""), parse_mode=None)
            else:
                await original_message.reply(response, parse_mode="MarkdownV2")
                
        except Exception as e:
            duration = perf_counter() - t0
            activity_logger.log(user_id, "AGENT_CALL_ERROR", f"agent={agent_name},type=chat,error={str(e)},duration={duration:.2f}s")
            logger.error(f"Ошибка в чате с агентом {agent_name}: {e}", exc_info=True)
            try:
                await processing_msg.delete()
            except:
                pass
            await original_message.reply(
                f"❌ Ошибка: {escape_markdown_v2(str(e))}",
                parse_mode="MarkdownV2"
            )
            
    async def handle_chat_document(self, message: types.Message, state: FSMContext):
        """Обработка документов в чат-режиме с поддержкой множественных файлов"""
        user_id = str(message.from_user.id)
        
        if not message.document:
            return
        
        if user_id not in self.active_chat_sessions:
            await state.clear()
            return
        
        from config import Config
        if not Config.is_text_file(message.document.file_name):
            await message.reply("⚠️ В режиме чата поддерживаются только текстовые файлы\\.", parse_mode="MarkdownV2")
            return
        
        session = self.active_chat_sessions[user_id]
        agent_name = session.get('agent_name', 'chat')
        
        agent = await self.parent._get_agent_instance(user_id, agent_name)
        if not agent:
            await message.reply(f"❌ Агент @{escape_markdown_v2(agent_name)} не найден", parse_mode="MarkdownV2")
            return
        
        # Получаем конфигурацию файлового контекста
        config = agent.get_config()
        file_config = config.get('file_context', {})
        max_file_size = file_config.get('max_content_length', 200000)
        multi_file_mode = file_config.get('multi_file_mode', 'merge')
        
        processing_msg = await message.reply(f"📄 Загружаю файл для чата\\.\\.\\.", parse_mode="MarkdownV2")
        
        try:
            # Загрузка файла
            file = await self.bot.get_file(message.document.file_id)
            file_data = await self.bot.download_file(file.file_path)
            
            if hasattr(file_data, 'getvalue'):
                file_bytes = file_data.getvalue()
            else:
                file_bytes = file_data
            
            try:
                content = file_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    content = file_bytes.decode('cp1251')
                except:
                    content = file_bytes.decode('latin-1')
                    
            # Добавляем файл в контекст агента
            if hasattr(agent, 'add_file_context'):
                file_info = agent.add_file_context(user_id, message.document.file_name, content)
                
                # Получаем объединенный контекст всех файлов
                merged_context = agent.get_merged_file_context(user_id)
                
                # Сохраняем в глобальный контекст для использования в процессе
                self.user_file_contexts[user_id] = merged_context
                
                try:
                    await processing_msg.delete()
                except:
                    pass
                
                # Формируем информационное сообщение
                if file_info['mode'] == 'merge':
                    if file_info['files_count'] > 1:
                        info_msg = f"✅ Файл *{escape_markdown_v2(message.document.file_name)}* добавлен в контекст чата\\.\n"
                        info_msg += f"📚 Всего файлов в контексте: *{file_info['files_count']}*\n"
                        
                        # Форматируем размер с правильным экранированием точки
                        if file_info['total_size'] >= 1024*1024:
                            size_mb = file_info['total_size']/(1024*1024)
                            size_str = f"{size_mb:.1f} МБ"
                        elif file_info['total_size'] >= 1024:
                            size_kb = file_info['total_size']/1024
                            size_str = f"{size_kb:.1f} КБ"
                        else:
                            size_str = f"{file_info['total_size']} байт"
                        
                        info_msg += f"📊 Общий размер: *{escape_markdown_v2(size_str)}*"
                        
                        if file_info['total_size'] < file_info['total_original_size']:
                            original_mb = file_info['total_original_size'] / (1024*1024)
                            info_msg += f"\n⚠️ Содержимое было обрезано с {escape_markdown_v2(f'{original_mb:.1f}')} МБ до лимита агента"
                        
                        info_msg += "\n\n💬 *Режим:* Объединение всех файлов"
                        info_msg += "\n📄 Все файлы объединены в один контекст для ИИ"
                    else:
                        info_msg = f"✅ Файл *{escape_markdown_v2(message.document.file_name)}* загружен в контекст чата\\."
                        if file_info['truncated']:
                            info_msg += f"\n⚠️ Файл был обрезан до {escape_markdown_v2(str(max_file_size))} символов из\\-за ограничений агента\\."
                else:  # mode == 'last'
                    info_msg = f"✅ Файл *{escape_markdown_v2(message.document.file_name)}* заменил предыдущий контекст\\."
                    info_msg += "\n\n💬 *Режим:* Только последний файл"
                    if file_info['truncated']:
                        info_msg += f"\n⚠️ Файл был обрезан до {escape_markdown_v2(str(max_file_size))} символов\\."
                    
                info_msg += "\n\nТеперь вы можете задавать вопросы по содержимому файла\\(ов\\)\\."
                
                await message.reply(info_msg, parse_mode="MarkdownV2")
            else:
                # Старая логика для агентов без поддержки множественных файлов
                if len(content) > max_file_size:
                    content = content[:max_file_size]
                    truncated = True
                else:
                    truncated = False
                
                self.user_file_contexts[user_id] = {
                    'filename': message.document.file_name,
                    'content': content
                }
                
                try:
                    await processing_msg.delete()
                except:
                    pass
                
                info_msg = f"✅ Файл *{escape_markdown_v2(message.document.file_name)}* загружен в контекст чата\\."
                if truncated:
                    info_msg += f"\n⚠️ Файл был обрезан до {escape_markdown_v2(str(max_file_size))} символов из\\-за ограничений агента\\."
                info_msg += "\n\nТеперь вы можете задавать вопросы по содержимому файла\\."
                
                await message.reply(info_msg, parse_mode="MarkdownV2")
                
        except Exception as e:
            logger.error(f"Ошибка загрузки файла в чат: {e}", exc_info=True)
            try:
                await processing_msg.delete()
            except:
                pass
            await message.reply(f"❌ Ошибка загрузки файла: {escape_markdown_v2(str(e))}", parse_mode="MarkdownV2")