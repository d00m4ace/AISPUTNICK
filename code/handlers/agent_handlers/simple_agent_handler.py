# code/handlers/agent_handlers/simple_agent_handler.py

import os
import re
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from aiogram import types, F
from aiogram.fsm.context import FSMContext
from utils.markdown_utils import escape_markdown_v2
from utils.info_utils import (
    info_no_access,
    info_system_agent_immutable,
    info_not_public_agent_owner,
    info_public_agent_saved,
    info_private_agent_saved,
    info_invalid_config_format,
    info_agent_name_not_determined,
    info_json_parse_error,
    info_agent_config_error
)

# Импорт агентов
from agents.rag_agent import RagAgent
from agents.chat_agent import ChatAgent
from agents.filejob_agent import FilejobAgent
from agents.zip_agent import ZipAgent

# Импорт обработчиков
from .base_handler import BaseAgentHandler
from .chat_handler import ChatAgentHandler, ChatStates
from .filejob_handler import FilejobAgentHandler
from .macro_handler import MacroCommandHandler
from .commands_handler import CommandsHandler
from handlers.macro_commands import MacroCommands

# Импорт новых модулей
from .agent_config_manager import AgentConfigManager
from .agent_processor import AgentProcessor
from .message_router import MessageRouter
from .nethack_manager import NethackManager
from .session_manager import SessionManager

logger = logging.getLogger(__name__)

