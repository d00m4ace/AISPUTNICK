# code/agents/lightweight_rag.py

import os
import json
import hashlib
import numpy as np
import re
from collections import Counter
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import asyncio
import pickle

from utils.codebase_utils import _get_owner_config, _get_owner_params_and_settings

import logging
logger = logging.getLogger(__name__)


class LightweightRAG:

    def __init__(self, index_dir: str = None):
        from config import Config
        if index_dir is None:
            index_dir = os.path.join(Config.DATA_DIR, "rag_indexes")

        self.index_dir = index_dir
        os.makedirs(index_dir, exist_ok=True)

        self.indexes_cache = {}
        self._lock = asyncio.Lock()

        # Расширенный список стоп-слов
        self.stop_words = set([
            'и', 'в', 'на', 'с', 'по', 'для', 'от', 'из', 'к', 'о', 'у', 'за',
            'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
            'from', 'as', 'is', 'was', 'are', 'were', 'been', 'be', 'have', 'has',
            'это', 'что', 'как', 'или', 'если', 'то', 'не', 'все', 'так'
        ])

        logger.info("Инициализирован оптимизированный RAG индексатор с NumPy")

    def _is_text_file(self, filename: str) -> bool:
        from config import Config
        return Config.is_text_file(filename)

    def _get_index_path(self, user_id: str, codebase_id: str) -> str:
        return os.path.join(self.index_dir, f"{user_id}_{codebase_id}")

    def _get_file_hash(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return ""

    def _tokenize(self, text: str) -> List[str]:
        """Улучшенная токенизация с поддержкой различных языков и форматов"""
        # Приводим к нижнему регистру
        text_lower = text.lower()
        
        # Расширенный паттерн для поиска слов
        # \b не работает корректно с кириллицей, используем другой подход
        # Разбиваем по пробелам и знакам препинания
        import re
        
        # Сначала заменяем знаки препинания на пробелы
        text_clean = re.sub(r'[.,!?;:()«»"\'`\[\]{}|\\/<>@#$%^&*+=~]', ' ', text_lower)
        
        # Находим все слова (кириллица, латиница, цифры, дефисы и подчеркивания внутри слов)
        words = re.findall(r'[а-яёa-z0-9]+(?:[-_][а-яёa-z0-9]+)*', text_clean)
        
        # Фильтруем стоп-слова и слишком короткие слова
        tokens = []
        for w in words:
            # Пропускаем стоп-слова
            if w in self.stop_words:
                continue
            # Пропускаем слова короче 2 символов (но оставляем важные короткие слова)
            if len(w) < 2 and w not in ['c', 'r', 'go', 'js', 'ts', 'ai', 'id', 'db']:
                continue
            tokens.append(w)
        
        # Добавляем n-граммы для лучшего поиска
        # Создаем биграммы для коротких запросов
        if len(tokens) <= 5 and len(tokens) > 1:
            bigrams = []
            for i in range(len(tokens) - 1):
                bigram = f"{tokens[i]}_{tokens[i+1]}"
                bigrams.append(bigram)
            tokens.extend(bigrams)
        
        # Логируем результат токенизации для отладки
        logger.debug(f"Токенизация: '{text[:50]}...' -> {tokens[:10]}...")
        
        return tokens

    def _build_vocabulary(self, all_documents: List[List[str]]) -> Dict[str, int]:
        """Построение словаря с учетом частотности"""
        vocabulary = {}
        vocab_idx = 0
        word_freq = Counter()

        # Подсчитываем частоты всех слов
        for doc_tokens in all_documents:
            word_freq.update(doc_tokens)
        
        # Добавляем в словарь, приоритизируя частые слова
        for word, freq in word_freq.most_common():
            vocabulary[word] = vocab_idx
            vocab_idx += 1

        logger.info(f"Построен словарь из {len(vocabulary)} уникальных токенов")
        return vocabulary

    def _documents_to_matrix(self, documents: List[List[str]], vocabulary: Dict[str, int]) -> np.ndarray:
        n_docs = len(documents)
        n_terms = len(vocabulary)

        term_doc_matrix = np.zeros((n_docs, n_terms), dtype=np.float32)

        for doc_idx, doc_tokens in enumerate(documents):
            word_counts = Counter(doc_tokens)
            total_words = len(doc_tokens)

            if total_words == 0:
                continue

            for word, count in word_counts.items():
                if word in vocabulary:
                    word_idx = vocabulary[word]
                    # TF normalization
                    term_doc_matrix[doc_idx, word_idx] = count / total_words

        return term_doc_matrix

    def _compute_tfidf_matrix(self, tf_matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        n_docs, n_terms = tf_matrix.shape

        # IDF calculation with smoothing
        doc_freq = np.sum(tf_matrix > 0, axis=0)
        idf = np.log((n_docs + 1) / (1 + doc_freq))  # Smoothing to avoid division by zero

        tfidf_matrix = tf_matrix * idf

        # L2 normalization
        norms = np.linalg.norm(tfidf_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        tfidf_matrix_normalized = tfidf_matrix / norms

        return tfidf_matrix_normalized, idf

    def _cosine_similarity_batch(self, query_vector: np.ndarray, doc_matrix: np.ndarray) -> np.ndarray:
        similarities = np.dot(doc_matrix, query_vector)
        return similarities

    def _split_into_chunks(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """Улучшенное разбиение на чанки с сохранением контекста"""
        if not text:
            return []

        chunks = []
        lines = text.split('\n')
        current_chunk = []
        current_size = 0

        for line in lines:
            line_size = len(line)

            if current_size + line_size > chunk_size and current_chunk:
                # Сохраняем чанк
                chunks.append('\n'.join(current_chunk))

                # Создаем перекрытие
                if overlap > 0 and len(current_chunk) > 1:
                    overlap_lines = []
                    overlap_size = 0
                    for prev_line in reversed(current_chunk):
                        if overlap_size + len(prev_line) <= overlap:
                            overlap_lines.insert(0, prev_line)
                            overlap_size += len(prev_line)
                        else:
                            break
                    current_chunk = overlap_lines
                    current_size = overlap_size
                else:
                    current_chunk = []
                    current_size = 0

            current_chunk.append(line)
            current_size += line_size

        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        return chunks

    async def index_codebase(
        self,
        user_id: str,
        codebase_id: str,
        files_dir: str,
        force_reindex: bool = False,
        progress_callback=None,
        chunk_size: int = None,
        overlap_size: int = None
    ) -> Tuple[bool, str]:
        async with self._lock:
            try:
                real_user_id, real_codebase_id, owner_rag_settings = _get_owner_params_and_settings(user_id, codebase_id)

                if owner_rag_settings:
                    if chunk_size is None:
                        chunk_size = owner_rag_settings.get("chunk_size", 4096)
                    if overlap_size is None:
                        overlap_size = owner_rag_settings.get("overlap_size", 256)
                    logger.info(f"Используем RAG настройки владельца: chunk_size={chunk_size}, overlap_size={overlap_size}")

                if chunk_size is None:
                    chunk_size = 1024 * 4
                if overlap_size is None:
                    overlap_size = 256

                logger.info(f"Индексация с размером чанка: {chunk_size}, перекрытие: {overlap_size}")

                index_path = self._get_index_path(user_id, codebase_id)
                os.makedirs(index_path, exist_ok=True)

                metadata_file = os.path.join(index_path, "metadata.json")
                index_file = os.path.join(index_path, "tfidf_matrix.npz")
                vocab_file = os.path.join(index_path, "vocabulary.pkl")
                chunks_file = os.path.join(index_path, "chunks.pkl")

                existing_metadata = {}
                if os.path.exists(metadata_file) and not force_reindex:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        existing_metadata = json.load(f)

                files_to_index = []
                all_files = []

                if os.path.exists(files_dir):
                    for filename in os.listdir(files_dir):
                        if not self._is_text_file(filename):
                            logger.debug(f"Пропускаем не-текстовый файл: {filename}")
                            continue

                        file_path = os.path.join(files_dir, filename)
                        if os.path.isfile(file_path):
                            all_files.append(filename)

                            file_hash = self._get_file_hash(file_path)
                            existing_info = existing_metadata.get('files', {}).get(filename, {})

                            if force_reindex or existing_info.get('hash') != file_hash:
                                files_to_index.append((filename, file_path, file_hash))

                removed_files = set(existing_metadata.get('files', {}).keys()) - set(all_files)

                if not files_to_index and not removed_files and not force_reindex:
                    return True, "Индекс актуален, обновление не требуется"

                # При force_reindex индексируем все файлы
                if force_reindex:
                    existing_chunks_data = []
                    existing_tokens = []
                else:
                    if os.path.exists(chunks_file):
                        with open(chunks_file, 'rb') as f:
                            existing_chunks_data = pickle.load(f)
                        existing_chunks_data = [
                            c for c in existing_chunks_data
                            if c['filename'] not in removed_files
                        ]
                        existing_tokens = [c['tokens'] for c in existing_chunks_data]
                    else:
                        existing_chunks_data = []
                        existing_tokens = []

                new_chunks_data = []
                new_tokens = []

                total_files = len(files_to_index)
                for idx, (filename, file_path, file_hash) in enumerate(files_to_index):
                    if progress_callback:
                        await progress_callback(f"Индексация {filename} ({idx+1}/{total_files})")

                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                    except:
                        logger.warning(f"Не удалось прочитать файл {filename}")
                        continue

                    chunks = self._split_into_chunks(content, chunk_size=chunk_size, overlap=overlap_size)

                    for chunk_idx, chunk_text in enumerate(chunks):
                        tokens = self._tokenize(chunk_text)
                        if tokens:  # Только если есть токены
                            new_chunks_data.append({
                                'filename': filename,
                                'chunk_idx': chunk_idx,
                                'text': chunk_text,
                                'tokens': tokens
                            })
                            new_tokens.append(tokens)

                    if 'files' not in existing_metadata:
                        existing_metadata['files'] = {}

                    existing_metadata['files'][filename] = {
                        'hash': file_hash,
                        'chunks_count': len(chunks),
                        'indexed_at': datetime.now().isoformat()
                    }

                all_chunks_data = existing_chunks_data + new_chunks_data
                all_tokens = existing_tokens + new_tokens

                if not all_tokens:
                    return False, "Нет данных для индексации"

                logger.info(f"Построение словаря для {len(all_tokens)} чанков")
                vocabulary = self._build_vocabulary(all_tokens)

                logger.info(f"Создание TF матрицы размером {len(all_tokens)} x {len(vocabulary)}")
                tf_matrix = self._documents_to_matrix(all_tokens, vocabulary)

                logger.info("Вычисление TF-IDF матрицы")
                tfidf_matrix, idf_vector = self._compute_tfidf_matrix(tf_matrix)

                # Сохраняем индекс
                np.savez_compressed(
                    index_file,
                    tfidf_matrix=tfidf_matrix,
                    idf_vector=idf_vector
                )

                with open(vocab_file, 'wb') as f:
                    pickle.dump(vocabulary, f)

                with open(chunks_file, 'wb') as f:
                    pickle.dump(all_chunks_data, f)

                # Удаляем информацию об удаленных файлах
                for filename in removed_files:
                    existing_metadata['files'].pop(filename, None)

                # Обновляем метаданные
                existing_metadata['last_updated'] = datetime.now().isoformat()
                existing_metadata['total_chunks'] = len(all_chunks_data)
                existing_metadata['index_type'] = 'tfidf_numpy'
                existing_metadata['total_unique_words'] = len(vocabulary)
                existing_metadata['matrix_shape'] = list(tfidf_matrix.shape)
                existing_metadata['chunk_size'] = chunk_size
                existing_metadata['overlap_size'] = overlap_size

                from config import Config
                existing_metadata['supported_formats'] = sorted(list(Config.get_text_extensions()))

                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_metadata, f, ensure_ascii=False, indent=2)

                # Обновляем кэш
                cache_key = f"{user_id}_{codebase_id}"
                self.indexes_cache[cache_key] = {
                    'tfidf_matrix': tfidf_matrix,
                    'idf_vector': idf_vector,
                    'vocabulary': vocabulary,
                    'chunks_data': all_chunks_data,
                    'metadata': existing_metadata
                }

                indexed_count = len(files_to_index)
                removed_count = len(removed_files)
                total_chunks = len(all_chunks_data)
                new_chunks = len(new_chunks_data)

                msg = f"Обновлено файлов: {indexed_count}, новых чанков: {new_chunks}, всего в индексе: {total_chunks} чанков"
                if removed_count > 0:
                    msg += f", удалено файлов: {removed_count}"

                logger.info(msg)
                return True, msg

            except Exception as e:
                logger.error(f"Ошибка индексации: {e}", exc_info=True)
                return False, f"Ошибка индексации: {str(e)}"

    async def search(
        self,
        user_id: str,
        codebase_id: str,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        try:
            cache_key = f"{user_id}_{codebase_id}"

            # Загружаем индекс если его нет в кэше
            if cache_key not in self.indexes_cache:
                index_path = self._get_index_path(user_id, codebase_id)
                index_file = os.path.join(index_path, "tfidf_matrix.npz")
                vocab_file = os.path.join(index_path, "vocabulary.pkl")
                chunks_file = os.path.join(index_path, "chunks.pkl")
                metadata_file = os.path.join(index_path, "metadata.json")

                if not os.path.exists(index_file):
                    logger.warning(f"Индекс не найден для {user_id}/{codebase_id}")
                    return []

                data = np.load(index_file)
                tfidf_matrix = data['tfidf_matrix']
                idf_vector = data['idf_vector']

                with open(vocab_file, 'rb') as f:
                    vocabulary = pickle.load(f)

                with open(chunks_file, 'rb') as f:
                    chunks_data = pickle.load(f)

                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                self.indexes_cache[cache_key] = {
                    'tfidf_matrix': tfidf_matrix,
                    'idf_vector': idf_vector,
                    'vocabulary': vocabulary,
                    'chunks_data': chunks_data,
                    'metadata': metadata
                }

            cache_data = self.indexes_cache[cache_key]
            tfidf_matrix = cache_data['tfidf_matrix']
            idf_vector = cache_data['idf_vector']
            vocabulary = cache_data['vocabulary']
            chunks_data = cache_data['chunks_data']

            if tfidf_matrix.shape[0] == 0:
                logger.warning("Пустая матрица TF-IDF")
                return []

            # Токенизация запроса
            query_tokens = self._tokenize(query)
            logger.debug(f"Токены запроса: {query_tokens[:10]}...")  # Логируем первые 10 токенов
            
            if not query_tokens:
                logger.warning("Пустой запрос после токенизации")
                # Пробуем простое разбиение если токенизация не дала результатов
                query_tokens = query.lower().split()
            
            # Построение вектора запроса
            query_vector = np.zeros(len(vocabulary), dtype=np.float32)
            
            token_counts = Counter(query_tokens)
            total_tokens = len(query_tokens)
            found_tokens = 0

            for token, count in token_counts.items():
                if token in vocabulary:
                    token_idx = vocabulary[token]
                    tf = count / total_tokens
                    query_vector[token_idx] = tf * idf_vector[token_idx]
                    found_tokens += 1

            logger.debug(f"Найдено {found_tokens} из {len(token_counts)} уникальных токенов в словаре")

            # Если ни один токен не найден, пробуем частичное совпадение
            if found_tokens == 0:
                logger.info("Токены не найдены в словаре, пробуем частичное совпадение")
                for token in query_tokens:
                    # Ищем похожие слова в словаре
                    for vocab_word in vocabulary:
                        if token in vocab_word or vocab_word in token:
                            token_idx = vocabulary[vocab_word]
                            query_vector[token_idx] = idf_vector[token_idx] * 0.5  # Меньший вес для частичного совпадения
                            found_tokens += 1
                            if found_tokens >= 5:  # Ограничиваем количество частичных совпадений
                                break
                    if found_tokens >= 5:
                        break

            # Нормализация вектора запроса
            query_norm = np.linalg.norm(query_vector)
            if query_norm > 0:
                query_vector = query_vector / query_norm
            else:
                logger.warning("Нулевой вектор запроса после обработки")
                # В крайнем случае возвращаем случайные чанки
                if len(chunks_data) > 0:
                    random_indices = np.random.choice(len(chunks_data), min(top_k, len(chunks_data)), replace=False)
                    results = []
                    for idx in random_indices:
                        chunk_data = chunks_data[idx]
                        results.append({
                            'filename': chunk_data['filename'],
                            'text': chunk_data['text'],
                            'chunk_idx': chunk_data['chunk_idx'],
                            'relevance': 0.01,  # Низкая релевантность для случайных результатов
                            'distance': 0.99
                        })
                    logger.info(f"Возвращаем {len(results)} случайных чанков из-за нулевого вектора")
                    return results
                return []

            # Вычисление схожести
            similarities = self._cosine_similarity_batch(query_vector, tfidf_matrix)

            # Выбор топ-K результатов
            if len(similarities) > top_k:
                top_indices = np.argpartition(similarities, -top_k)[-top_k:]
                top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]
            else:
                top_indices = np.argsort(similarities)[::-1]

            results = []
            for idx in top_indices:
                if similarities[idx] > 0:  # Только положительные схожести
                    chunk_data = chunks_data[idx]
                    results.append({
                        'filename': chunk_data['filename'],
                        'text': chunk_data['text'],
                        'chunk_idx': chunk_data['chunk_idx'],
                        'relevance': float(similarities[idx]),
                        'distance': float(1.0 - similarities[idx])
                    })

            logger.info(f"Найдено {len(results)} релевантных чанков для запроса: {query[:50]}...")
            
            # Если результатов мало, возвращаем хоть что-то
            if len(results) < 3 and len(chunks_data) > 0:
                # Добавляем случайные чанки с низкой релевантностью
                existing_indices = set([chunks_data.index(r) for r in chunks_data if any(
                    r['filename'] == res['filename'] and r['chunk_idx'] == res['chunk_idx'] 
                    for res in results
                )])
                remaining_indices = [i for i in range(len(chunks_data)) if i not in existing_indices]
                
                if remaining_indices:
                    additional = min(3 - len(results), len(remaining_indices))
                    random_indices = np.random.choice(remaining_indices, additional, replace=False)
                    
                    for idx in random_indices:
                        chunk_data = chunks_data[idx]
                        results.append({
                            'filename': chunk_data['filename'],
                            'text': chunk_data['text'],
                            'chunk_idx': chunk_data['chunk_idx'],
                            'relevance': 0.01,
                            'distance': 0.99
                        })
                    logger.info(f"Добавлено {additional} дополнительных чанков для контекста")

            return results

        except Exception as e:
            logger.error(f"Ошибка поиска: {e}", exc_info=True)
            return []

    async def get_index_info(self, user_id: str, codebase_id: str) -> Optional[Dict[str, Any]]:
        try:
            index_path = self._get_index_path(user_id, codebase_id)
            metadata_file = os.path.join(index_path, "metadata.json")

            if not os.path.exists(metadata_file):
                return None

            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            return {
                'files_count': len(metadata.get('files', {})),
                'total_chunks': metadata.get('total_chunks', 0),
                'total_unique_words': metadata.get('total_unique_words', 0),
                'last_updated': metadata.get('last_updated'),
                'files': list(metadata.get('files', {}).keys()),
                'index_type': metadata.get('index_type', 'tfidf_numpy'),
                'matrix_shape': metadata.get('matrix_shape', []),
                'chunk_size': metadata.get('chunk_size', 0),
                'overlap_size': metadata.get('overlap_size', 0),
                'supported_formats': metadata.get('supported_formats', [])
            }

        except Exception as e:
            logger.error(f"Ошибка получения информации об индексе: {e}")
            return None

    async def clear_cache(self, user_id: str = None, codebase_id: str = None):
        if user_id and codebase_id:
            cache_key = f"{user_id}_{codebase_id}"
            self.indexes_cache.pop(cache_key, None)
            logger.info(f"Кэш очищен для {cache_key}")
        else:
            self.indexes_cache.clear()
            logger.info("Весь кэш индексов очищен")