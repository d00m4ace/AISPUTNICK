# code/handlers/agent_handlers/base_handler.py

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class BaseAgentHandler:
    """Базовый класс для обработчиков агентов"""
    
    def __init__(self, bot, user_manager, codebase_manager, file_manager, ai_interface):
        self.bot = bot
        self.user_manager = user_manager
        self.codebase_manager = codebase_manager
        self.file_manager = file_manager
        self.ai_interface = ai_interface
        
    def save_md_file_for_macros(self, user_id: str, filename: str, content: str, original_filename: str = None):
        """Сохранить файл для последующего использования макро-командами"""
        # Этот метод будет переопределен в главном handler
        pass