class SimpleAgentHandler(BaseAgentHandler):
    """Упрощенный обработчик для вызова агентов через @имя_агента"""
    
    def __init__(self, bot, user_manager, codebase_manager, file_manager, ai_interface):
        super().__init__(bot, user_manager, codebase_manager, file_manager, ai_interface)
        
        # Инициализация системных агентов
        self.system_agents = {}
        self._init_system_agents()
        
        # Инициализация менеджеров
        self.config_manager = AgentConfigManager(codebase_manager, file_manager, ai_interface, user_manager)
        self.agent_processor = AgentProcessor(bot, self.config_manager, codebase_manager, file_manager, ai_interface, user_manager)
        self.nethack_manager = NethackManager(self)
        self.session_manager = SessionManager(self)
        self.message_router = MessageRouter(self)
        
        # Инициализация макро-команд
        self.macro_commands = MacroCommands()
        
        # Инициализация upload_handler для обработки файлов
        from handlers.file_operations.upload_handler import FileUploadHandler
        self.upload_handler = FileUploadHandler(
            bot=bot,
            user_manager=user_manager,
            codebase_manager=codebase_manager,
            file_manager=file_manager
        )
        
        # Инициализация обработчиков
        self.chat_handler = ChatAgentHandler(self)
        self.filejob_handler = FilejobAgentHandler(self)
        self.macro_handler = MacroCommandHandler(self)
        self.commands_handler = CommandsHandler(self)
        
        # Связываем upload_handler с agent_handler
        self.upload_handler.set_agent_handler(self)
        
        # Загрузка сохраненных агентов
        self.config_manager.load_saved_agents()
        
        # Переносим хранилища в config_manager для обратной совместимости
        self.user_agents = self.config_manager.user_agents
        self.public_agents = self.config_manager.public_agents
    
    def _init_system_agents(self):
        """Инициализация системных агентов"""
        # RAG агент
        from agents.rag_singleton import get_rag_manager
        rag_agent = RagAgent()
        rag_agent.set_rag_manager(get_rag_manager())
        self.system_agents['rag'] = rag_agent
        
        # Chat агент
        chat_agent = ChatAgent()
        self.system_agents['chat'] = chat_agent
        
        # Filejob агент
        filejob_agent = FilejobAgent()
        self.system_agents['filejob'] = filejob_agent
        
        # ZIP АГЕНТ
        zip_agent = ZipAgent()
        self.system_agents['zip'] = zip_agent
        
        # Upload агент
        from agents.upload_agent import UploadAgent
        upload_agent = UploadAgent()
        self.system_agents['upload'] = upload_agent
        
        logger.info(f"Инициализировано системных агентов: {len(self.system_agents)}")
    
    def save_md_file_for_macros(self, user_id: str, filename: str, content: str, original_filename: str = None):
        """Сохранить файл для последующего использования макро-командами"""
        # Поддерживаем не только .md, но и любые текстовые файлы
        from config import Config
        
        is_text_file = Config.is_text_file(filename) if hasattr(Config, 'is_text_file') else False
        is_markdown = filename.endswith('.md') or filename.endswith('.markdown')
        is_text_doc = filename.endswith('.txt') or filename.endswith('.text')
        
        if is_text_file or is_markdown or is_text_doc:
            # Определяем тип файла для лучшего контекста
            file_type = 'markdown'
            if not is_markdown:
                ext = os.path.splitext(filename.lower())[1]
                if ext in ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.cs', '.go', '.rs', '.h', '.hpp']:
                    file_type = 'code'
                elif ext in ['.json', '.xml', '.yaml', '.yml', '.toml', '.ini', '.conf']:
                    file_type = 'config'
                elif ext in ['.html', '.htm', '.css', '.scss']:
                    file_type = 'web'
                elif ext in ['.sql', '.psql']:
                    file_type = 'sql'
                else:
                    file_type = 'text'
            
            self.macro_handler.last_md_files[user_id] = {
                'filename': filename,
                'content': content if isinstance(content, str) else content.decode('utf-8'),
                'timestamp': datetime.now(),
                'original_filename': original_filename or filename,
                'file_type': file_type
            }
            logger.info(f"Сохранен файл ({file_type}) для макро: {filename} для пользователя {user_id}")
    
    def get_priority_macro_commands(self, limit=5):
        """Получить приоритетные макро-команды для отображения в справке"""
        # Определяем приоритетные категории команд
        priority_categories = {
            'analysis': ['sum', 'analyze', 'explain'],
            'translation': ['translate', 'translate_ru'],
            'extraction': ['keywords', 'entities', 'tasks'],
            'code': ['code', 'refactor', 'tests'],
            'structure': ['outline', 'questions']
        }
        
        result = []
        all_commands = self.macro_commands.get_all_commands()
        
        # Сначала добавляем по одной команде из каждой категории
        for category, cmd_list in priority_categories.items():
            for cmd in cmd_list:
                if cmd in all_commands and len(result) < limit:
                    # Сокращаем описание для справки
                    description = all_commands[cmd]['description']
                    # Берем только первую часть до запятой или точки
                    short_desc = description.split('.')[0].split(',')[0]
                    result.append((cmd, short_desc))
                    break
        
        # Если нужно больше команд, добавляем остальные
        if len(result) < limit:
            for cmd_name, cmd_info in all_commands.items():
                if not any(cmd_name == r[0] for r in result):
                    short_desc = cmd_info['description'].split('.')[0].split(',')[0]
                    result.append((cmd_name, short_desc))
                    if len(result) >= limit:
                        break
        
        return result
    
    def register_handlers(self, dp):
        """Регистрация обработчиков"""
        # Команды справки по агентам
        dp.message.register(self.commands_handler.cmd_agents, F.text == "/agents")
        dp.message.register(self.commands_handler.cmd_agents_pub, F.text == "/agents_pub")
        dp.message.register(self.commands_handler.cmd_agents_user, F.text == "/agents_user")
        
        # Универсальные команды управления агентами
        dp.message.register(self.commands_handler.cmd_agent_stop, F.text == "/stop")
        dp.message.register(self.commands_handler.cmd_agent_status, F.text == "/agent_status")
        
        # Обработчик отмены задачи
        dp.callback_query.register(self.filejob_handler.handle_cancel_job, F.data.startswith("cancel_job_"))
        
        # Новые команды для истории
        dp.message.register(self.commands_handler.cmd_clear_history, F.text == "/clear_history")
        dp.message.register(self.commands_handler.cmd_export_history, F.text == "/export_history")
        dp.message.register(self.commands_handler.cmd_history_info, F.text == "/history_info")
        
        # ВАЖНО: Сначала обрабатываем вызовы агентов через @ (высший приоритет для @)
        dp.message.register(self.message_router.handle_agent_call, F.text.regexp(r'^@\w+'))
        
        # Затем обработчик активного чата (для обычных сообщений без @)
        dp.message.register(self.message_router.handle_chat_message, ChatStates.active_chat)
        
        # Обработка документов в активном чате
        dp.message.register(self.message_router.handle_chat_document, ChatStates.active_chat, F.document)
        
        # Обработчик простых текстовых сообщений
        dp.message.register(self.message_router.handle_text_message, F.text & ~F.text.startswith('/') & ~F.text.startswith('@'))
        
        # Обработка загрузки конфигурации агента
        dp.message.register(self.handle_agent_config_upload, F.document)
    
    async def handle_document_for_active_agent(self, message: types.Message, state: FSMContext) -> bool:
        """
        Универсальный обработчик документов для активных агентов
        Возвращает True если документ обработан, False если нужна стандартная обработка
        """
        user_id = str(message.from_user.id)
        
        # Проверяем активный чат
        if user_id in self.chat_handler.active_chat_sessions:
            session = self.chat_handler.active_chat_sessions[user_id]
            agent_name = session.get('agent_name', 'chat')
            
            # Получаем агент
            agent = await self._get_agent_instance(user_id, agent_name)
            if agent and hasattr(agent, 'handle_document'):
                # Агент сам решает, что делать с документом
                await agent.handle_document(message, state, self)
                return True
        
        # Проверяем последнее использование RAG агента
        if hasattr(self.agent_processor, '_last_agent_used') and self.agent_processor._last_agent_used.get(user_id) == 'rag':
            last_time = self.agent_processor._last_agent_used_time.get(user_id)
            if last_time and (datetime.now() - last_time).total_seconds() < 300:
                agent = self.system_agents.get('rag')
                if agent and hasattr(agent, 'handle_document'):
                    await agent.handle_document(message, state, self)
                    return True
        
        # Проверка для ZIP агента
        if hasattr(self.agent_processor, '_last_agent_used') and self.agent_processor._last_agent_used.get(user_id) == 'zip':
            last_time = self.agent_processor._last_agent_used_time.get(user_id)
            if last_time and (datetime.now() - last_time).total_seconds() < 300:
                if message.document:
                    filename = message.document.file_name.lower() if message.document.file_name else ""
                    if filename.endswith('.zip') or filename.endswith('.7z'):
                        agent = self.system_agents.get('zip')
                        if agent and hasattr(agent, 'handle_document'):
                            await agent.handle_document(message, state, self)
                            return True
                    else:
                        from utils.info_utils import info_zip_agent_expects_archive
                        await message.reply(info_zip_agent_expects_archive(), parse_mode="MarkdownV2")
                        return True
        
        # Проверка для UPLOAD агента
        if hasattr(self.agent_processor, '_last_agent_used') and self.agent_processor._last_agent_used.get(user_id) == 'upload':
            last_time = self.agent_processor._last_agent_used_time.get(user_id)
            if last_time and (datetime.now() - last_time).total_seconds() < 300:
                from utils.info_utils import info_upload_agent_expects_url
                await message.reply(info_upload_agent_expects_url(), parse_mode="MarkdownV2")
                return True
        
        # Проверяем активные filejob задачи
        if hasattr(self, 'filejob_handler') and self.filejob_handler.has_active_jobs(user_id):
            from utils.info_utils import info_active_file_processing
            await message.reply(info_active_file_processing(), parse_mode="MarkdownV2")
            return True
        
        return False  # Документ не обработан активным агентом
    
    async def handle_agent_config_upload(self, message: types.Message):
        """Обработка загрузки конфигурации агента"""
        user_id = str(message.from_user.id)
        
        if not message.document or not message.document.file_name.endswith('.json'):
            return  # Не JSON файл, пропускаем
        
        # Проверяем имя файла на паттерн agent_*.json
        if not message.document.file_name.startswith('agent_'):
            return
        
        if not await self.user_manager.is_active(user_id):
            await message.reply(info_no_access())
            return
        
        try:
            # Загружаем файл
            file = await self.bot.get_file(message.document.file_id)
            file_data = await self.bot.download_file(file.file_path)
            
            if hasattr(file_data, 'getvalue'):
                file_bytes = file_data.getvalue()
            else:
                file_bytes = file_data
            
            # Парсим JSON
            config = json.loads(file_bytes.decode('utf-8'))
            
            # Валидация конфигурации
            if not all(key in config for key in ['name', 'description']):
                await message.reply(info_invalid_config_format(), parse_mode="MarkdownV2")
                return
            
            # Извлекаем имя агента
            agent_name = config.get('name', '').lower()
            if not agent_name:
                # Пытаемся извлечь из имени файла
                match = re.match(r'agent_(\w+)_config\.json', message.document.file_name)
                if match:
                    agent_name = match.group(1).lower()
                else:
                    await message.reply(info_agent_name_not_determined(), parse_mode="MarkdownV2")
                    return
            
            # Проверяем права на изменение
            if agent_name in self.system_agents:
                await message.reply(info_system_agent_immutable(agent_name), parse_mode="MarkdownV2")
                return
            
            if agent_name in self.public_agents:
                if self.public_agents[agent_name]['owner_id'] != user_id:
                    await message.reply(info_not_public_agent_owner(agent_name), parse_mode="MarkdownV2")
                    return
            
            # Определяем тип агента из конфига
            access_type = config.get('access', 'private')
            agent_type = config.get('type', 'unknown')
            
            # Добавляем эмодзи к описанию для чат агентов
            type_indicator = " 💬" if agent_type == 'chat' else ""
            
            if access_type == 'public':
                # Сохраняем как публичного
                self.public_agents[agent_name] = {
                    'config': config,
                    'owner_id': user_id
                }
                
                # Инвалидируем кэш
                self.config_manager.invalidate_agent_cache(agent_name, user_id=None)
                
                await self.config_manager.save_public_agents()
                await message.reply(info_public_agent_saved(agent_name, type_indicator), parse_mode="MarkdownV2")
            else:
                # Сохраняем как личного
                if user_id not in self.user_agents:
                    self.user_agents[user_id] = {}
                
                self.user_agents[user_id][agent_name] = config
                
                # Инвалидируем кэш
                self.config_manager.invalidate_agent_cache(agent_name, user_id=user_id)
                
                await self.config_manager.save_user_agents(user_id)
                await message.reply(info_private_agent_saved(agent_name, type_indicator), parse_mode="MarkdownV2")
                
        except json.JSONDecodeError:
            await message.reply(info_json_parse_error(), parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации агента: {e}", exc_info=True)
            await message.reply(info_agent_config_error(str(e)), parse_mode="MarkdownV2")
    
    async def _get_agent_instance(self, user_id: str, agent_name: str):
        """Получение экземпляра агента с кэшированием"""
        from agents.rag_singleton import get_rag_manager
        return await self.config_manager.get_cached_agent(
            user_id, agent_name, self.system_agents, get_rag_manager()
        )