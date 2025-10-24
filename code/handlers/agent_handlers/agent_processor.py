# code/handlers/agent_handlers/agent_processor.py

import os
import json
import re
import logging
from datetime import datetime
from typing import Dict, Any
from time import perf_counter
import asyncio
from aiogram import types
from aiogram.types import BufferedInputFile, FSInputFile
from utils.markdown_utils import escape_markdown_v2
from utils.info_utils import (
    info_agent_processing,
    info_agent_result_too_large,
    info_invalid_agent_response,
    info_agent_help_header,
    info_agent_description,
    info_archive_agent_help,
    info_rag_agent_help,
    info_chat_agent_help,
    info_fileworker_agent_help,
    info_generic_agent_help,
    info_system_agent_help,
    info_agent_config_command,
    info_agent_config_caption,
    info_agent_not_found
)
from user_activity_logger import activity_logger

logger = logging.getLogger(__name__)

class AgentProcessor:
    """Обработка запросов к агентам"""
    
    def __init__(self, bot, config_manager, codebase_manager, file_manager, ai_interface, user_manager):
        self.bot = bot
        self.config_manager = config_manager
        self.codebase_manager = codebase_manager
        self.file_manager = file_manager
        self.ai_interface = ai_interface
        self.user_manager = user_manager
        
        # Отслеживание последнего использованного агента
        self._last_agent_used = {}
        self._last_agent_used_time = {}
    
    async def update_last_agent_used(self, user_id: str, agent_name: str):
        """Обновляет информацию о последнем использованном агенте"""
        self._last_agent_used[user_id] = agent_name
        self._last_agent_used_time[user_id] = datetime.now()
        logger.debug(f"Обновлен последний агент для {user_id}: {agent_name}")
    
    async def show_agent_help(self, message: types.Message, agent_name: str, agent_config: Dict):
        """Показывает справку по агенту когда нет запроса"""
        help_text = info_agent_help_header(agent_name)
        
        if agent_config:
            description = agent_config.get('description', 'Без описания')
            help_text += info_agent_description(description)
            
            agent_type = agent_config.get('type', 'unknown')
            
            if agent_type == 'archive':
                help_text += info_archive_agent_help(agent_name)
            elif agent_type == 'rag':
                help_text += info_rag_agent_help(agent_name)
            elif agent_type == 'chat':
                help_text += info_chat_agent_help(agent_name)
            elif agent_type == 'fileworker':
                help_text += info_fileworker_agent_help(agent_name)
            else:
                help_text += info_generic_agent_help(agent_name, agent_type)
        else:
            help_text += info_system_agent_help(agent_name)
        
        help_text += info_agent_config_command(agent_name)
        
        await message.reply(help_text, parse_mode="MarkdownV2")
    
    async def process_regular_agent(self, message: types.Message, user_id: str, agent_name: str, 
                                   query: str, agent, upload_handler=None, chat_handler=None):
        """Обработка обычного (не чат) агента"""
        t0 = perf_counter()
        agent_cfg = agent.get_config() if hasattr(agent, 'get_config') else {}
        agent_type = agent_cfg.get('type', 'unknown')
        activity_logger.log(user_id, "AGENT_CALL_START", f"agent={agent_name},type={agent_type},query_len={len(query)}")
        
        processing_msg = await message.reply(info_agent_processing(agent_name), parse_mode="MarkdownV2")
        
        try:
            # Подготовка контекста
            context = {
                'codebase_manager': self.codebase_manager,
                'file_manager': self.file_manager,
                'ai_interface': self.ai_interface,
                'user_manager': self.user_manager,
                'message': message
            }
            
            # Всегда передаем upload_handler для всех агентов
            if upload_handler:
                context['upload_handler'] = upload_handler
            
            # Добавляем контекст файла если есть (для обратной совместимости)
            if chat_handler and hasattr(chat_handler, 'user_file_contexts') and user_id in chat_handler.user_file_contexts:
                context['last_file_content'] = chat_handler.user_file_contexts[user_id]
            
            # Вызов агента
            result = await agent.process(user_id, query, context)
            
            # Обработка результата
            if isinstance(result, tuple) and len(result) >= 2:
                success = result[0]
                response = result[1]
                archive_path = result[2] if len(result) > 2 else None
            else:
                success = False
                response = info_invalid_agent_response()
                archive_path = None
            
            duration = perf_counter() - t0
            activity_logger.log(user_id, "AGENT_CALL_END", f"agent={agent_name},type={agent_type},success={success},duration={duration:.2f}s,response_len={len(response) if isinstance(response,str) else 0}")
            
            await processing_msg.delete()
            
            if success:
                # Отправка архива если есть
                if archive_path and os.path.exists(archive_path):
                    await self._send_archive_result(message, archive_path, response)
                    return
                
                # Отправка результата в файле для больших ответов
                if len(response) > 4000:
                    await self._send_file_result(message, agent_name, query, response)
                else:
                    await self._send_text_result(message, response)
            else:
                # Ошибка
                await self._send_text_result(message, response)
                
        except Exception as e:
            duration = perf_counter() - t0
            activity_logger.log(user_id, "AGENT_CALL_ERROR", f"agent={agent_name},type={agent_type},error={str(e)},duration={duration:.2f}s")
            logger.error(f"Ошибка при вызове агента {agent_name}: {e}", exc_info=True)
            try:
                await processing_msg.delete()
            except:
                pass
            
            error_text = f"⚠ Ошибка при выполнении агента: {str(e)}"
            try:
                await message.reply(escape_markdown_v2(error_text), parse_mode="MarkdownV2")
            except:
                await message.reply(error_text, parse_mode=None)
    
    async def _send_archive_result(self, message: types.Message, archive_path: str, response: str):
        """Отправка архива с результатами"""
        try:
            archive_name = os.path.basename(archive_path)
            document = FSInputFile(archive_path, filename=archive_name)
            
            await message.reply_document(
                document,
                caption=response if len(response) <= 1024 else response[:1021] + "...",
                parse_mode=None
            )
            
            # Удаляем временный архив после отправки
            try:
                await asyncio.sleep(2)
                os.remove(archive_path)
                temp_dir = os.path.dirname(archive_path)
                if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                    os.rmdir(temp_dir)
            except Exception as e:
                logger.debug(f"Не удалось удалить временный архив: {e}")
        
        except Exception as e:
            logger.error(f"Ошибка отправки архива: {e}")
    
    async def _send_file_result(self, message: types.Message, agent_name: str, query: str, response: str):
        """Отправка результата в файле"""
        file_content = f"# Ответ агента @{agent_name}\n\n"
        file_content += f"**Запрос:** {query}\n\n"
        file_content += f"**Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        file_content += "---\n\n"
        clean_response = response.replace("\\", "")
        file_content += clean_response
        
        file_bytes = file_content.encode('utf-8')
        input_file = BufferedInputFile(
            file=file_bytes,
            filename=f"response_{agent_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        
        await message.reply_document(
            document=input_file,
            caption=info_agent_result_too_large(agent_name),
            parse_mode="MarkdownV2"
        )
    
    async def _send_text_result(self, message: types.Message, response: str):
        """Отправка текстового результата"""
        try:
            await message.reply(response, parse_mode="MarkdownV2")
        except:
            # Если ошибка форматирования, отправляем без форматирования
            safe_response = escape_markdown_v2(response.replace("\\", ""))
            try:
                await message.reply(safe_response, parse_mode="MarkdownV2")
            except:
                await message.reply(response.replace("\\", ""), parse_mode=None)
    
    async def send_agent_config(self, message: types.Message, user_id: str, agent_name: str, system_agents: Dict):
        """Отправка конфигурации агента пользователю"""
        config = await self.config_manager.get_agent_config(user_id, agent_name, system_agents)
        
        if not config:
            await message.reply(info_agent_not_found(agent_name), parse_mode="MarkdownV2")
            return
        
        # Создаем JSON файл
        config_json = json.dumps(config, ensure_ascii=False, indent=2)
        file_bytes = config_json.encode('utf-8')
        
        input_file = BufferedInputFile(
            file=file_bytes,
            filename=f"agent_{agent_name}_config.json"
        )
        
        await message.reply_document(
            document=input_file,
            caption=info_agent_config_caption(agent_name),
            parse_mode="MarkdownV2"
        )