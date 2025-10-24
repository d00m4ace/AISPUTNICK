# code/agents/rag_singleton.py
"""
Глобальный экземпляр RAGManager
"""
import logging
from typing import Optional
from .rag_manager import RAGManager

logger = logging.getLogger(__name__)

# Создаем глобальную функцию для удобства
def get_rag_manager() -> RAGManager:
    """Получить глобальный экземпляр RAGManager"""
    if _global_rag_manager is None:
        logger.info(f"RAGManager не инициализирован!")

    return _global_rag_manager

# Опционально: создаем сразу экземпляр при импорте
_global_rag_manager = None

def init_rag_manager(codebase_manager:None):
    """Инициализация глобального RAGManager"""
    global _global_rag_manager
    if _global_rag_manager is None:
        _global_rag_manager = RAGManager(codebase_manager)
    return _global_rag_manager

# Экспортируем для прямого импорта
#rag_manager = init_rag_manager()