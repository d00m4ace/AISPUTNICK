# code/handlers/file_operations/base.py
"""
Базовый класс для файловых обработчиков
"""
from typing import Tuple


class BaseFileHandler:
    """Базовый класс для всех файловых обработчиков"""
    
    def __init__(self, bot, user_manager, codebase_manager, file_manager):
        self.bot = bot
        self.user_manager = user_manager
        self.codebase_manager = codebase_manager
        self.file_manager = file_manager