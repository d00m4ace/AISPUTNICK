# code/handlers/agent_handlers/message_router.py

import re
import logging
import asyncio
from datetime import datetime
from aiogram import types
from aiogram.fsm.context import FSMContext
from utils.markdown_utils import escape_markdown_v2
from utils.info_utils import (
    info_global_help_message,
    info_nocmd_chat_message,
    info_unprocessed_message_in_state,
    info_invalid_format,
    info_agent_not_found,
    info_upload_preparing,
    info_upload_error,
    info_upload_help_message,
    info_invalid_agent_response
)

logger = logging.getLogger(__name__)

class MessageRouter:
    """Маршрутизация сообщений к соответствующим обработчикам"""
    
    def __init__(self, handler):
        self.handler = handler

    async def handle_text_message(self, message: types.Message, state: FSMContext):
        """Обработка простых текстовых сообщений"""
        user_id = str(message.from_user.id)
        
        # Обработка продолжения запросов к активному nethack агенту
        if hasattr(self.handler, 'nethack_manager'):
            handled = await self.handler.nethack_manager.handle_continuation(message)
            if handled:
                return
        
        # Проверка последнего использованного агента
        if hasattr(self.handler, 'agent_processor') and hasattr(self.handler.agent_processor, '_last_agent_used'):
            if user_id in self.handler.agent_processor._last_agent_used:
                last_agent = self.handler.agent_processor._last_agent_used[user_id]
                
                # Проверяем, что это не nethack агент (он уже обработан выше)
                agent_config = await self.handler.config_manager.get_agent_config(
                    user_id, last_agent, self.handler.system_agents
                )
                
                if agent_config and agent_config.get('type') != 'nethack':
                    # Получаем агент
                    agent = await self.handler._get_agent_instance(user_id, last_agent)
                    
                    if agent:
                        logger.info(f"Продолжение работы с последним агентом {last_agent} для пользователя {user_id}")
                        
                        # Обрабатываем запрос через последний агент
                        await self.handler.agent_processor.process_regular_agent(
                            message, user_id, last_agent, message.text, agent,
                            self.handler.upload_handler, self.handler.chat_handler
                        )
                        
                        # Обновляем время последнего использования
                        await self.handler.agent_processor.update_last_agent_used(user_id, last_agent)
                        return
        
        # Если не обработано выводим сообщение о необработанных командах
        current_state = await state.get_state()
        
        if current_state:
            logger.warning(f"Необработанное сообщение в состоянии {current_state}: {message.text}")
            await message.reply(info_unprocessed_message_in_state(current_state, message.text))
            return
        
        # Если сообщение не обработано и не команда - перенаправляем агенту @hero
        if not message.text or not message.text.startswith('/'):
            # Проверяем доступ пользователя
            if not await self.handler.user_manager.is_active(user_id):
                from utils.info_utils import info_no_access
                await message.reply(info_no_access())
                return
            
            agent_name = 'hero'
            query = message.text if message.text else ""
            
            # Получаем экземпляр агента и конфигурацию
            agent = await self.handler._get_agent_instance(user_id, agent_name)
            agent_config = await self.handler.config_manager.get_agent_config(
                user_id, agent_name, self.handler.system_agents
            )
            
            if not agent:
                # Если агент hero не найден, показываем справку как раньше
                await message.reply(info_global_help_message(), parse_mode="MarkdownV2")
                return
            
            # Проверяем, что это nethack агент
            if agent_config and agent_config.get('type') == 'nethack':
                # Останавливаем все активные процессы
                if hasattr(self.handler, 'session_manager'):
                    await self.handler.session_manager.stop_all_active_agents(user_id, state)
                
                # Активируем nethack сессию
                if hasattr(self.handler, 'nethack_manager'):
                    self.handler.nethack_manager.activate_session(user_id, agent_name)
                    logger.info(f"Автоматически активирована nethack сессия с агентом {agent_name} для пользователя {user_id}")
                    
                    # Обрабатываем запрос
                    if query:
                        await self.handler.agent_processor.process_regular_agent(
                            message, user_id, agent_name, query, agent,
                            self.handler.upload_handler, self.handler.chat_handler
                        )
                    else:
                        # Если текст пустой, показываем справку по nethack агенту
                        await self.handler.agent_processor.show_agent_help(message, agent_name, agent_config)
                    
                    # Обновляем последний использованный агент
                    await self.handler.agent_processor.update_last_agent_used(user_id, agent_name)
            else:
                # Если hero не является nethack агентом, показываем справку
                await message.reply(info_global_help_message(), parse_mode="MarkdownV2")    
   
    async def handle_chat_message(self, message: types.Message, state: FSMContext):
        """Обработка сообщений в активном чате"""
        user_id = str(message.from_user.id)
        
        # ВАЖНО: Проверяем, что это НЕ команда и НЕ вызов агента
        if message.text:
            if message.text.startswith('/') or message.text.startswith('@'):
                # Получаем последнего использованного агента
                if hasattr(self.handler, 'agent_processor') and hasattr(self.handler.agent_processor, '_last_agent_used'):
                    if user_id in self.handler.agent_processor._last_agent_used:
                        last_agent = self.handler.agent_processor._last_agent_used[user_id]
                    else:
                        last_agent = 'chat'
                else:
                    last_agent = 'chat'
                
                # Это команда или вызов агента - пропускаем для обработки другими хендлерами
                await asyncio.sleep(1)
                await message.reply(info_nocmd_chat_message(escape_markdown_v2(last_agent), message.text), parse_mode="MarkdownV2")
                await asyncio.sleep(0.5)
                return
        
        # Проверяем, что чат действительно активен
        if user_id not in self.handler.chat_handler.active_chat_sessions:
            await state.clear()
            return
        
        # Обрабатываем как обычное сообщение чата
        await self.handler.chat_handler.process_chat_query(message, state, user_id, 'chat', message.text)
    
    async def handle_chat_document(self, message: types.Message, state: FSMContext):
        """Обработка документов в активном чате"""
        await self.handler.chat_handler.handle_chat_document(message, state)
    
    async def handle_agent_call(self, message: types.Message, state: FSMContext):
        """Обработка вызова агентов через @"""
        user_id = str(message.from_user.id)
        
        if not await self.handler.user_manager.is_active(user_id):
            from utils.info_utils import info_no_access
            await message.reply(info_no_access())
            return
        
        text = message.text
        
        # Извлекаем имя агента и запрос из текста
        match = re.match(r'^@(\w+)(?:\s+(.*))?$', text, re.DOTALL)
        if not match:
            await message.reply(info_invalid_format(), parse_mode="MarkdownV2")
            return
        
        agent_name = match.group(1).lower()
        query = match.group(2).strip() if match.group(2) else ""
        
        # Для макро-команд передаем весь текст после @
        macro_text = text[1:].strip()  # Убираем @ и пробелы
        if await self.handler.macro_handler.handle_macro_command(message, user_id, macro_text):
            # Макро-команда обработана
            return
        
        # Проверка специальной команды config
        if query == "config":
            await self.handler.agent_processor.send_agent_config(
                message, user_id, agent_name, self.handler.system_agents
            )
            return
        
        # Получаем экземпляр агента и конфигурацию
        agent = await self.handler._get_agent_instance(user_id, agent_name)
        agent_config = await self.handler.config_manager.get_agent_config(
            user_id, agent_name, self.handler.system_agents
        )
        
        if not agent:
            await message.reply(info_agent_not_found(agent_name), parse_mode="MarkdownV2")
            return
        
        # ВСЕГДА останавливаем все активные процессы при вызове любого агента через @
        if hasattr(self.handler, 'session_manager'):
            await self.handler.session_manager.stop_all_active_agents(user_id, state)
        
        # Обработка nethack агента
        if agent_config and agent_config.get('type') == 'nethack':
            await self._handle_nethack_agent(message, user_id, agent_name, query, agent, agent_config)
            return
        
        # Обработка архивного агента (ZIP)
        if agent_config and agent_config.get('type') == 'archive':
            success = await agent.activate(message, user_id, self.handler)
            if success:
                await self.handler.agent_processor.update_last_agent_used(user_id, agent_name)
            return
        
        # Обработка UPLOAD агента
        if agent_name == 'upload':
            await self._handle_upload_agent(message, user_id, agent_name, query, agent)
            return
        
        # Обработка chat агентов
        if agent_config and agent_config.get('type') == 'chat':
            await self.handler.chat_handler.activate_chat_mode(message, state, user_id, agent_name, query)
            await self.handler.agent_processor.update_last_agent_used(user_id, agent_name)
            return
        
        # Обработка fileworker агентов (filejob)
        if agent_config and agent_config.get('type') == 'fileworker':
            await self.handler.filejob_handler.process_fileworker_agent(
                message, user_id, agent_name, query, agent,
                cont={'message': message}
            )
            await self.handler.agent_processor.update_last_agent_used(user_id, agent_name)
            return
        
        # Для остальных агентов (rag и др.) проверяем наличие запроса
        if not query:
            await self.handler.agent_processor.show_agent_help(message, agent_name, agent_config)
            return
        
        # Обработка обычных агентов (rag и др.)
        await self.handler.agent_processor.process_regular_agent(
            message, user_id, agent_name, query, agent,
            self.handler.upload_handler, self.handler.chat_handler
        )
        await self.handler.agent_processor.update_last_agent_used(user_id, agent_name)
    
    async def _handle_nethack_agent(self, message, user_id, agent_name, query, agent, agent_config):
        """Обработка nethack агента"""
        if hasattr(self.handler, 'nethack_manager'):
            self.handler.nethack_manager.activate_session(user_id, agent_name)
            logger.info(f"Активирована nethack сессия с агентом {agent_name} для пользователя {user_id}")
            
            # Если есть начальный запрос, обрабатываем его
            if query:
                await self.handler.agent_processor.process_regular_agent(
                    message, user_id, agent_name, query, agent,
                    self.handler.upload_handler, self.handler.chat_handler
                )
            else:
                # Показываем справку по nethack агенту
                await self.handler.agent_processor.show_agent_help(message, agent_name, agent_config)
            
            await self.handler.agent_processor.update_last_agent_used(user_id, agent_name)
    
    async def _handle_upload_agent(self, message, user_id, agent_name, query, agent):
        """Обработка upload агента"""
        if query:
            # Передаем upload_handler в контекст если он доступен
            context = {
                'codebase_manager': self.handler.codebase_manager,
                'file_manager': self.handler.file_manager,
                'ai_interface': self.handler.ai_interface,
                'user_manager': self.handler.user_manager,
                'message': message,
                'agent_handler': self.handler
            }
            
            if hasattr(self.handler, 'upload_handler'):
                context['upload_handler'] = self.handler.upload_handler
            
            processing_msg = await message.reply(info_upload_preparing(), parse_mode="MarkdownV2")
            
            try:
                result = await agent.process(user_id, query, context)
                
                await processing_msg.delete()
                
                if isinstance(result, tuple) and len(result) >= 2:
                    success = result[0]
                    response = result[1]
                    await message.reply(response, parse_mode="MarkdownV2")
                else:
                    await message.reply(info_invalid_agent_response(), parse_mode="MarkdownV2")
                
            except Exception as e:
                logger.error(f"Ошибка при работе Upload агента: {e}", exc_info=True)
                await processing_msg.delete()
                await message.reply(info_upload_error(str(e)), parse_mode="MarkdownV2")
            
            await self.handler.agent_processor.update_last_agent_used(user_id, agent_name)
        else:
            # Показываем справку если нет URL
            await message.reply(info_upload_help_message(), parse_mode="MarkdownV2")
            await self.handler.agent_processor.update_last_agent_used(user_id, agent_name)