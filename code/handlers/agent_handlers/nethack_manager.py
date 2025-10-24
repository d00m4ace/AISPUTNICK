# code/handlers/agent_handlers/nethack_manager.py

import logging
from datetime import datetime
from typing import Optional
from aiogram import types

logger = logging.getLogger(__name__)

class NethackManager:
    """Управление nethack сессиями"""
    
    def __init__(self, handler):
        self.handler = handler
        
        # Отслеживание последнего использованного nethack агента
        self._last_nethack_agent = {}  # {user_id: agent_name}
        self._last_nethack_time = {}   # {user_id: datetime}
        self._active_nethack_sessions = {}  # {user_id: {'agent_name': str, 'started_at': datetime}}
    
    def has_active_session(self, user_id: str) -> bool:
        """Проверяет наличие активной nethack сессии"""
        if user_id not in self._active_nethack_sessions:
            return False
        
        # Проверяем таймаут сессии (24 часа)
        session = self._active_nethack_sessions[user_id]
        elapsed = (datetime.now() - session['started_at']).total_seconds()
        
        if elapsed > 3600*60:  # 24 часа
            del self._active_nethack_sessions[user_id]
            return False
        
        return True
    
    def get_active_agent(self, user_id: str) -> Optional[str]:
        """Получает имя активного nethack агента"""
        if self.has_active_session(user_id):
            return self._active_nethack_sessions[user_id]['agent_name']
        return None
    
    def activate_session(self, user_id: str, agent_name: str):
        """Активирует nethack сессию"""
        self._last_nethack_agent[user_id] = agent_name
        self._last_nethack_time[user_id] = datetime.now()
        self._active_nethack_sessions[user_id] = {
            'agent_name': agent_name,
            'started_at': datetime.now()
        }
        logger.info(f"Активирована nethack сессия с агентом {agent_name} для пользователя {user_id}")
    
    def deactivate_session(self, user_id: str):
        """Деактивирует nethack сессию"""
        if user_id in self._active_nethack_sessions:
            del self._active_nethack_sessions[user_id]
            logger.info(f"Деактивирована nethack сессия для пользователя {user_id}")
    
    async def handle_continuation(self, message: types.Message):
        """Обработка продолжения запросов к активному nethack агенту"""
        user_id = str(message.from_user.id)
        
        if not await self.handler.user_manager.is_active(user_id):
            return False
        
        # Проверяем наличие активной nethack сессии
        if not self.has_active_session(user_id):
            return False
        
        agent_name = self.get_active_agent(user_id)
        if not agent_name:
            return False
        
        # Получаем агент
        agent = await self.handler._get_agent_instance(user_id, agent_name)
        if not agent:
            # Сессия устарела, очищаем
            del self._active_nethack_sessions[user_id]
            return False
        
        # Обновляем время последнего использования
        self._active_nethack_sessions[user_id]['started_at'] = datetime.now()
        
        # Обрабатываем запрос через nethack агент
        logger.info(f"Продолжение nethack сессии {agent_name} для пользователя {user_id}")
        await self.handler.agent_processor.process_regular_agent(
            message, user_id, agent_name, message.text, agent,
            self.handler.upload_handler, self.handler.chat_handler
        )
        
        return True