# code/agents/nethack_agent.py

import os
import logging
import asyncio
from typing import Dict, Any, Tuple, Optional
from datetime import datetime
import sys
import json

from .async_qa import AsyncDocumentQA

logger = logging.getLogger(__name__)


class NethackAgent:
    """Агент для ответов на вопросы на основе собранных данных из сети"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.name = "nethack"
        
        # Если передан config, используем его, иначе загружаем дефолтный
        if config:
            self.config = config
        else:
            self.config = self._load_default_config()
            
        self.qa_system = None
        self._init_qa_system()
        
    def _load_default_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации агента"""
        config_path = os.path.join(os.path.dirname(__file__), "configs", "nethack_default.json")
        
        default_config = {
            "name": "hero",
            "description": "Интеллектуальный поиск ответов в документах из сети",
            "type": "nethack",
            "access": "public",
            
            "qa_config_path": "./NETHACK/acmecorp/config_aifaq.json",
            "access_config_path": "./NETHACK/acmecorp/doc_access.json",
            
            "response_settings": {
                "verbose": False,
                "show_sources": True,
                "max_answer_length": 20000,
                "fallback_message": "К сожалению, не могу найти информацию по вашему запросу в доступных документах."
            },
            
            "cache_settings": {
                "enabled": True,
                "ttl_seconds": 600
            }
        }
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    # Обновляем дефолтный конфиг загруженными значениями
                    for key, value in loaded_config.items():
                        default_config[key] = value
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига Nethack агента: {e}")
                
        return default_config
        
    def _init_qa_system(self):
        """Инициализация системы вопрос-ответ"""
        try:
            # Берем пути из конфигурации агента
            qa_config_path = self.config.get("qa_config_path")
            access_config_path = self.config.get("access_config_path")
            
            if not qa_config_path or not access_config_path:
                logger.error("Не заданы пути к конфигурационным файлам QA системы")
                return
            
            # Проверяем существование файлов конфигурации
            if not os.path.exists(qa_config_path):
                logger.warning(f"Файл конфигурации QA не найден: {qa_config_path}")
                # Создаем директорию если её нет
                os.makedirs(os.path.dirname(qa_config_path), exist_ok=True)
                
            if not os.path.exists(access_config_path):
                logger.warning(f"Файл конфигурации доступа не найден: {access_config_path}")
                # Создаем директорию если её нет
                os.makedirs(os.path.dirname(access_config_path), exist_ok=True)
            
            # Передаем пути из конфига агента в QA систему
            self.qa_system = AsyncDocumentQA(
                config_path=qa_config_path,
                access_config_path=access_config_path
            )
            
            logger.info(f"Система вопрос-ответ инициализирована с путями:")
            logger.info(f"  - QA config: {qa_config_path}")
            logger.info(f"  - Access config: {access_config_path}")
            
        except Exception as e:
            logger.error(f"Ошибка инициализации QA системы: {e}", exc_info=True)
            self.qa_system = None
            
    async def reload_access_config(self):
        """Перезагрузка конфигурации доступа к документам"""
        if self.qa_system:
            await self.qa_system.reload_access_config()
            logger.info("Конфигурация доступа перезагружена")
            
    def get_user_telegram_id(self, user_id: str) -> int:
        """Преобразование user_id в Telegram ID для проверки доступа"""
        try:
            # Предполагаем, что user_id это строка с Telegram ID
            return int(user_id)
        except (ValueError, TypeError):
            # Если не удается преобразовать, используем дефолтный ID
            # или можно вернуть 0 для публичного доступа
            return 0
            
    def format_answer_with_sources(self, answer: str, selected_files: list) -> str:
        """Форматирование ответа с указанием источников"""
        if not self.config.get("response_settings", {}).get("show_sources", True):
            return answer
            
        if selected_files:
            sources_text = "\n\n📚 *Источники:*\n"
            for i, file in enumerate(selected_files, 1):
                # Убираем расширение для красоты
                file_display = file.replace('.md', '').replace('.txt', '')
                sources_text += f"{i}. {file_display}\n"
            return answer + sources_text
        
        return answer
        
    async def process(
        self,
        user_id: str,
        query: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Обработка запроса пользователя через систему QA
        
        Args:
            user_id: ID пользователя
            query: Запрос пользователя
            context: Контекст выполнения
            
        Returns:
            Tuple[успех, ответ]
        """
        try:
            if not self.qa_system:
                # Пробуем переинициализировать систему
                self._init_qa_system()
                if not self.qa_system:
                    return False, "⚠️ Система поиска по документам временно недоступна"
            
            # Получаем Telegram ID для проверки доступа
            telegram_id = self.get_user_telegram_id(user_id)
            
            # Настройки из конфига
            response_settings = self.config.get("response_settings", {})
            verbose = response_settings.get("verbose", False)
            max_length = response_settings.get("max_answer_length", 4000)
            
            # Выполняем поиск и генерацию ответа
            logger.info(f"Nethack обрабатывает запрос от пользователя {user_id}: {query[:100]}...")
            
            # Сначала проверяем доступные документы
            available_docs = self.qa_system.get_user_documents(telegram_id)
            if not available_docs:
                return False, "📭 У вас нет доступа к документам в системе"
            
            logger.info(f"Доступно документов для пользователя {telegram_id}: {len(available_docs)}")
            
            # Основной процесс обработки вопроса
            answer = await self.qa_system.process_question(
                question=query,
                user_id=telegram_id,
                verbose=verbose
            )
            
            # Проверяем успешность ответа
            if not answer or "не найдено" in answer.lower():
                fallback = response_settings.get("fallback_message", 
                    "К сожалению, не могу найти информацию по вашему запросу")
                return False, fallback
            
            # Обрезаем слишком длинный ответ
            if len(answer) > max_length:
                answer = answer[:max_length-100] + "\n\n... *(ответ сокращен)*"
            
            formatted_answer = answer
            
            # Очистка кэша если нужно
            if self.config.get("cache_settings", {}).get("enabled", True):
                try:
                    await self.qa_system.cleanup_cache()
                except:
                    pass
            
            logger.info(f"Nethack успешно обработал запрос, длина ответа: {len(formatted_answer)}")
            return True, formatted_answer
            
        except asyncio.TimeoutError:
            logger.error("Таймаут при обработке запроса Nethack")
            return False, "⏱️ Превышено время ожидания ответа. Попробуйте упростить запрос."
            
        except Exception as e:
            logger.error(f"Ошибка в Nethack агенте: {e}", exc_info=True)
            return False, f"❌ Ошибка обработки: {str(e)}"
            
    def get_config(self) -> Dict[str, Any]:
        """Получение конфигурации агента"""
        return self.config.copy()
        
    def set_config(self, config: Dict[str, Any]):
        """Установка новой конфигурации"""
        
        # Сохраняем старые пути для сравнения
        old_qa_config = self.config.get("qa_config_path")
        old_access_config = self.config.get("access_config_path")
        
        # Обновляем конфигурацию
        self.config = config
        
        # Переинициализируем QA систему если изменились пути
        new_qa_config = config.get("qa_config_path")
        new_access_config = config.get("access_config_path")
        
        if old_qa_config != new_qa_config or old_access_config != new_access_config:
            logger.info("Переинициализация QA системы из-за изменения конфигурации")
            logger.info(f"  Старые пути: QA={old_qa_config}, Access={old_access_config}")
            logger.info(f"  Новые пути: QA={new_qa_config}, Access={new_access_config}")
            self._init_qa_system()
            
    def update_config(self, updates: Dict[str, Any]):
        """Частичное обновление конфигурации"""
        
        # Сохраняем старые пути для сравнения
        old_qa_config = self.config.get("qa_config_path")
        old_access_config = self.config.get("access_config_path")
        
        # Обновляем только переданные поля
        for key, value in updates.items():
            if isinstance(value, dict) and key in self.config and isinstance(self.config[key], dict):
                # Для вложенных словарей делаем рекурсивное обновление
                self.config[key].update(value)
            else:
                self.config[key] = value
        
        # Проверяем, изменились ли пути к конфигурациям
        new_qa_config = self.config.get("qa_config_path")
        new_access_config = self.config.get("access_config_path")
        
        if old_qa_config != new_qa_config or old_access_config != new_access_config:
            logger.info("Переинициализация QA системы из-за изменения путей конфигурации")
            self._init_qa_system()