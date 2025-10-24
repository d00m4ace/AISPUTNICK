# code/agents/async_qa.py

import asyncio
import aiofiles
import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field
import tiktoken
from openai import AsyncOpenAI

import xml.etree.ElementTree as ET
from xml.dom import minidom

from user_manager import UserManager

from user_activity_logger import activity_logger
import logging

logger = logging.getLogger(__name__)

# reasoning_effort: "minimal", "low", "medium", "high"
# verbosity: "low", "medium", "high"

select_reasoning_effort = "minimal" 
select_verbosity = "low"

answer_reasoning_effort = "minimal"
answer_verbosity = "medium"

@dataclass
class CachedDocument:
    """Кэшированный документ с метаданными"""
    content: str
    summary: str
    last_modified: float
    token_count: int
    file_hash: str


@dataclass
class CacheEntry:
    """Запись в кэше с блокировкой для обновления"""
    document: Optional[CachedDocument] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    updating: bool = False


class AsyncDocumentQA:
    """Асинхронная система вопрос-ответ для документов"""

    def _load_options(self) -> Dict[str, Any]:
        """
        Загружает опции из файла options_aifaq.json
    
        Returns:
            Словарь с опциями страниц или пустой словарь если файл не найден
        """
        try:
            options_path = self.base_dir / "options_aifaq.json"
        
            if not options_path.exists():
                logger.info(f"Файл options_aifaq.json не найден в {self.base_dir}, используются настройки по умолчанию")
                return {}
        
            with open(options_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"Загружено {len(data.get('pages', {}))} опций страниц из options_aifaq.json")
                return data
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга options_aifaq.json: {str(e)}")
            return {}
        except Exception as e:
            logger.error(f"Ошибка при загрузке options_aifaq.json: {str(e)}")
            return {}

    async def reload_options(self):
        """
        Перезагружает опции из options_aifaq.json
        Полезно если файл был обновлен во время работы программы
        """
        async with self.options_lock:
            self.options_cache = self._load_options()
            logger.info("options_aifaq.json перезагружен")

    def get_document_options(self, filename: str) -> Dict[str, Any]:
        """
        Получает опции для документа из кэшированных данных options_aifaq.json
    
        Args:
            filename: Имя файла без расширения
        
        Returns:
            Словарь с опциями документа или пустой словарь
        """
        try:
            # Получаем page_id для документа
            page_id = self.get_page_id_by_filename(filename)
        
            if not page_id:
                return {}
        
            # Ищем опции в кэше
            pages_options = self.options_cache.get("pages", {})
        
            if page_id in pages_options:
                return pages_options[page_id]
            
            return {}
        
        except Exception as e:
            logger.error(f"Ошибка при получении опций для {filename}: {str(e)}")
            return {}

    def get_document_metadata(self, filename: str) -> Dict[str, Any]:
        """
        Получает все метаданные документа из кэша с учетом опций
    
        Args:
            filename: Имя файла без расширения
        
        Returns:
            Словарь с метаданными документа или пустой словарь
        """
        try:
            if not self.local_pages_cache:
                return {}
        
            pages = self.local_pages_cache.get("pages", {})
        
            # Ищем документ
            metadata = {}
            for page_id, page_info in pages.items():
                file_name = page_info.get("file_name", "")
                file_name_without_ext = file_name.replace('.md', '').replace('.txt', '').replace('.markdown', '')
            
                if file_name_without_ext == filename:
                    metadata = page_info.copy()  # Копируем чтобы не менять оригинал
                    break
        
            # Пробуем по ключу если не нашли
            if not metadata and filename in pages:
                metadata = pages[filename].copy()
        
            # Добавляем опции из options_aifaq.json если они есть
            options = self.get_document_options(filename)
            if options:
                metadata.update(options)  # Опции перезаписывают значения из local_pages
            
            return metadata
        
        except Exception as e:
            logger.error(f"Ошибка при получении метаданных для {filename}: {str(e)}")
            return {}

    def __init__(self, config_path: str = "./config_qa.json", 
                 access_config_path: str = "./document_access.json"):
        self.config_path = config_path
        self.access_config_path = access_config_path
        self.config = self._load_config()
        self.access_config = self._load_access_config()
        
        self.user_manager = UserManager()

        # Асинхронный клиент OpenAI
        self.client = AsyncOpenAI(api_key=self.config["api_key"])
        
        # Пути
        self.base_dir = Path(self.config["base_dir"])
        self.source_dir = Path(self.config["source_dir"])
        self.summary_dir = Path(self.config["summary_dir"])
        
        # Кэш документов (общий для всех пользователей)
        self.document_cache: Dict[str, CacheEntry] = {}
        self.cache_lock = asyncio.Lock()

        # Загружаем опции из options_aifaq.json
        self.options_cache = self._load_options()
        self.options_lock = asyncio.Lock()  # Для потокобезопасности при перезагрузке
        
        # Загружаем local_pages.json один раз при инициализации
        self.local_pages_cache = self._load_local_pages()
        self.local_pages_lock = asyncio.Lock()  # Для потокобезопасности при перезагрузке
        
        # Загружаем промпты из отдельных файлов
        self.prompts_cache = self._load_prompts()
        self.prompts_lock = asyncio.Lock()  # Для потокобезопасности при перезагрузке
        
        # Encoding для подсчета токенов
        self.encoding = tiktoken.get_encoding("cl100k_base")
        
        # Семафор для ограничения параллельных запросов к API
        self.api_semaphore = asyncio.Semaphore(self.config.get("max_concurrent_api_calls", 5))
        
        # Путь к лог-файлу запросов
        self.queries_log_path = self.base_dir / "queries_log.jsonl"
        self.queries_log_lock = asyncio.Lock()
    
    def _load_local_pages(self) -> Dict[str, Any]:
        """
        Загружает данные из local_pages.json при инициализации
        
        Returns:
            Словарь с данными страниц или пустой словарь если файл не найден
        """
        try:
            local_pages_path = self.base_dir / "local_pages.json"
            
            if not local_pages_path.exists():
                logger.warning(f"Файл local_pages.json не найден в {self.base_dir}")
                return {}
            
            with open(local_pages_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"Загружено {len(data.get('pages', {}))} страниц из local_pages.json")
                return data
                
        except Exception as e:
            logger.error(f"Ошибка при загрузке local_pages.json: {str(e)}")
            return {}
    
    def _load_prompts(self) -> Dict[str, Any]:
        """
        Загружает данные из всех файлов prompt_*.json в base_dir
        
        Returns:
            Объединенный словарь с промптами из всех файлов
        """
        try:
            combined_prompts = {"pages": {}}
            
            # Ищем все файлы prompt_*.json
            prompt_files = list(self.base_dir.glob("prompt_*.json"))
            
            if not prompt_files:
                logger.warning(f"Файлы prompt_*.json не найдены в {self.base_dir}")
                return combined_prompts
            
            # Загружаем и объединяем все файлы
            for prompt_file in prompt_files:
                try:
                    with open(prompt_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        pages = data.get("pages", {})
                        combined_prompts["pages"].update(pages)
                        logger.info(f"Загружено {len(pages)} промптов из {prompt_file.name}")
                except Exception as e:
                    logger.error(f"Ошибка при загрузке {prompt_file.name}: {str(e)}")
                    continue
            
            total_prompts = len(combined_prompts["pages"])
            logger.info(f"Всего загружено {total_prompts} промптов из {len(prompt_files)} файлов")
            return combined_prompts
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке prompt файлов: {str(e)}")
            return {"pages": {}}
    
    async def reload_local_pages(self):
        """
        Перезагружает данные из local_pages.json
        Полезно если файл был обновлен во время работы программы
        """
        async with self.local_pages_lock:
            self.local_pages_cache = self._load_local_pages()
            logger.info("local_pages.json перезагружен")
    
    async def reload_prompts(self):
        """
        Перезагружает данные из prompt_*.json файлов
        Полезно если файлы были обновлены во время работы программы
        """
        async with self.prompts_lock:
            self.prompts_cache = self._load_prompts()
            logger.info("Промпты перезагружены")
    
    def get_document_url(self, filename: str) -> Optional[str]:
        """
        Получает URL документа из кэшированных данных local_pages
        
        Args:
            filename: Имя файла без расширения
            
        Returns:
            URL документа или None если не найден
        """
        try:
            # Работаем с кэшированными данными
            if not self.local_pages_cache:
                return None
            
            pages = self.local_pages_cache.get("pages", {})
            
            # Ищем соответствующий документ
            for page_id, page_info in pages.items():
                # Проверяем file_name (может быть с расширением .md)
                file_name = page_info.get("file_name", "")
                
                # Убираем расширение для сравнения
                file_name_without_ext = file_name.replace('.md', '').replace('.txt', '').replace('.markdown', '')
                
                if file_name_without_ext == filename:
                    return page_info.get("url")
            
            # Если не нашли по file_name, пробуем по ключу
            if filename in pages:
                return pages[filename].get("url")
                
            logger.debug(f"URL не найден для файла: {filename}")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при получении URL для {filename}: {str(e)}")
            return None    
    
    def get_page_id_by_filename(self, filename: str) -> Optional[str]:
        """
        Получает page_id документа по имени файла
        
        Args:
            filename: Имя файла без расширения
            
        Returns:
            page_id или None если не найден
        """
        try:
            if not self.local_pages_cache:
                return None
            
            pages = self.local_pages_cache.get("pages", {})
            
            # Ищем документ и возвращаем его page_id
            for page_id, page_info in pages.items():
                file_name = page_info.get("file_name", "")
                file_name_without_ext = file_name.replace('.md', '').replace('.txt', '').replace('.markdown', '')
                
                if file_name_without_ext == filename:
                    return page_id
            
            # Если filename совпадает с page_id
            if filename in pages:
                return filename
                
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при получении page_id для {filename}: {str(e)}")
            return None
    
    def get_add_prompt(self, filename: str) -> Optional[str]:
        """
        Получает add_prompt для документа из файлов prompt_*.json
        
        Args:
            filename: Имя файла без расширения
            
        Returns:
            add_prompt или None если не найден
        """
        try:
            # Получаем page_id документа
            page_id = self.get_page_id_by_filename(filename)
            
            if not page_id:
                logger.debug(f"page_id не найден для файла: {filename}")
                return None
            
            # Ищем промпт в кэше
            prompts_pages = self.prompts_cache.get("pages", {})
            
            if page_id in prompts_pages:
                add_prompt = prompts_pages[page_id].get("add_prompt")
                if add_prompt:
                    logger.debug(f"Найден add_prompt для {filename} (page_id: {page_id})")
                    return add_prompt
            
            logger.debug(f"add_prompt не найден для {filename} (page_id: {page_id})")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при получении add_prompt для {filename}: {str(e)}")
            return None
    
    def get_all_document_urls(self) -> Dict[str, str]:
        """
        Возвращает словарь всех документов и их URL
        
        Returns:
            Словарь {filename: url}
        """
        result = {}
        
        if not self.local_pages_cache:
            return result
        
        pages = self.local_pages_cache.get("pages", {})
        
        for page_id, page_info in pages.items():
            file_name = page_info.get("file_name", "")
            if file_name:
                file_name_without_ext = file_name.replace('.md', '').replace('.txt', '').replace('.markdown', '')
                url = page_info.get("url")
                if url:
                    result[file_name_without_ext] = url
        
        return result
    
    async def log_query_and_documents(
        self,
        user_id: int,
        query: str,
        selected_documents: List[str],
        selection_time: float,
        has_add_prompt: bool = False,
        metadata: Dict[str, Any] = None
    ):
        """
        Асинхронно логирует запрос пользователя и отобранные документы
        
        Args:
            user_id: ID пользователя
            query: Запрос пользователя
            selected_documents: Список отобранных документов
            selection_time: Время выбора документов в секундах
            has_add_prompt: Был ли применен add_prompt
            metadata: Дополнительные метаданные
        """
        try:
            # Формируем запись лога
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "query": query,
                "selected_documents": selected_documents,
                "documents_count": len(selected_documents),
                "selection_time": round(selection_time, 3),
                "has_add_prompt": has_add_prompt,
                "selection_model": self.config.get("selection_model", "unknown")
            }
            
            # Добавляем дополнительные метаданные если есть
            if metadata:
                log_entry["metadata"] = metadata
            
            # Добавляем информацию о документах
            documents_info = []
            for doc_name in selected_documents:
                doc_info = {
                    "filename": doc_name,
                    "url": self.get_document_url(doc_name),
                    "has_add_prompt": bool(self.get_add_prompt(doc_name))
                }
                metadata_doc = self.get_document_metadata(doc_name)
                if metadata_doc.get("title"):
                    doc_info["title"] = metadata_doc["title"]
                documents_info.append(doc_info)
            
            log_entry["documents_info"] = documents_info
            
            # Асинхронная запись в файл
            async with self.queries_log_lock:
                async with aiofiles.open(self.queries_log_path, 'a', encoding='utf-8') as f:
                    await f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            
            logger.debug(f"Query logged for user {user_id}: {len(selected_documents)} documents selected")
            
        except Exception as e:
            logger.error(f"Ошибка при логировании запроса: {str(e)}", exc_info=True)
    
    async def get_queries_log(
        self,
        user_id: Optional[int] = None,
        limit: Optional[int] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Читает лог запросов с фильтрацией
        
        Args:
            user_id: Фильтр по ID пользователя (опционально)
            limit: Максимальное количество записей (опционально)
            from_date: Дата начала в формате ISO (опционально)
            to_date: Дата окончания в формате ISO (опционально)
            
        Returns:
            Список записей лога
        """
        try:
            if not self.queries_log_path.exists():
                return []
            
            queries = []
            
            async with aiofiles.open(self.queries_log_path, 'r', encoding='utf-8') as f:
                async for line in f:
                    try:
                        entry = json.loads(line.strip())
                        
                        # Фильтр по user_id
                        if user_id is not None and entry.get("user_id") != user_id:
                            continue
                        
                        # Фильтр по датам
                        if from_date and entry.get("timestamp", "") < from_date:
                            continue
                        if to_date and entry.get("timestamp", "") > to_date:
                            continue
                        
                        queries.append(entry)
                        
                        # Ограничение количества
                        if limit and len(queries) >= limit:
                            break
                            
                    except json.JSONDecodeError:
                        continue
            
            return queries
            
        except Exception as e:
            logger.error(f"Ошибка при чтении лога запросов: {str(e)}")
            return []
    
    async def get_queries_statistics(
        self,
        user_id: Optional[int] = None,
        days: int = 7
    ) -> Dict[str, Any]:
        """
        Получает статистику по запросам
        
        Args:
            user_id: ID пользователя для статистики (опционально)
            days: Количество дней для анализа
            
        Returns:
            Словарь со статистикой
        """
        try:
            from_date = (datetime.now() - timedelta(days=days)).isoformat()
            queries = await self.get_queries_log(user_id=user_id, from_date=from_date)
            
            if not queries:
                return {
                    "total_queries": 0,
                    "period_days": days,
                    "user_id": user_id
                }
            
            # Собираем статистику
            total_queries = len(queries)
            documents_counter = {}
            avg_selection_time = sum(q.get("selection_time", 0) for q in queries) / total_queries
            queries_with_results = sum(1 for q in queries if q.get("documents_count", 0) > 0)
            queries_with_add_prompt = sum(1 for q in queries if q.get("has_add_prompt", False))
            
            # Подсчитываем популярность документов
            for query in queries:
                for doc in query.get("selected_documents", []):
                    documents_counter[doc] = documents_counter.get(doc, 0) + 1
            
            # Топ документов
            top_documents = sorted(
                documents_counter.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
            
            return {
                "total_queries": total_queries,
                "period_days": days,
                "user_id": user_id,
                "queries_with_results": queries_with_results,
                "queries_with_add_prompt": queries_with_add_prompt,
                "avg_selection_time": round(avg_selection_time, 3),
                "avg_documents_per_query": round(
                    sum(q.get("documents_count", 0) for q in queries) / total_queries, 2
                ),
                "top_documents": [
                    {"document": doc, "count": count}
                    for doc, count in top_documents
                ],
                "unique_documents_used": len(documents_counter)
            }
            
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {str(e)}")
            return {}
    
    async def process_question(self, question: str, user_id: int, verbose: bool = True) -> str:
        """
        Главный метод для обработки вопроса пользователя.
    
        Args:
            question: Вопрос пользователя
            user_id: Telegram ID пользователя
            verbose: Выводить ли информацию о процессе
        
        Returns:
            Ответ на вопрос с указанием источника и URL
        """
        try:
            start_time = time.time()
        
            # Добавляем текущую дату и время в начало запроса
            current_datetime = datetime.now().strftime("%d.%m.%Y %H:%M")

            # Загружаем информацию о пользователе через UserManager
            user_info_str = ""
            try:
                # Используем UserManager для получения данных пользователя
                user_data = await self.user_manager.get_user(str(user_id))
            
                if user_data:
                    # Формируем строку с информацией о пользователе
                    # Учитываем, что в UserManager есть поле company вместо patronymic
                    str_fio = f"{user_data.get('surname', '')} {user_data.get('name', '')}".strip()
                    if str_fio:
                        str_fio += ","
                
                    # Добавляем компанию если есть
                    str_company = user_data.get('company', '').strip()
                    if str_company:
                        str_company = f"Компания: {str_company},"
                
                    str_pos_dept = []
                    if user_data.get('position', '').strip():
                        str_pos_dept.append(user_data.get('position', '').strip())
                    if user_data.get('department', '').strip():
                        str_pos_dept.append(user_data.get('department', '').strip())
                    str_pos = "/".join(str_pos_dept)
                    if str_pos:
                        str_pos += ","
                
                    str_eml = user_data.get('email', '').strip()
                    if str_eml:
                        str_eml += ","
                
                    str_tlg = f"Telegram: @{user_data.get('telegram_username', '')}" if user_data.get('telegram_username') else ""
                
                    # Собираем все части вместе
                    usr_info_parts = [str_fio, str_company, str_pos, str_eml, str_tlg]
                    usr_info = " ".join(part for part in usr_info_parts if part).strip()
                
                    if usr_info:
                        user_info_str = f"\n[Информация о пользователе: {usr_info}]"
                                                    
            except Exception as e:
                logger.debug(f"Не удалось загрузить информацию о пользователе {user_id}: {str(e)}")
                if verbose:
                    print(f"[WARNING] Не удалось загрузить информацию о пользователе: {str(e)}")

            # Формируем запрос с датой, временем и информацией о пользователе
            question_with_datetime = f"[Текущая дата и время: {current_datetime}]{user_info_str}\n\n{question}"
        
            # 1. Выбираем релевантные документы
            selection_start = time.time()
            selected_files = await self.select_relevant_documents(question_with_datetime, user_id)
            selection_time = time.time() - selection_start

            if not selected_files or selected_files == "NONE":
                if verbose:
                    print(f"[INFO] Документы не найдены")
                    print(f"[TIME] Время поиска: {selection_time:.2f}с")
                    print(f"[MODEL] Модель выбора: {self.config.get('selection_model')}")
                return "К сожалению, не найдено документов для ответа на ваш вопрос."
        
            # Логируем выбранные файлы
            if verbose:
                print(f"\n[INFO] Выбранные документы:")
                for i, file in enumerate(selected_files, 1):
                    url = self.get_document_url(file)
                    url_info = f" ({url[:50]}...)" if url else " (URL не найден)"
                    add_prompt = self.get_add_prompt(file)
                    add_prompt_info = " [+prompt]" if add_prompt else ""
                    print(f"  {i}. {file}{url_info}{add_prompt_info}")
                print(f"[TIME] Время выбора документов: {selection_time:.2f}с")
                print(f"[MODEL] Модель выбора: {self.config.get('selection_model')}")
        
            # Асинхронно логируем запрос и отобранные документы
            asyncio.create_task(
                self.log_query_and_documents(
                    user_id=user_id,
                    query=question,  # Оригинальный запрос без даты
                    selected_documents=selected_files,
                    selection_time=selection_time,
                    has_add_prompt=False,  # Пока не знаем, обновим позже если нужно
                    metadata={
                        "query_with_datetime": question_with_datetime,
                        "current_datetime": current_datetime
                    }
                )
            )
        
            # 2. Подготавливаем контекст
            context_start = time.time()
            result = await self.prepare_context(selected_files, question_with_datetime)
            context = result["context"]
            filename = result["filename"]
        
            # Обработка дополнительных файлов из опции add_files
            additional_context = ""
            additional_files_used = []
        
            if filename:
                # Получаем опции для основного документа
                doc_options = self.get_document_options(filename)
            
                if doc_options and "add_files" in doc_options:
                    add_files_list = doc_options["add_files"]
                    if verbose:
                        print(f"[INFO] Найдены дополнительные файлы для {filename}: {add_files_list}")
                
                    # Загружаем каждый дополнительный файл
                    for add_file_id in add_files_list:
                        try:
                            # Проверяем доступ пользователя к дополнительному файлу
                            if self.check_document_access(user_id, add_file_id):
                                # Загружаем документ
                                add_doc = await self.load_document(add_file_id)
                            
                                if add_doc:
                                    additional_context += f"\n\n=== Дополнительный документ: {add_file_id} ===\n{add_doc.content}"
                                    additional_files_used.append(add_file_id)
                                
                                    if verbose:
                                        print(f"[INFO] Добавлен дополнительный файл: {add_file_id}")
                            else:
                                if verbose:
                                    print(f"[WARNING] Нет доступа к дополнительному файлу: {add_file_id}")
                                
                        except Exception as e:
                            logger.error(f"Ошибка при загрузке дополнительного файла {add_file_id}: {str(e)}")
                            if verbose:
                                print(f"[ERROR] Не удалось загрузить дополнительный файл {add_file_id}: {str(e)}")
        
            # Объединяем основной контекст с дополнительным
            if additional_context:
                context = context + additional_context
                if verbose:
                    print(f"[INFO] Добавлено {len(additional_files_used)} дополнительных файлов к контексту")

            # Получаем add_prompt из отдельных файлов
            add_prompt = None
            if filename:
                add_prompt = self.get_add_prompt(filename)

            context_time = time.time() - context_start
        
            if verbose:
                print(f"[TIME] Время подготовки контекста: {context_time:.2f}с")
                if add_prompt:
                    print(f"[INFO] Применен add_prompt из документа: {add_prompt[:100]}...")
                if additional_files_used:
                    print(f"[INFO] Использованы дополнительные файлы: {', '.join(additional_files_used)}")
        
            # 3. Генерируем ответ с учетом add_prompt
            answer_start = time.time()

            # Формируем итоговый вопрос с add_prompt если он есть
            final_question = question_with_datetime
            if add_prompt:
                final_question = f"{add_prompt}\n\n{question_with_datetime}"

            answer = await self.generate_answer(final_question, context, user_id)
            answer_time = time.time() - answer_start
        
            total_time = time.time() - start_time
        
            if verbose:
                print(f"[TIME] Время генерации ответа: {answer_time:.2f}с")
                print(f"[MODEL] Модель ответа: {self.config.get('answer_model')}")
                print(f"[TIME] Общее время обработки: {total_time:.2f}с")
                print("-" * 50)

            # Логируем общую статистику
            logger.info(f"QA Process completed for user {user_id}: total_time={total_time:.2f}s, files={len(selected_files)}, add_prompt={bool(add_prompt)}, additional_files={len(additional_files_used)}")
        
            # Формируем ответ с источником и URL
            response = answer
        
            if filename:
                # Получаем URL и метаданные документа из кэша
                doc_url = self.get_document_url(filename)
                doc_metadata = self.get_document_metadata(filename)
            
                # Добавляем информацию об источнике
                response += f"\n\n📄 Источник: {filename}"
            
                # Добавляем заголовок если есть
                if doc_metadata.get("title"):
                    response += f"\n📋 Документ: {doc_metadata['title']}"
            
                # Добавляем URL только если report_url не равно false
                # По умолчанию report_url = true (если поля нет)
                report_url = doc_metadata.get("report_url", True)
                if doc_url and report_url:
                    response += f"\n🔗 URL: {doc_url}"
            
                # Добавляем дату последнего изменения если есть
                if doc_metadata.get("last_modified"):
                    response += f"\n📅 Обновлено: {doc_metadata['last_modified'][:10]}"
            
                # Добавляем индикатор использования add_prompt
                if add_prompt:
                    response += f"\n⚙️ Применены специальные инструкции документа"
            
                # Добавляем информацию о дополнительных файлах
                if additional_files_used:
                    response += f"\n📎 Использованы дополнительные документы: {', '.join(additional_files_used)}"
        
            return response
        
        except Exception as e:
            if verbose:
                print(f"[ERROR] Ошибка: {str(e)}")
            logger.error(f"Error in process_question for user {user_id}: {str(e)}", exc_info=True)
            return f"Произошла ошибка при обработке запроса: {str(e)}"

    def log_ai_request(
        self,
        user_id: int,
        provider: str,
        model: str,
        request_type: str,
        prompt_tokens: int,
        completion_tokens: int,
        response_time: float,
        error: str = None
    ):
        """Логирование AI запросов для системы QA"""
        try:
            # Логируем через activity_logger
            activity_logger.log_ai_request(
                user_id=str(user_id),
                provider=provider,
                model=model,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                duration=response_time
            )
        
            # Дополнительное логирование для отладки
            if error:
                logger.error(f"QA AI Error - User: {user_id}, Model: {model}, Type: {request_type}, Error: {error}")
            else:
                logger.info(f"QA AI Success - User: {user_id}, Model: {model}, Type: {request_type}, Time: {response_time:.2f}s")
            
        except Exception as e:
            logger.error(f"Ошибка логирования QA AI запроса: {e}")

    def _load_config(self) -> Dict:
        """Загружает конфигурацию"""
        default_config = {}
        
        if Path(self.config_path).exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                default_config.update(loaded)        
        
        return default_config
    
    def _load_access_config(self) -> Dict[str, Any]:
        """Загружает конфигурацию доступа к документам"""
        if Path(self.access_config_path).exists():
            with open(self.access_config_path, 'r', encoding='utf-8') as f:
                return json.load(f)   
    
        return None
    
    def get_user_groups(self, user_id: int) -> Set[str]:
        """Получает список групп, в которых состоит пользователь"""
        user_groups = set()
    
        groups = self.access_config.get("groups", {})
        for group_id, group_info in groups.items():
            users_in_group = group_info.get("users", [])
            # Если список пользователей пустой - это публичная группа
            if not users_in_group or user_id in users_in_group:
                user_groups.add(group_id)
    
        return user_groups

    async def reload_access_config(self):
        """Перезагружает конфигурацию доступа"""
        self.access_config = self._load_access_config()
    
    def get_user_documents(self, user_id: int) -> Set[str]:
        """Получает список документов, доступных пользователю"""
        available_docs = set()
    
        # Получаем группы пользователя
        user_groups = self.get_user_groups(user_id)
    
        # Проверяем доступ к документам через группы
        documents = self.access_config.get("documents", {})
        for doc_id, doc_info in documents.items():
            doc_groups = doc_info.get("access_groups", [])
        
            # Проверяем пересечение групп пользователя и групп документа
            if user_groups.intersection(doc_groups):
                available_docs.add(doc_id)
    
        # Добавляем публичные документы (доступные всем)
        public_docs = self.access_config.get("public_documents", [])
        for doc_id in public_docs:
            available_docs.add(doc_id)
    
        return available_docs
    
    def check_document_access(self, user_id: int, document_id: str) -> bool:
        """Проверяет, имеет ли пользователь доступ к конкретному документу"""
        user_docs = self.get_user_documents(user_id)
        return document_id in user_docs

    def get_user_info(self, user_id: int) -> Dict[str, Any]:
        """Получает информацию о пользователе и его доступах"""
        user_groups = self.get_user_groups(user_id)
        user_documents = self.get_user_documents(user_id)
    
        # Собираем информацию о группах
        groups_info = []
        for group_id in user_groups:
            group_data = self.access_config.get("groups", {}).get(group_id, {})
            groups_info.append({
                "id": group_id,
                "name": group_data.get("name", group_id),
                "description": group_data.get("description", "")
            })
    
        # Собираем информацию о документах
        documents_info = []
        for doc_id in user_documents:
            doc_data = self.access_config.get("documents", {}).get(doc_id, {})
            documents_info.append({
                "id": doc_id,
                "name": doc_data.get("name", doc_id)
            })
    
        return {
            "user_id": user_id,
            "groups": groups_info,
            "groups_count": len(groups_info),
            "documents": documents_info,
            "documents_count": len(documents_info)
        }

    def count_tokens(self, text: str) -> int:
        """Подсчитывает токены"""
        return len(self.encoding.encode(text))
    
    def extract_body_content(self, content: str) -> str:
        """Извлекает тело документа после ---"""
        parts = content.split('---', 1)
        if len(parts) > 1:
            return parts[1].strip()
        return content.strip()
    
    def calculate_file_hash(self, content: str) -> str:
        """Вычисляет хэш файла"""
        return hashlib.md5(content.encode()).hexdigest()
    
    def get_model_temperature(self, model: str, default: float = 0.7) -> float:
        """Возвращает правильную температуру для модели"""
        # Модели, требующие temperature = 1
        fixed_temp_models = ["gpt-5", "gpt-5-mini", "gpt-5-nano", "o3", "o3-mini", "o4", "o4-mini", "o1-preview", "o1-mini", "o1"]
        
        # Проверяем, требует ли модель фиксированную температуру
        for fixed_model in fixed_temp_models:
            if fixed_model in model.lower():
                return 1.0
        
        # Для остальных моделей используем переданную температуру
        return default
    
    async def get_file_info(self, filename: str) -> Optional[Tuple[Path, float]]:
        """Получает путь и время модификации файла"""
        for ext in ['.txt', '.md', '.markdown']:
            file_path = self.source_dir / f"{filename}{ext}"
            if file_path.exists():
                stat = file_path.stat()
                return file_path, stat.st_mtime
        return None
    
    async def load_document(self, filename: str) -> Optional[CachedDocument]:
        """Загружает или обновляет документ в кэше"""
        # Проверяем существование файла
        file_info = await self.get_file_info(filename)
        if not file_info:
            return None
        
        file_path, last_modified = file_info
        
        # Создаем запись в кэше если её нет
        if filename not in self.document_cache:
            async with self.cache_lock:
                if filename not in self.document_cache:
                    self.document_cache[filename] = CacheEntry()
        
        cache_entry = self.document_cache[filename]
        
        # Проверяем нужно ли обновление
        needs_update = (
            cache_entry.document is None or
            cache_entry.document.last_modified < last_modified
        )
        
        if not needs_update:
            return cache_entry.document
        
        # Обновляем документ (с блокировкой)
        async with cache_entry.lock:
            # Проверяем еще раз после получения блокировки
            if cache_entry.updating:
                # Кто-то уже обновляет, ждем
                while cache_entry.updating:
                    await asyncio.sleep(0.1)
                return cache_entry.document
            
            # Повторная проверка после блокировки
            if (cache_entry.document and 
                cache_entry.document.last_modified >= last_modified):
                return cache_entry.document
            
            cache_entry.updating = True
            
            try:
                # Читаем файл
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                
                body = self.extract_body_content(content)
                
                # Загружаем резюме
                summary = await self.load_summary(filename, body)
                
                # Обновляем кэш
                cache_entry.document = CachedDocument(
                    content=body,
                    summary=summary,
                    last_modified=last_modified,
                    token_count=self.count_tokens(body),
                    file_hash=self.calculate_file_hash(body)
                )
                
                return cache_entry.document
                
            finally:
                cache_entry.updating = False
    
    async def load_summary(self, filename: str, content: str) -> str:
        """Загружает существующее резюме или создает новое"""
        summary_file = self.summary_dir / f"{filename}_summary.txt"
        
        # Проверяем существующее резюме
        if summary_file.exists():
            async with aiofiles.open(summary_file, 'r', encoding='utf-8') as f:
                summary_content = await f.read()
                return summary_content
        
        # резюме не найдено
        return None
    
    async def select_relevant_documents(self, query: str, user_id: int) -> List[str]:
        """Выбирает релевантные документы для пользователя"""
        start_time = time.time()

        # Получаем доступные документы
        available_docs = self.get_user_documents(user_id)
        
        if not available_docs:
            return []
        
        # Загружаем документы параллельно
        tasks = [self.load_document(doc) for doc in available_docs]
        documents = await asyncio.gather(*tasks)
        
        # Фильтруем None и создаем словарь резюме
        summaries = {}
        for doc_name, doc in zip(available_docs, documents):
            if doc:
                summaries[doc_name] = doc.summary
        
        if not summaries:
            return []

        #print(summaries)
            
        # Выбираем релевантные через API
        root = ET.Element("files")

        for filename, summary in summaries.items():
            file_el = ET.SubElement(root, "file")
            ET.SubElement(file_el, "name").text = filename
            ET.SubElement(file_el, "summary").text = summary

        # Создаём XML со спецификацией и кодировкой UTF-8
        xml_bytes = ET.tostring(root, encoding="utf-8")
        xml_pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8")

        # Преобразуем в строку
        files_list = xml_pretty.decode("utf-8")                    
        
        prompt = f"""Проанализируй запрос и выбери файлы, которые ТОЧНО подходят для ответа.

ЗАПРОС ПОЛЬЗОВАТЕЛЯ: 
{query}

ДОСТУПНЫЕ ФАЙЛЫ С ИХ РЕЗЮМЕ:
{files_list}

ИНСТРУКЦИИ:
1. Выбери ТОЛЬКО те файлы, которые содержат информацию, напрямую отвечающую на запрос
2. Обрати внимание на секции "🎯 ТОЧНОЕ НАЗНАЧЕНИЕ" и "❌ НЕ ПОДХОДИТ ДЛЯ" в резюме
3. Упорядочи файлы по релевантности (первый - самый важный)
4. Если ни один файл не подходит точно, ответь: NONE

Ответь ТОЛЬКО списком имен файлов (без расширений), по одному на строку.
Выбранные файлы (в порядке убывания релевантности):"""


        # Подсчитываем токены
        prompt_tokens = self.count_tokens(prompt) + 10

        model = self.config.get("selection_model", "gpt-5-mini")
        
        # Получаем правильную температуру для модели
        temperature = self.get_model_temperature(model, 0.1)
        
        #print(prompt) 
        
        async with self.api_semaphore:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Выбирай релевантные файлы."},
                        {"role": "user", "content": prompt}
                    ],
                    reasoning_effort = self.config.get("select_reasoning_effort",select_reasoning_effort),
                    verbosity = self.config.get("select_verbosity",select_verbosity),
                    temperature=temperature
                )
                
                result = response.choices[0].message.content.strip()

                completion_tokens = self.count_tokens(result)
                response_time = time.time() - start_time
            
                # Логируем запрос
                self.log_ai_request(
                    user_id=user_id,
                    provider="openai",
                    model=model,
                    request_type="document_selection",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    response_time=response_time
                )
                
                if result == "NONE":
                    return []
                
                selected = []
                for line in result.split('\n'):
                    line = line.strip()
                    if line and line in summaries:
                        selected.append(line)
                
                return selected[:3]  # Максимум 3 файла
                
            except Exception as e:
                response_time = time.time() - start_time
                self.log_ai_request(
                    user_id=user_id,
                    provider="openai",
                    model=model,
                    request_type="document_selection",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    response_time=response_time,
                    error=str(e)
                )
                return []
    
    async def prepare_context(self, selected_files: List[str], query: str) -> Dict[str, Any]:
        """Подготавливает контекст из выбранных файлов"""
        if not selected_files:
            return ""
        
        model = self.config.get("answer_model", "gpt-5")
        max_tokens = self.config["model_contexts"].get(model, 8192) - 3000
        
        # Загружаем документы
        tasks = [self.load_document(doc) for doc in selected_files]
        documents = await asyncio.gather(*tasks)
        
        # Собираем контекст
        context = ""
        total_tokens = 0
        
        for filename, doc in zip(selected_files, documents):
            if not doc:
                continue
            
            # Проверяем влезет ли
            if total_tokens + doc.token_count > max_tokens:
                # Обрезаем документ
                available = max_tokens - total_tokens
                if available > 1000:
                    tokens = self.encoding.encode(doc.content)
                    truncated = self.encoding.decode(tokens[:available])
                    context += f"\n\n=== {filename} (частично) ===\n{truncated}"
                break
            else:
                context += f"\n\n=== {filename} ===\n{doc.content}"
                total_tokens += doc.token_count

                return {"context": context, "filename": filename} # Ограничиваем максимум одним файлом для контекста
        
        return {"context": None, "filename": None}
    
    async def generate_answer(self, query: str, context: str, user_id: int = 0) -> str:
        """Генерирует ответ на основе контекста"""
        start_time = time.time()

        if not context:
            return "Не найдено релевантных документов для ответа на ваш вопрос."
        
        model = self.config.get("answer_model", "gpt-5")
        
        prompt = f"""На основе документов дай подробный ответ на вопрос.

Документы:{context}

Вопрос: {query}

Ответ:"""
        
        # Подсчитываем токены
        prompt_tokens = self.count_tokens(prompt) + 10

        # Получаем правильную температуру для модели
        temperature = self.get_model_temperature(model, 0.7)
        
        async with self.api_semaphore:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Отвечай на основе предоставленных документов."},
                        {"role": "user", "content": prompt}
                    ],
                    reasoning_effort = self.config.get("answer_reasoning_effort", answer_reasoning_effort),
                    verbosity = self.config.get("answer_verbosity", answer_verbosity),
                    temperature=temperature
                )

                answer = response.choices[0].message.content.strip()

                completion_tokens = self.count_tokens(answer)
                response_time = time.time() - start_time
            
                # Логируем запрос
                self.log_ai_request(
                    user_id=user_id,
                    provider="openai",
                    model=model,
                    request_type="answer_generation",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    response_time=response_time
                )
            
                return answer
                
            except Exception as e:

                response_time = time.time() - start_time
                self.log_ai_request(
                    user_id=user_id,
                    provider="openai",
                    model=model,
                    request_type="answer_generation",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    response_time=response_time,
                    error=str(e)
                )
                
                return f"Ошибка при генерации ответа: {str(e)}"

    async def cleanup_cache(self):
        """Очищает устаревший кэш"""
        current_time = time.time()
        ttl = self.config.get("cache_ttl_seconds", 300)
        
        async with self.cache_lock:
            to_remove = []
            for filename, entry in self.document_cache.items():
                if entry.document:
                    age = current_time - entry.document.last_modified
                    if age > ttl:
                        to_remove.append(filename)
            
            for filename in to_remove:
                del self.document_cache[filename]


# Пример использования логирования запросов:
"""
# Получить последние 10 запросов
queries = await qa_system.get_queries_log(limit=10)

# Получить запросы конкретного пользователя
user_queries = await qa_system.get_queries_log(user_id=123456)

# Получить запросы за период
queries = await qa_system.get_queries_log(
    from_date="2025-01-01T00:00:00",
    to_date="2025-01-31T23:59:59"
)

# Получить статистику за последние 7 дней
stats = await qa_system.get_queries_statistics(days=7)
print(f"Всего запросов: {stats['total_queries']}")
print(f"Топ документов: {stats['top_documents']}")

# Получить статистику для конкретного пользователя
user_stats = await qa_system.get_queries_statistics(user_id=123456, days=30)
"""