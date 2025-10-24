# code/agents/rag_manager.py
"""
Менеджер для управления индексацией RAG
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import asyncio

from .lightweight_rag import LightweightRAG
from config import Config

logger = logging.getLogger(__name__)


class RAGManager:
    """Менеджер для управления индексацией RAG"""
    
    def __init__(self, codebase_manager=None):
        self.rag_indexer = LightweightRAG()
        self._lock = asyncio.Lock()
        self.codebase_manager = codebase_manager  # НОВОЕ
        
        logger.info(f"RAGManager инициализирован с поддержкой текстовых форматов из Config")
    
    def _is_text_file(self, filename: str) -> bool:
        """
        Проверка, является ли файл текстовым
        Использует логику из Config
        """
        return Config.is_text_file(filename)
    
    def _get_text_files(self, files_dir: str) -> List[str]:
        """Получение списка текстовых файлов в директории"""
        text_files = []
        if os.path.exists(files_dir):
            for filename in os.listdir(files_dir):
                file_path = os.path.join(files_dir, filename)
                if os.path.isfile(file_path) and self._is_text_file(filename):
                    text_files.append(filename)
        return text_files
    
    async def _get_rag_settings(self, user_id: str, codebase_id: str) -> Dict[str, int]:
        """Получает настройки RAG с учетом публичных баз"""
    
        # Для публичных баз получаем настройки владельца
        owner_user_id, owner_codebase_id, _ = self._get_owner_params(user_id, codebase_id)
    
        config = await self.codebase_manager.get_codebase_config(owner_user_id, owner_codebase_id)
    
        if not config:
            return {"chunk_size": 4096, "overlap_size": 256}
    
        rag_settings = config.get("rag_settings", {})
        return {
            "chunk_size": rag_settings.get("chunk_size", 4096),
            "overlap_size": rag_settings.get("overlap_size", 256)
        }

    async def update_incremental(
        self,
        user_id: str,
        codebase_id: str,
        files_dir: str,
        progress_callback=None
    ) -> Tuple[bool, str]:
        """
        1. Инкрементальное обновление - только измененные/новые файлы
        """
        async with self._lock:
            try:
                logger.info(f"Инкрементальное обновление индекса для {user_id}/{codebase_id}")

                # Получаем параметры из конфигурации
                config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
                if not config:
                    return False, "Конфигурация кодовой базы не найдена"
            
                rag_params = await self._get_rag_settings(user_id, codebase_id)
                chunk_size = rag_params["chunk_size"]
                overlap_size = rag_params["overlap_size"]
                
                # Фильтруем только текстовые файлы
                text_files = self._get_text_files(files_dir)
                logger.info(f"Найдено {len(text_files)} текстовых файлов для индексации")
                
                # Логируем поддерживаемые расширения для отладки
                supported_extensions = Config.get_text_extensions()
                logger.debug(f"Поддерживаемые текстовые расширения: {supported_extensions}")
                
                # Вызываем стандартную индексацию без force_reindex
                # Она автоматически обновит только измененные файлы
                success, msg = await self.rag_indexer.index_codebase(
                    user_id=user_id,
                    codebase_id=codebase_id,
                    files_dir=files_dir,
                    force_reindex=False,
                    progress_callback=progress_callback,
                    chunk_size=chunk_size,
                    overlap_size=overlap_size
                )
                
                if success:
                    logger.debug(f"Инкрементальное обновление успешно: {msg}")
                else:
                    logger.error(f"Ошибка инкрементального обновления: {msg}")
                
                return success, msg
                
            except Exception as e:
                logger.error(f"Ошибка при инкрементальном обновлении: {e}", exc_info=True)
                return False, str(e)
    
    async def reindex_full(
        self,
        user_id: str,
        codebase_id: str,
        files_dir: str,
        progress_callback=None
    ) -> Tuple[bool, str]:
        """
        2. Полная переиндексация с очисткой старого индекса
        """
        async with self._lock:
            try:
                logger.info(f"Полная переиндексация для {user_id}/{codebase_id}")
                
                # Очищаем кэш для этой кодовой базы
                await self.rag_indexer.clear_cache(user_id, codebase_id)

                # Получаем параметры из конфигурации
                config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
                if not config:
                    return False, "Конфигурация кодовой базы не найдена"
            
                rag_params = await self._get_rag_settings(user_id, codebase_id)
                chunk_size = rag_params["chunk_size"]
                overlap_size = rag_params["overlap_size"]
                
                # Фильтруем только текстовые файлы
                text_files = self._get_text_files(files_dir)
                logger.info(f"Найдено {len(text_files)} текстовых файлов для полной переиндексации")
                
                # Вызываем индексацию с force_reindex=True
                success, msg = await self.rag_indexer.index_codebase(
                    user_id=user_id,
                    codebase_id=codebase_id,
                    files_dir=files_dir,
                    force_reindex=True,
                    progress_callback=progress_callback,
                    chunk_size=chunk_size,
                    overlap_size=overlap_size
                )
                
                if success:
                    logger.info(f"Полная переиндексация успешна: {msg}")
                else:
                    logger.error(f"Ошибка полной переиндексации: {msg}")
                
                return success, msg
                
            except Exception as e:
                logger.error(f"Ошибка при полной переиндексации: {e}", exc_info=True)
                return False, str(e)
    
    async def remove_file_from_index(
        self,
        user_id: str,
        codebase_id: str,
        filename: str
    ) -> Tuple[bool, str]:
        """
        3. Удаление файла из индекса
        """
        async with self._lock:
            try:
                logger.info(f"Удаление файла {filename} из индекса {user_id}/{codebase_id}")
                
                # Получаем информацию об индексе
                index_info = await self.rag_indexer.get_index_info(user_id, codebase_id)
                
                if not index_info:
                    return False, "Индекс не найден"
                
                if filename not in index_info.get('files', []):
                    return True, f"Файл {filename} не найден в индексе"
                
                # Для удаления файла нужно переиндексировать без этого файла
                # Это будет обработано автоматически при следующем update_incremental
                # так как файла уже не будет в директории
                
                # Очищаем кэш чтобы при следующем поиске загрузился обновленный индекс
                await self.rag_indexer.clear_cache(user_id, codebase_id)
                
                logger.info(f"Файл {filename} помечен для удаления из индекса")
                return True, f"Файл {filename} будет удален из индекса при следующем обновлении"
                
            except Exception as e:
                logger.error(f"Ошибка при удалении файла из индекса: {e}", exc_info=True)
                return False, str(e)
       

    async def check_index_status(
        self,
        user_id: str,
        codebase_id: str,
        files_dir: str
    ) -> Dict[str, Any]:
        """
        Проверка статуса индекса и необходимости обновления
        Для публичных баз проверяет индекс владельца
        """
        try:
            # Получаем параметры владельца для публичных баз
            owner_user_id, owner_codebase_id, folder_name = self._get_owner_params(user_id, codebase_id)
        
            # Если это публичная база, используем директорию владельца
            if owner_user_id != user_id and folder_name:
                users_dir = Config.USERS_DIR
                owner_codebase_dir = os.path.join(users_dir, owner_user_id, "codebases", folder_name)
                files_dir = os.path.join(owner_codebase_dir, "files")
        
            index_info = await self.rag_indexer.get_index_info(owner_user_id, owner_codebase_id)
        
            if not index_info:
                return {
                    "exists": False,
                    "needs_update": True,
                    "reason": "Индекс не существует",
                    "is_public_ref": owner_user_id != user_id
                }
        
            # Получаем текущие файлы
            current_files = set(self._get_text_files(files_dir))
            indexed_files = set(index_info.get('files', []))
        
            # Проверяем различия
            new_files = current_files - indexed_files
            deleted_files = indexed_files - current_files
        
            if new_files or deleted_files:
                return {
                    "exists": True,
                    "needs_update": True,
                    "reason": f"Найдено изменений: {len(new_files)} новых, {len(deleted_files)} удаленных файлов",
                    "new_files": list(new_files),
                    "deleted_files": list(deleted_files),
                    "indexed_files_count": len(indexed_files),
                    "current_files_count": len(current_files),
                    "last_updated": index_info.get('last_updated'),
                    "is_public_ref": owner_user_id != user_id
                }
        
            return {
                "exists": True,
                "needs_update": False,
                "reason": "Индекс актуален",
                "indexed_files_count": len(indexed_files),
                "last_updated": index_info.get('last_updated'),
                "is_public_ref": owner_user_id != user_id
            }
        
        except Exception as e:
            logger.error(f"Ошибка проверки статуса индекса: {e}", exc_info=True)
            return {
                "exists": False,
                "needs_update": True,
                "reason": f"Ошибка проверки: {str(e)}"
            }

    async def search(
        self,
        user_id: str,
        codebase_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Поиск по индексу (для публичных баз используется индекс владельца)"""
        # Получаем параметры владельца для публичных баз
        owner_user_id, owner_codebase_id, _ = self._get_owner_params(user_id, codebase_id)
    
        logger.debug(f"RAG поиск: user={user_id}, codebase={codebase_id} -> owner={owner_user_id}, owner_cb={owner_codebase_id}")
    
        # Используем индекс владельца для поиска
        return await self.rag_indexer.search(owner_user_id, owner_codebase_id, query, top_k)

    async def get_index_info(self, user_id: str, codebase_id: str) -> Optional[Dict[str, Any]]:
        """Получение информации об индексе (для публичных баз - индекс владельца)"""
        # Получаем параметры владельца для публичных баз
        owner_user_id, owner_codebase_id, _ = self._get_owner_params(user_id, codebase_id)
    
        return await self.rag_indexer.get_index_info(owner_user_id, owner_codebase_id)

    async def get_supported_formats(self) -> List[str]:
        """
        Получение списка поддерживаемых текстовых форматов
        """
        return sorted(list(Config.get_text_extensions()))

    def _get_owner_params(self, user_id: str, codebase_id: str) -> Tuple[str, str, str]:
        """
        Получает параметры владельца для публичных баз
        Возвращает (owner_user_id, owner_codebase_id, folder_name)
        """
        # Если это не публичная ссылка, возвращаем исходные параметры
        if not codebase_id.startswith("pub_"):
            return user_id, codebase_id, None
    
        try:
            users_dir = Config.USERS_DIR
        
            # Читаем информацию о кодовой базе пользователя
            user_dir = os.path.join(users_dir, user_id)
            codebases_file = os.path.join(user_dir, "codebases.json")
        
            if not os.path.exists(codebases_file):
                logger.warning(f"Файл codebases.json не найден для пользователя {user_id}")
                return user_id, codebase_id, None
        
            with open(codebases_file, "r", encoding="utf-8") as f:
                user_codebases = json.load(f)
        
            cb_info = user_codebases.get("codebases", {}).get(codebase_id, {})
        
            if not cb_info.get("is_public_ref"):
                logger.warning(f"Кодовая база {codebase_id} не является публичной ссылкой")
                return user_id, codebase_id, None
        
            owner_id = cb_info.get("owner_id")
            public_id = cb_info.get("public_id")
        
            if not owner_id or not public_id:
                logger.warning(f"Отсутствуют owner_id или public_id для {codebase_id}")
                return user_id, codebase_id, None
        
            # Получаем реальный ID базы из реестра
            registry_file = os.path.join(users_dir, "public_codebases.json")
        
            if not os.path.exists(registry_file):
                logger.warning("Реестр публичных баз не найден")
                return user_id, codebase_id, None
        
            with open(registry_file, "r", encoding="utf-8") as f:
                registry = json.load(f)
        
            pub_info = registry.get(public_id)
        
            if not pub_info:
                logger.warning(f"Публичная база {public_id} не найдена в реестре")
                return user_id, codebase_id, None
        
            real_codebase_id = pub_info.get("codebase_id")
        
            if not real_codebase_id:
                logger.warning(f"Не найден codebase_id для публичной базы {public_id}")
                return user_id, codebase_id, None
        
            # Теперь читаем codebases.json владельца чтобы получить folder_name
            owner_dir = os.path.join(users_dir, owner_id)
            owner_codebases_file = os.path.join(owner_dir, "codebases.json")
        
            if not os.path.exists(owner_codebases_file):
                logger.warning(f"Файл codebases.json не найден для владельца {owner_id}")
                return owner_id, real_codebase_id, None
        
            with open(owner_codebases_file, "r", encoding="utf-8") as f:
                owner_codebases = json.load(f)
        
            owner_cb_info = owner_codebases.get("codebases", {}).get(real_codebase_id, {})
            folder_name = owner_cb_info.get("folder_name")
        
            if not folder_name:
                logger.warning(f"folder_name не найден для базы {real_codebase_id} владельца {owner_id}")
                return owner_id, real_codebase_id, None
        
            logger.debug(f"Mapped pub_{public_id} -> owner={owner_id}, codebase={real_codebase_id}, folder={folder_name}")
            return owner_id, real_codebase_id, folder_name
        
        except Exception as e:
            logger.error(f"Ошибка получения параметров владельца: {e}", exc_info=True)
            return user_id, codebase_id, None