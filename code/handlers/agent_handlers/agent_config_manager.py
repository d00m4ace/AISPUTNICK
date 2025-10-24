# code/handlers/agent_handlers/agent_config_manager.py

import os
import json
import logging
from typing import Optional, Dict, Any
from agents.rag_agent import RagAgent
from agents.chat_agent import ChatAgent
from agents.filejob_agent import FilejobAgent

logger = logging.getLogger(__name__)

class AgentConfigManager:
    """Управление конфигурацией агентов"""
    
    def __init__(self, codebase_manager, file_manager, ai_interface, user_manager):
        self.codebase_manager = codebase_manager
        self.file_manager = file_manager
        self.ai_interface = ai_interface
        self.user_manager = user_manager
        
        # Хранилища
        self.user_agents = {}  # {user_id: {agent_name: config}}
        self.public_agents = {}  # {agent_name: {config, owner_id}}
        self._cached_user_agents = {}  # {user_id: {agent_name: agent_instance}}
        self._cached_public_agents = {}  # {agent_name: agent_instance}
        
    def load_saved_agents(self):
        """Загрузка сохраненных пользовательских и публичных агентов"""
        from config import Config
        agents_dir = os.path.join(Config.DATA_DIR, "agents")
        
        # Загрузка публичных агентов
        public_file = os.path.join(agents_dir, "public_agents.json")
        if os.path.exists(public_file):
            try:
                with open(public_file, 'r', encoding='utf-8') as f:
                    self.public_agents = json.load(f)
                logger.info(f"Загружено публичных агентов: {len(self.public_agents)}")
            except Exception as e:
                logger.error(f"Ошибка загрузки публичных агентов: {e}")
        
        # Загрузка пользовательских агентов
        users_dir = os.path.join(agents_dir, "users")
        if os.path.exists(users_dir):
            for user_file in os.listdir(users_dir):
                if user_file.endswith('.json'):
                    user_id = user_file.replace('.json', '')
                    try:
                        with open(os.path.join(users_dir, user_file), 'r', encoding='utf-8') as f:
                            self.user_agents[user_id] = json.load(f)
                        logger.info(f"Загружены агенты пользователя {user_id}: {len(self.user_agents[user_id])}")
                    except Exception as e:
                        logger.error(f"Ошибка загрузки агентов пользователя {user_id}: {e}")
    
    async def get_agent_config(self, user_id: str, agent_name: str, system_agents: Dict) -> Optional[Dict[str, Any]]:
        """Получение конфигурации агента"""
        # 1. Проверяем системные агенты
        if agent_name in system_agents:
            return system_agents[agent_name].get_config()
        
        # 2. Проверяем личные агенты пользователя
        if user_id in self.user_agents and agent_name in self.user_agents[user_id]:
            return self.user_agents[user_id][agent_name]
        
        # 3. Проверяем публичные агенты
        if agent_name in self.public_agents:
            return self.public_agents[agent_name]['config']
        
        return None
    
    async def create_agent_from_config(self, config: Dict[str, Any], rag_manager=None):
        """Создание агента из конфигурации"""
        agent_type = config.get('type', 'rag')
        
        if agent_type == 'chat':
            agent = ChatAgent()
            agent.set_config(config)
            return agent
        elif agent_type == 'rag':
            agent = RagAgent()
            agent.set_config(config)
            if rag_manager:
                agent.set_rag_manager(rag_manager)
            return agent
        elif agent_type == 'fileworker':
            agent = FilejobAgent()
            agent.set_config(config)
            return agent
        elif agent_type == 'nethack':
            from agents.nethack_agent import NethackAgent
            agent = NethackAgent()
            agent.set_config(config)
            return agent
        elif agent_type == 'downloader':
            from agents.upload_agent import UploadAgent
            agent = UploadAgent()
            agent.set_config(config)
            return agent
        else:
            return None
    
    def invalidate_agent_cache(self, agent_name: str, user_id: str = None):
        """Инвалидация кэша агента при обновлении конфигурации"""
        if user_id:
            if user_id in self._cached_user_agents and agent_name in self._cached_user_agents[user_id]:
                del self._cached_user_agents[user_id][agent_name]
                logger.info(f"Инвалидирован кэш личного агента {agent_name} для пользователя {user_id}")
        else:
            if agent_name in self._cached_public_agents:
                del self._cached_public_agents[agent_name]
                logger.info(f"Инвалидирован кэш публичного агента {agent_name}")
    
    async def save_public_agents(self):
        """Сохранение публичных агентов"""
        from config import Config
        agents_dir = os.path.join(Config.DATA_DIR, "agents")
        os.makedirs(agents_dir, exist_ok=True)
        
        public_file = os.path.join(agents_dir, "public_agents.json")
        with open(public_file, 'w', encoding='utf-8') as f:
            json.dump(self.public_agents, f, ensure_ascii=False, indent=2)
    
    async def save_user_agents(self, user_id: str):
        """Сохранение агентов пользователя"""
        from config import Config
        agents_dir = os.path.join(Config.DATA_DIR, "agents", "users")
        os.makedirs(agents_dir, exist_ok=True)
        
        user_file = os.path.join(agents_dir, f"{user_id}.json")
        with open(user_file, 'w', encoding='utf-8') as f:
            json.dump(self.user_agents[user_id], f, ensure_ascii=False, indent=2)
    
    async def get_cached_agent(self, user_id: str, agent_name: str, system_agents: Dict, rag_manager=None):
        """Получение экземпляра агента с кэшированием"""
        # 1. Проверяем системные агенты
        if agent_name in system_agents:
            return system_agents[agent_name]
        
        # 2. Проверяем кэш личных агентов пользователя
        if user_id in self._cached_user_agents and agent_name in self._cached_user_agents[user_id]:
            logger.debug(f"Использование кэшированного личного агента {agent_name} для пользователя {user_id}")
            return self._cached_user_agents[user_id][agent_name]
        
        # 3. Проверяем личные агенты пользователя (создаем если нужно)
        if user_id in self.user_agents and agent_name in self.user_agents[user_id]:
            config = self.user_agents[user_id][agent_name]
            agent = await self.create_agent_from_config(config, rag_manager)
            
            if agent:
                if user_id not in self._cached_user_agents:
                    self._cached_user_agents[user_id] = {}
                self._cached_user_agents[user_id][agent_name] = agent
                logger.info(f"Создан и закэширован личный агент {agent_name} для пользователя {user_id}")
                return agent
        
        # 4. Проверяем кэш публичных агентов
        if agent_name in self._cached_public_agents:
            logger.debug(f"Использование кэшированного публичного агента {agent_name}")
            return self._cached_public_agents[agent_name]
        
        # 5. Проверяем публичные агенты (создаем если нужно)
        if agent_name in self.public_agents:
            config = self.public_agents[agent_name]['config']
            agent = await self.create_agent_from_config(config, rag_manager)
            
            if agent:
                self._cached_public_agents[agent_name] = agent
                logger.info(f"Создан и закэширован публичный агент {agent_name}")
                return agent
        
        return None