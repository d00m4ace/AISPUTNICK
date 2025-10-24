# code/agents/filejob_agent.py

import os
import tempfile
import zipfile
import shutil
import json
import logging
import asyncio
import re
import fnmatch
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from utils.markdown_utils import escape_markdown_v2
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import types, F
from aiogram.types import FSInputFile
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)

class FilejobAgent:
    """Агент для пакетной обработки файлов с применением ИИ к каждому файлу"""
    
    def __init__(self):
        self.name = "filejob"
        self.config = self._load_default_config()
        self.active_jobs = {}  # Хранение активных задач для возможности отмены
        
    async def handle_document(self, message: types.Message, state: FSMContext, agent_handler):
        """
        Обработка документов для filejob агента
        В данном случае просто информируем пользователя
        """
        await message.reply(
            "ℹ️ Агент *filejob* не поддерживает интерактивную загрузку файлов\\.\n\n"
            "Используйте:\n"
            "`@filejob селектор_файлов`\n"
            "для обработки файлов из активной кодовой базы\\.\n\n"
            "_Если у вас активен другой агент, используйте /agent\\_stop_",
            parse_mode="MarkdownV2"
        )

    def _load_default_config(self) -> Dict[str, Any]:
        config_path = os.path.join(os.path.dirname(__file__), "configs", "filejob_default.json")
        
        default_config = {}
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    for key, value in loaded_config.items():
                        default_config[key] = value
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига Filejob агента: {e}")
                
        return default_config
    
    def _parse_file_selector(self, selector: str, available_files: List[str]) -> List[str]:
        """Парсит селектор файлов и возвращает список выбранных файлов"""
        selector = selector.strip()
        selected_files = []
        
        # Все файлы
        if selector == "*":
            return available_files
        
        # Числовой диапазон (например, 2-5)
        if re.match(r'^\d+-\d+$', selector):
            start, end = map(int, selector.split('-'))
            for i in range(start - 1, min(end, len(available_files))):
                if 0 <= i < len(available_files):
                    selected_files.append(available_files[i])
            return selected_files
        
        # Список номеров через запятую (например, 1,3,5)
        if re.match(r'^[\d,\s]+$', selector):
            numbers = [int(n.strip()) for n in selector.split(',') if n.strip()]
            for num in numbers:
                if 1 <= num <= len(available_files):
                    selected_files.append(available_files[num - 1])
            return selected_files
        
        # Маска файлов (например, *.py или test_*)
        if '*' in selector or '?' in selector:
            pattern = selector.lower()
            for filename in available_files:
                if fnmatch.fnmatch(filename.lower(), pattern):
                    selected_files.append(filename)
            return selected_files
        
        # Список имен файлов через запятую
        filenames = [f.strip() for f in selector.split(',')]
        for filename in filenames:
            if filename in available_files:
                selected_files.append(filename)
            else:
                # Пробуем найти частичное совпадение
                for available in available_files:
                    if filename.lower() in available.lower():
                        selected_files.append(available)
                        break
        
        return selected_files
    
    def _split_into_chunks(self, content: str, filename: str) -> List[Dict[str, Any]]:
        """Разделяет содержимое файла на чанки согласно настройкам"""
        chunking_config = self.config.get('chunking', {})
        
        if not chunking_config.get('enabled', False):
            return [{'content': content, 'chunk_num': 1, 'total_chunks': 1}]
        
        chunk_size = chunking_config.get('chunk_size', 4000)
        overlap_size = chunking_config.get('overlap_size', 200)
        chunk_mode = chunking_config.get('chunk_mode', 'sliding_window')
        max_chunks = chunking_config.get('max_chunks_per_file', 50)
        
        chunks = []
        
        if chunk_mode == 'fixed':
            # Фиксированные куски без перекрытия
            for i in range(0, len(content), chunk_size):
                if len(chunks) >= max_chunks:
                    break
                chunks.append(content[i:i + chunk_size])
        
        elif chunk_mode == 'sliding_window':
            # Скользящее окно с перекрытием
            step = chunk_size - overlap_size
            for i in range(0, len(content), step):
                if len(chunks) >= max_chunks:
                    break
                chunk = content[i:i + chunk_size]
                if len(chunk.strip()) > 0:  # Пропускаем пустые чанки
                    chunks.append(chunk)
        
        elif chunk_mode == 'smart':
            # Умное разделение по логическим границам
            smart_boundaries = chunking_config.get('smart_boundaries', {})
            
            if smart_boundaries.get('enabled', True):
                patterns = smart_boundaries.get('patterns', [])
                
                # Находим все позиции логических границ
                boundaries = [0]
                for pattern in patterns:
                    for match in re.finditer(pattern, content):
                        boundaries.append(match.start())
                
                boundaries.append(len(content))
                boundaries = sorted(set(boundaries))
                
                # Создаем чанки на основе границ
                current_chunk = ""
                for i in range(1, len(boundaries)):
                    segment = content[boundaries[i-1]:boundaries[i]]
                    
                    if len(current_chunk) + len(segment) <= chunk_size:
                        current_chunk += segment
                    else:
                        if current_chunk.strip():
                            chunks.append(current_chunk)
                            if len(chunks) >= max_chunks:
                                break
                        
                        # Если сегмент больше chunk_size, разбиваем его
                        if len(segment) > chunk_size:
                            for j in range(0, len(segment), chunk_size):
                                sub_chunk = segment[j:j + chunk_size]
                                if sub_chunk.strip():
                                    chunks.append(sub_chunk)
                                    if len(chunks) >= max_chunks:
                                        break
                            current_chunk = ""
                        else:
                            current_chunk = segment
                
                # Добавляем последний чанк
                if current_chunk.strip() and len(chunks) < max_chunks:
                    chunks.append(current_chunk)
            
            else:
                # Если умные границы отключены, используем sliding_window
                return self._split_into_chunks_sliding_window(content, chunk_size, overlap_size, max_chunks)
        
        # Если не создано ни одного чанка, возвращаем весь контент
        if not chunks:
            chunks = [content]
        
        # Форматируем результат
        total_chunks = len(chunks)
        result = []
        for i, chunk_content in enumerate(chunks, 1):
            result.append({
                'content': chunk_content,
                'chunk_num': i,
                'total_chunks': total_chunks
            })
        
        return result
    
    def _split_into_chunks_sliding_window(self, content: str, chunk_size: int, overlap_size: int, max_chunks: int) -> List[str]:
        """Вспомогательный метод для sliding_window разделения"""
        chunks = []
        step = chunk_size - overlap_size
        
        for i in range(0, len(content), step):
            if len(chunks) >= max_chunks:
                break
            chunk = content[i:i + chunk_size]
            if len(chunk.strip()) > 0:
                chunks.append(chunk)
        
        return chunks
    
    async def _process_concatenate(
        self,
        user_id: str,
        query: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, str, str]:
        """Обрабатывает файлы в режиме простой склейки без ИИ"""
        try:
            # В режиме concatenate принимаем просто селектор файлов
            file_selector = query.strip()
            
            if not file_selector:
                return False, "⚠️ Не указан селектор файлов для склейки", ""
            
            # Получаем компоненты
            codebase_manager = context.get('codebase_manager')
            file_manager = context.get('file_manager')
            
            if not all([codebase_manager, file_manager]):
                return False, "⚠️ Недостаточно компонентов для работы агента", ""
            
            # Получаем активную кодовую базу
            user_codebases = await codebase_manager.get_user_codebases(user_id)
            active_codebase_id = user_codebases.get('active')
            
            if not active_codebase_id:
                return False, "⚠️ Нет активной кодовой базы\\. Выберите базу командой /switch", ""
            
            # Получаем список файлов
            files_data = await file_manager.list_files_for_agent(
                user_id, active_codebase_id, page=1, per_page=1000
            )
            
            if not files_data.get('files'):
                return False, "⚠️ В активной кодовой базе нет файлов", ""
            
            available_files = [f['name'] for f in files_data['files']]
            
            # Парсим селектор
            selected_files = self._parse_file_selector(file_selector, available_files)
            
            if not selected_files:
                return False, f"⚠️ Не найдено файлов по селектору: {escape_markdown_v2(file_selector)}", ""
            
            # Настройки concatenate
            concat_config = self.config.get('concatenate_settings', {})
            
            # Сортировка файлов
            sort_mode = concat_config.get('sort_files', 'name')
            if sort_mode == 'name':
                selected_files.sort()
            elif sort_mode == 'extension':
                selected_files.sort(key=lambda f: (f.split('.')[-1] if '.' in f else '', f))
            elif sort_mode == 'size':
                # Получаем размеры файлов
                file_sizes = {}
                for filename in selected_files:
                    file_content = await file_manager.get_file_for_agent(
                        user_id, active_codebase_id, filename
                    )
                    if file_content:
                        file_sizes[filename] = len(file_content)
                selected_files.sort(key=lambda f: file_sizes.get(f, 0))
            
            # Группировка по расширению
            if concat_config.get('group_by_extension', False):
                grouped = {}
                for filename in selected_files:
                    ext = filename.split('.')[-1] if '.' in filename else 'no_extension'
                    if ext not in grouped:
                        grouped[ext] = []
                    grouped[ext].append(filename)
                
                # Пересобираем список файлов
                selected_files = []
                for ext in sorted(grouped.keys()):
                    selected_files.extend(sorted(grouped[ext]))
            
            # Обрабатываем файлы
            concatenated_parts = []
            toc_items = []
            total_size = 0
            processed_count = 0
            skipped_count = 0
            
            for idx, filename in enumerate(selected_files, 1):
                # Загружаем файл
                file_content = await file_manager.get_file_for_agent(
                    user_id, active_codebase_id, filename
                )
                
                if not file_content:
                    skipped_count += 1
                    continue
                
                file_size = len(file_content)
                
                # Проверяем размер
                max_file_size = concat_config.get('max_file_size', 1048576)
                if file_size > max_file_size and not concat_config.get('truncate_large_files', True):
                    skipped_count += 1
                    continue
                
                # Декодируем содержимое
                encoding_config = self.config.get('encoding', {})
                try_encodings = encoding_config.get('try_encodings', ['utf-8', 'cp1251', 'latin-1', 'cp866'])
                fallback_encoding = encoding_config.get('fallback_encoding', 'latin-1')
                fallback_errors = encoding_config.get('fallback_errors', 'ignore')
                
                content = None
                for encoding in try_encodings:
                    try:
                        content = file_content.decode(encoding)
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
                
                if content is None:
                    try:
                        content = file_content.decode(fallback_encoding, errors=fallback_errors)
                    except:
                        skipped_count += 1
                        continue
                
                # Пропускаем пустые файлы
                if concat_config.get('skip_empty_files', True) and not content.strip():
                    skipped_count += 1
                    continue
                
                # Обрезаем большие файлы
                if concat_config.get('truncate_large_files', True):
                    truncate_at = concat_config.get('truncate_at', 100000)
                    if len(content) > truncate_at:
                        truncate_msg = concat_config.get(
                            'truncate_message',
                            '\n\n[... файл обрезан, показано {shown} из {total} символов ...]\n'
                        )
                        truncated_content = content[:truncate_at]
                        truncated_content += truncate_msg.format(
                            shown=truncate_at,
                            total=len(content)
                        )
                        content = truncated_content
                
                # Формируем заголовок файла
                separator_line = "=" * 60
                # Всегда используем безопасный шаблон, игнорируя конфиг
                header_template = '\n\n' + separator_line + '\n# Файл: {filename}\n# Размер: {size} байт\n' + separator_line + '\n\n'

                # Создаем якорь для навигации
                anchor = filename.replace('/', '_').replace('.', '_').replace(' ', '_')

                header = header_template.format(
                    filename=filename,
                    size=file_size
                )

                # Добавляем якорь если нужно
                if concat_config.get('add_file_anchors', True):
                    header = f'<a name="{anchor}"></a>\n{header}'                     
                
                # Добавляем в результат
                file_separator = concat_config.get('file_separator', '\n\n')
                if concatenated_parts:
                    concatenated_parts.append(file_separator)
                concatenated_parts.append(header + content)
                
                # Добавляем в оглавление
                toc_item_template = concat_config.get(
                    'toc_item_template',
                    '{index}. [{filename}](#{anchor}) - {size} байт\n'
                )
                toc_items.append(toc_item_template.format(
                    index=idx,
                    filename=filename,
                    anchor=anchor,
                    size=file_size
                ))
                
                processed_count += 1
                total_size += file_size
            
            # Формируем итоговый документ
            result_parts = []
            
            # Добавляем оглавление
            if concat_config.get('include_toc', True) and toc_items:
                toc_template = concat_config.get(
                    'toc_template',
                    '# Объединенный документ\n\n## Содержание:\n{toc_items}\n\n---\n\n'
                )
                toc_content = toc_template.format(toc_items=''.join(toc_items))
                result_parts.append(toc_content)
            
            # Добавляем содержимое файлов
            result_parts.extend(concatenated_parts)
            
            # Добавляем статистику
            if concat_config.get('include_stats', True):
                stats_template = concat_config.get(
                    'stats_template',
                    '\n\n---\n\n## Статистика:\n- Всего файлов: {total_files}\n- Общий размер: {total_size}\n- Дата создания: {timestamp}\n'
                )
                
                # Форматируем размер
                if total_size < 1024:
                    size_str = f"{total_size} байт"
                elif total_size < 1024 * 1024:
                    size_str = f"{total_size / 1024:.2f} КБ"
                else:
                    size_str = f"{total_size / (1024 * 1024):.2f} МБ"
                
                stats = stats_template.format(
                    total_files=processed_count,
                    total_size=size_str,
                    timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                )
                result_parts.append(stats)
            
            # Собираем финальный результат
            final_result = ''.join(result_parts)
            
            # Формируем статус
            status_msg = f"✅ Объединено файлов: {processed_count}/{len(selected_files)}"
            if skipped_count > 0:
                status_msg += f"\n⚠️ Пропущено: {skipped_count}"
            status_msg += f"\n📊 Общий размер: {total_size:,} байт"
            
            return True, status_msg, final_result
            
        except Exception as e:
            logger.error(f"Ошибка в режиме concatenate: {e}", exc_info=True)
            return False, f"⚠️ Ошибка склейки файлов: {escape_markdown_v2(str(e))}", ""
    
    async def _process_file_with_chunks(
        self,
        user_id: str,
        filename: str,
        content: str,
        ai_query: str,
        ai_interface: Any,
        ai_provider: str,
        ai_model: str,
        ai_params: Dict,
        job_id: str
    ) -> Dict[str, Any]:
        """Обрабатывает файл с разделением на чанки"""
        chunking_config = self.config.get('chunking', {})
        chunks = self._split_into_chunks(content, filename)
        
        if len(chunks) == 1:
            # Если только один чанк, обрабатываем как обычно
            return await self._process_single_content(
                user_id,
                filename, content, ai_query, ai_interface,
                ai_provider, ai_model, ai_params
            )
        
        # Обрабатываем множественные чанки
        chunk_results = []
        previous_context = ""
        chunk_header_template = chunking_config.get(
            'chunk_header_template',
            "\n[Часть {chunk_num}/{total_chunks} файла {filename}]\n"
        )
        process_sequentially = chunking_config.get('process_chunks_sequentially', False)
        
        for chunk_data in chunks:
            # Проверяем отмену
            if self.active_jobs[job_id]['cancelled']:
                break
            
            # Формируем заголовок чанка
            chunk_header = chunk_header_template.format(
                chunk_num=chunk_data['chunk_num'],
                total_chunks=chunk_data['total_chunks'],
                filename=filename
            )
            
            # Формируем промпт
            if process_sequentially and previous_context:
                chunk_context_template = chunking_config.get(
                    'chunk_context_template',
                    "Это часть {chunk_num} из {total_chunks} файла {filename}. Предыдущий контекст: {previous_context}"
                )
                
                context_info = chunk_context_template.format(
                    chunk_num=chunk_data['chunk_num'],
                    total_chunks=chunk_data['total_chunks'],
                    filename=filename,
                    previous_context=previous_context[:500]  # Ограничиваем размер контекста
                )
                
                system_prompt = f"{context_info}\n\n{chunk_header}\n{chunk_data['content']}"
            else:
                system_prompt = f"Файл: {filename}\n{chunk_header}\n{chunk_data['content']}"
            
            try:
                # Отправляем запрос к ИИ
                response = await ai_interface.send_simple_request(
                    user_id=user_id,
                    provider=ai_provider,
                    prompt=ai_query,
                    system_prompt=system_prompt,
                    model=ai_model if ai_model != 'default' else None,
                    **ai_params
                )
                
                if response:
                    chunk_results.append({
                        'chunk_num': chunk_data['chunk_num'],
                        'result': response,
                        'error': False
                    })
                    
                    # Обновляем контекст для следующего чанка
                    if process_sequentially:
                        previous_context = response[:500]
                else:
                    chunk_results.append({
                        'chunk_num': chunk_data['chunk_num'],
                        'result': f'Ошибка: не удалось получить ответ от ИИ для части {chunk_data["chunk_num"]}',
                        'error': True
                    })
                
            except Exception as e:
                logger.error(f"Ошибка обработки чанка {chunk_data['chunk_num']} файла {filename}: {e}")
                chunk_results.append({
                    'chunk_num': chunk_data['chunk_num'],
                    'result': f'Ошибка обработки части {chunk_data["chunk_num"]}: {str(e)}',
                    'error': True
                })
            
            # Небольшая задержка между запросами
            await asyncio.sleep(0.3)
        
        # Объединяем результаты чанков
        if chunking_config.get('combine_chunk_results', True):
            chunk_separator = chunking_config.get('chunk_result_separator', '\n\n--- Продолжение ---\n\n')
            combined_result = chunk_separator.join([r['result'] for r in chunk_results if not r.get('error')])
            
            # Добавляем ошибки в конец, если есть
            errors = [r['result'] for r in chunk_results if r.get('error')]
            if errors:
                combined_result += '\n\n⚠️ Ошибки при обработке:\n' + '\n'.join(errors)
            
            return {
                'filename': filename,
                'result': combined_result,
                'error': any(r.get('error') for r in chunk_results)
            }
        else:
            # Возвращаем результаты как есть
            return {
                'filename': filename,
                'result': chunk_results,
                'error': any(r.get('error') for r in chunk_results)
            }
    
    async def _process_single_content(
        self,
        user_id: str,
        filename: str,
        content: str,
        ai_query: str,
        ai_interface: Any,
        ai_provider: str,
        ai_model: str,
        ai_params: Dict
    ) -> Dict[str, Any]:
        """Обрабатывает единичный контент (файл или чанк)"""
        system_prompt = f"Файл: {filename}\nСодержимое:\n{content}"
        
        try:
            response = await ai_interface.send_simple_request(
                user_id=user_id,
                provider=ai_provider,
                prompt=ai_query,
                system_prompt=system_prompt,
                model=ai_model if ai_model != 'default' else None,
                **ai_params
            )
            
            if response:
                return {
                    'filename': filename,
                    'result': response,
                    'error': False
                }
            else:
                return {
                    'filename': filename,
                    'result': 'Ошибка: не удалось получить ответ от ИИ',
                    'error': True
                }
        
        except Exception as e:
            logger.error(f"Ошибка обработки файла {filename}: {e}")
            return {
                'filename': filename,
                'result': f'Ошибка обработки: {str(e)}',
                'error': True
            }
    
    async def process(
        self,
        user_id: str,
        query: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, str]:
        try:
            # Проверяем режим concatenate
            concatenate_config = self.config.get('concatenate_settings', {})
            if concatenate_config.get('enabled', False):
                # В режиме concatenate query содержит только селектор файлов
                return await self._process_concatenate(user_id, query, context)

            # Проверяем наличие виртуальных файлов в контексте
            if 'virtual_files' in context:
                virtual_files = context['virtual_files']
                lines = query.strip().split('\n', 1)
            
                if len(lines) < 2:
                    return False, "⌠Неверный формат запроса", ""
            
                file_selector = lines[0].strip()
                ai_query = lines[1].strip()
            
                # Для виртуальных файлов используем упрощенную обработку
                if file_selector in virtual_files:
                    file_content = virtual_files[file_selector]
                
                    ai_interface = context.get('ai_interface')
                    if not ai_interface:
                        return False, "ИИ интерфейс недоступен", ""
                
                    # Определяем провайдера
                    ai_settings = self.config.get('ai_settings', {})
                    ai_provider = ai_settings.get('provider', 'default')
                
                    if ai_provider == 'default':
                        if ai_interface.has_api_key('openai'):
                            ai_provider = 'openai'
                        elif ai_interface.has_api_key('anthropic'):
                            ai_provider = 'anthropic'
                        else:
                            return False, "Нет доступных API ключей", ""
                
                    # Подготавливаем параметры
                    ai_params = {}
                    if ai_provider == "openai":
                        ai_params["max_completion_tokens"] = ai_settings.get("max_completion_tokens", 4096)
                    else:
                        ai_params["max_tokens"] = ai_settings.get("max_tokens", 4096)
                    ai_params["temperature"] = ai_settings.get('temperature', 1.0)
                
                    # Отправляем запрос
                    response = await ai_interface.send_simple_request(
                        user_id=user_id,
                        provider=ai_provider,
                        prompt=ai_query,
                        system_prompt=f"Обработай следующий текст согласно запросу.\n\nТекст:\n{file_content}",
                        **ai_params
                    )
                
                    if response:
                        return True, "✅ Обработано", response
                    else:
                        return False, "Не удалось получить ответ от ИИ", ""
            
                return False, f"Виртуальный файл {file_selector} не найден", ""

            lines = query.strip().split('\n', 1)
            if len(lines) < 2:
                return False, "⌠Неверный формат запроса\\. Используйте:\n@filejob селектор\\_файлов\nзапрос для ИИ"
            
            file_selector = lines[0].strip()
            ai_query = lines[1].strip()
            
            if not ai_query:
                return False, "⌠Не указан запрос для обработки файлов"
            
            # Получаем список файлов
            codebase_manager = context.get('codebase_manager')
            file_manager = context.get('file_manager')
            ai_interface = context.get('ai_interface')
            
            if not all([codebase_manager, file_manager, ai_interface]):
                return False, "⌠Недостаточно компонентов для работы агента"
            
            # Получаем активную кодовую базу
            user_codebases = await codebase_manager.get_user_codebases(user_id)
            active_codebase_id = user_codebases.get('active')
            
            if not active_codebase_id:
                return False, "⌠Нет активной кодовой базы\\. Выберите базу командой /switch"
            
            # Получаем список всех файлов
            files_data = await file_manager.list_files_for_agent(
                user_id, active_codebase_id, page=1, per_page=1000
            )
            
            if not files_data.get('files'):
                return False, "⌠В активной кодовой базе нет файлов"
            
            available_files = [f['name'] for f in files_data['files']]
            
            # Парсим селектор и получаем выбранные файлы
            selected_files = self._parse_file_selector(file_selector, available_files)
            
            if not selected_files:
                return False, f"⌠Не найдено файлов по селектору: {escape_markdown_v2(file_selector)}"
            
            # Проверяем лимит
            max_files = self.config.get('max_files_per_job', 50)
            if len(selected_files) > max_files:
                return False, f"⌠Выбрано слишком много файлов ({len(selected_files)})\\. Максимум: {max_files}"
            
            # Создаем уникальный ID для задачи
            job_id = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.active_jobs[job_id] = {
                'user_id': user_id,
                'files': selected_files,
                'query': ai_query,
                'cancelled': False,
                'processed': 0,
                'results': []
            }
            
            # Обрабатываем файлы
            results = []
            processing_mode = self.config.get('processing_mode', 'independent')
            chunking_enabled = self.config.get('chunking', {}).get('enabled', False)
            
            # Настройки ИИ
            ai_settings = self.config.get('ai_settings', {})
            ai_provider = ai_settings.get('provider', 'default')
            ai_model = ai_settings.get('model', 'default')
            
            if ai_provider == 'default':
                if ai_interface.has_api_key('openai'):
                    ai_provider = 'openai'
                elif ai_interface.has_api_key('anthropic'):
                    ai_provider = 'anthropic'
                else:
                    return False, "⌠Нет доступных API ключей для ИИ провайдеров"
            
            # Подготовка параметров ИИ
            ai_params = {}
            if ai_provider == "openai":
                ai_params["max_completion_tokens"] = ai_settings.get("max_completion_tokens", ai_settings.get("max_tokens", None))
                ai_params["temperature"] = ai_settings.get('temperature', 1.0)
            else:
                ai_params["max_tokens"] = ai_settings.get("max_tokens", ai_settings.get("max_completion_tokens", None))
                ai_params["temperature"] = ai_settings.get('temperature', 1.0)
            
            # Обработка каждого файла
            for idx, filename in enumerate(selected_files):
                # Проверяем отмену
                if self.active_jobs[job_id]['cancelled']:
                    logger.info(f"Задача {job_id} отменена пользователем")
                    break
                
                # Обновляем прогресс
                self.active_jobs[job_id]['processed'] = idx + 1
                
                # Загружаем содержимое файла
                file_content = await file_manager.get_file_for_agent(
                    user_id, active_codebase_id, filename
                )
                
                if not file_content:
                    results.append({
                        'filename': filename,
                        'result': 'Ошибка: не удалось загрузить файл',
                        'error': True
                    })
                    continue
                
                try:
                    content = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    content = file_content.decode('latin-1')
                
                # Обрабатываем файл
                if chunking_enabled:
                    # Обработка с чанкированием
                    result = await self._process_file_with_chunks(
                        user_id,
                        filename, content, ai_query, ai_interface,
                        ai_provider, ai_model, ai_params, job_id
                    )
                else:
                    # Обычная обработка
                    if processing_mode == 'sequential' and results:
                        # Добавляем результаты предыдущих файлов
                        previous_results = "\n\n".join([
                            f"Файл {r['filename']}:\n{r['result']}" 
                            for r in results if not r.get('error')
                        ])
                        
                        system_prompt = f"""Предыдущие результаты обработки:
{previous_results}

Текущий файл: {filename}
Содержимое:
{content}"""
                    else:
                        system_prompt = f"Файл: {filename}\nСодержимое:\n{content}"
                    
                    try:
                        response = await ai_interface.send_simple_request(
                            user_id=user_id,
                            provider=ai_provider,
                            prompt=ai_query,
                            system_prompt=system_prompt,
                            model=ai_model if ai_model != 'default' else None,
                            **ai_params
                        )
                        
                        if response:
                            result = {
                                'filename': filename,
                                'result': response,
                                'error': False
                            }
                        else:
                            result = {
                                'filename': filename,
                                'result': 'Ошибка: не удалось получить ответ от ИИ',
                                'error': True
                            }
                    
                    except Exception as e:
                        logger.error(f"Ошибка обработки файла {filename}: {e}")
                        result = {
                            'filename': filename,
                            'result': f'Ошибка обработки: {str(e)}',
                            'error': True
                        }
                
                results.append(result)
                
                # Небольшая задержка между запросами
                await asyncio.sleep(0.5)
            
            # ВАЖНО: Этот блок должен быть ВНЕ цикла for, на том же уровне отступа!
            # Создаем архив с результатами
            temp_dir = None
            archive_path = None

            try:
                # Создаем временную директорию для результатов
                temp_dir = tempfile.mkdtemp(prefix="filejob_")
    
                # Сохраняем результаты в файлы
                saved_files_count = 0
                for result in results:
                    if not result.get('error'):
                        # Формируем имя файла результата
                        base_name, ext = os.path.splitext(result['filename'])
                        if not ext:
                            ext = '.txt'
                        result_filename = f"{base_name}_res.txt"
                        result_path = os.path.join(temp_dir, result_filename)
            
                        try:
                            with open(result_path, 'w', encoding='utf-8') as f:
                                f.write(result['result'])
                            saved_files_count += 1
                            logger.info(f"Сохранен файл результата: {result_filename}, размер: {len(result['result'])} символов")
                        except Exception as e:
                            logger.error(f"Ошибка сохранения результата для {result['filename']}: {e}")
                    else:
                        logger.warning(f"Пропущен файл с ошибкой: {result['filename']}")
    
                logger.info(f"Сохранено файлов для архива: {saved_files_count} из {len(results)}")
    
                # Создаем ZIP архив
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                archive_name = f"filejob_results_{timestamp}.zip"
                archive_path = os.path.join(temp_dir, archive_name)
    
                with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    files_added = 0
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            if file != archive_name:  # Не включаем сам архив
                                file_path = os.path.join(root, file)
                                arcname = os.path.relpath(file_path, temp_dir)
                                zipf.write(file_path, arcname)
                                files_added += 1
                    logger.info(f"Файлов добавлено в архив: {files_added}")
    
                # Проверяем размер архива
                archive_size = os.path.getsize(archive_path)
                logger.info(f"Создан архив {archive_name}, размер: {archive_size} байт")
    
                # Отправляем архив если есть message в контексте
                message = context.get('message')
                if message and os.path.exists(archive_path):
                    try:
                        file_size = os.path.getsize(archive_path)
                        size_mb = file_size / (1024 * 1024)
            
                        # Формируем статистику
                        processed = len(results)
                        errors = sum(1 for r in results if r.get('error'))
            
                        status_msg = f"✅ Обработано файлов: {processed}/{len(selected_files)}"
                        if errors > 0:
                            status_msg += f"\n⚠️ С ошибками: {errors}"
                        if processed < len(selected_files):
                            status_msg += f"\n⚠️ Задача была прервана"
                        status_msg += f"\n📦 Размер архива: {size_mb:.2f} МБ"
            
                        # Отправляем архив
                        document = FSInputFile(archive_path, filename=archive_name)
                        await message.reply_document(
                            document,
                            caption=f"Результаты обработки {processed} файлов\nЗапрос: {ai_query[:100]}..."
                        )
            
                        logger.info(f"Архив {archive_name} успешно отправлен")
            
                        # Удаляем задачу из активных
                        if job_id in self.active_jobs:
                            del self.active_jobs[job_id]
            
                        # Возвращаем успех без результата (архив уже отправлен)
                        return True, status_msg, None
            
                    except Exception as e:
                        logger.error(f"Ошибка отправки архива: {e}")
                        # Продолжаем с обычным возвратом результата
            
            except Exception as e:
                logger.error(f"Ошибка создания архива: {e}")
    
            finally:
                # Очистка временных файлов
                if temp_dir and os.path.exists(temp_dir):
                    try:
                        await asyncio.sleep(2)
                        shutil.rmtree(temp_dir)
                    except Exception as e:
                        logger.debug(f"Ошибка удаления временной директории: {e}")

            # Формируем итоговый результат (выполняется только если архив не был отправлен)
            final_result = self._format_results(results)

            # Удаляем задачу из активных
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]

            # Статистика
            processed = len(results)
            errors = sum(1 for r in results if r.get('error'))

            status_msg = f"✅ Обработано файлов: {processed}/{len(selected_files)}"
            if errors > 0:
                status_msg += f"\n⚠️ С ошибками: {errors}"
            if processed < len(selected_files):
                status_msg += f"\n⚠️ Задача была прервана"

            return True, status_msg, final_result
            
        except Exception as e:
            logger.error(f"Ошибка в Filejob агенте: {e}", exc_info=True)
            return False, f"⌠Ошибка обработки: {escape_markdown_v2(str(e))}"
    
    def _format_results(self, results: List[Dict]) -> str:
        """Форматирует результаты в итоговый документ"""
        separator = self.config.get('result_separator', '\n\n---\n\n')
        header_template = self.config.get('file_header_template', '# Файл: {filename}\n\n')
        include_source = self.config.get('include_source_in_result', False)
        
        formatted_parts = []
        
        # Специальная обработка для merged режима
        if len(results) == 1 and results[0].get('filename') == 'merged_result':
            return results[0]['result']
        
        # Обычная обработка для independent и sequential режимов
        for result in results:
            header = header_template.format(
                filename=result['filename'],
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
            
            content = header + result['result']
            formatted_parts.append(content)
        
        return separator.join(formatted_parts)
    
    def cancel_job(self, job_id: str) -> bool:
        """Отменяет активную задачу"""
        if job_id in self.active_jobs:
            self.active_jobs[job_id]['cancelled'] = True
            return True
        return False
    
    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Получает статус задачи"""
        return self.active_jobs.get(job_id)
    
    def get_config(self) -> Dict[str, Any]:
        return self.config.copy()
    
    def set_config(self, config: Dict[str, Any]):
        self.config = config