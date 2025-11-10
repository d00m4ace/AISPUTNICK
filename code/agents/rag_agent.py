# code/agents/rag_agent.py

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from utils.markdown_utils import escape_markdown_v2
from utils.codebase_utils import _get_owner_params_and_settings
from aiogram import types, F
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)

class RagAgent:
    """RAG агент для поиска по кодовой базе с использованием ИИ"""
    
    def __init__(self):
        self.name = "rag"
        self.config = self._load_default_config()
        self.rag_manager = None  # Будет инициализирован при загрузке
        self.temp_document_context = {}  # {user_id: {'content': str, 'filename': str, 'timestamp': datetime}}


    async def handle_document(self, message: types.Message, state: FSMContext, agent_handler):
        """
        Обработка документов для RAG агента
        RAG может использовать документ как дополнительный контекст для поиска
        """
        user_id = str(message.from_user.id)
    
        # RAG агент принимает только текстовые файлы для анализа
        from config import Config
        if not Config.is_text_file(message.document.file_name):
            await message.reply(
                "⚠️ RAG агент поддерживает только текстовые файлы для анализа\\.\n\n"
                "Поддерживаемые форматы:\n"
                "• Код: \\.py, \\.js, \\.java, \\.cpp и др\\.\n"
                "• Текст: \\.txt, \\.md, \\.json, \\.xml и др\\.\n"
                "• Конфиги: \\.yaml, \\.ini, \\.conf и др\\.",
                parse_mode="MarkdownV2"
            )
            return
    
        processing_msg = await message.reply("📄 Загружаю документ для RAG анализа\\.\\.\\.", parse_mode="MarkdownV2")
    
        try:
            # Загрузка файла
            file = await agent_handler.bot.get_file(message.document.file_id)
            file_data = await agent_handler.bot.download_file(file.file_path)
        
            if hasattr(file_data, 'getvalue'):
                file_bytes = file_data.getvalue()
            else:
                file_bytes = file_data
        
            # Декодирование
            try:
                content = file_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    content = file_bytes.decode('cp1251')
                except:
                    content = file_bytes.decode('latin-1')
        
            # Сохраняем во временный контекст
            self.temp_document_context[user_id] = {
                'content': content,
                'filename': message.document.file_name,
                'timestamp': datetime.now(),
                'size': len(content)
            }
        
            await processing_msg.delete()
        
            # Анализируем содержимое для подсказок
            lines = content.split('\n')
            num_lines = len(lines)
        
            # Определяем тип файла
            file_ext = os.path.splitext(message.document.file_name)[1].lower()
            file_type = self._detect_file_type(file_ext, content)
        
            info_msg = f"✅ Документ *{escape_markdown_v2(message.document.file_name)}* загружен для RAG анализа\n\n"
            info_msg += f"📊 *Информация о файле:*\n"
            info_msg += f"• Тип: {escape_markdown_v2(file_type)}\n"
            info_msg += f"• Размер: {len(content):,} символов\n"
            info_msg += f"• Строк: {num_lines:,}\n\n"
        
            info_msg += "🔍 *Теперь вы можете:*\n"
            info_msg += "• Искать информацию в этом документе\n"
            info_msg += "• Сравнивать с файлами в базе знаний\n"
            info_msg += "• Анализировать код и структуру\n\n"
        
            info_msg += "💡 *Примеры запросов:*\n"
        
            # Подсказки в зависимости от типа файла
            if file_type == "Python код":
                info_msg += "`@rag найди все классы и их методы`\n"
                info_msg += "`@rag объясни что делает функция X`\n"
                info_msg += "`@rag найди похожий код в базе`\n"
            elif file_type == "JavaScript код":
                info_msg += "`@rag найди все экспорты`\n"
                info_msg += "`@rag какие зависимости используются`\n"
                info_msg += "`@rag найди похожие компоненты в базе`\n"
            elif file_type == "Конфигурация":
                info_msg += "`@rag какие параметры настроены`\n"
                info_msg += "`@rag сравни с конфигами в базе`\n"
                info_msg += "`@rag найди похожие настройки`\n"
            elif file_type == "Markdown":
                info_msg += "`@rag составь краткое резюме`\n"
                info_msg += "`@rag найди основные темы`\n"
                info_msg += "`@rag найди похожую документацию в базе`\n"
            else:
                info_msg += "`@rag что содержит этот файл`\n"
                info_msg += "`@rag найди ключевые элементы`\n"
                info_msg += "`@rag сравни с файлами в базе`\n"
        
            info_msg += f"\n⏱️ *Контекст активен 30 минут*"
            info_msg += f"\n\n💡 _Используйте /stop для завершения работы с агентом и очистки временного документа_"
        
            await message.reply(info_msg, parse_mode="MarkdownV2")
        
        except Exception as e:
            logger.error(f"Ошибка загрузки документа для RAG: {e}", exc_info=True)
            try:
                await processing_msg.delete()
            except:
                pass
            await message.reply(f"❌ Ошибка загрузки: {escape_markdown_v2(str(e))}", parse_mode="MarkdownV2")

    def _detect_file_type(self, ext: str, content: str) -> str:
        """Определение типа файла"""
        if ext in ['.py']:
            return "Python код"
        elif ext in ['.js', '.jsx', '.ts', '.tsx']:
            return "JavaScript код"
        elif ext in ['.java']:
            return "Java код"
        elif ext in ['.cpp', '.cc', '.c', '.h', '.hpp']:
            return "C/C++ код"
        elif ext in ['.cs']:
            return "C# код"
        elif ext in ['.go']:
            return "Go код"
        elif ext in ['.rs']:
            return "Rust код"
        elif ext in ['.json', '.yaml', '.yml', '.toml', '.ini', '.conf']:
            return "Конфигурация"
        elif ext in ['.md', '.markdown']:
            return "Markdown"
        elif ext in ['.txt', '.text']:
            return "Текстовый документ"
        elif ext in ['.sql']:
            return "SQL скрипт"
        elif ext in ['.html', '.htm']:
            return "HTML документ"
        elif ext in ['.css', '.scss', '.sass']:
            return "CSS стили"
        elif ext in ['.xml']:
            return "XML документ"
        else:
            # Пытаемся определить по содержимому
            if 'import ' in content or 'from ' in content:
                return "Код"
            elif content.strip().startswith('{') or content.strip().startswith('['):
                return "JSON данные"
            else:
                return "Текстовый файл"

    def _clean_expired_contexts(self):
        """Очистка устаревших контекстов (старше 30 минут)"""
        current_time = datetime.now()
        expired_users = []
    
        for user_id, context in self.temp_document_context.items():
            if (current_time - context['timestamp']).total_seconds() > 1800:  # 30 минут
                expired_users.append(user_id)
    
        for user_id in expired_users:
            del self.temp_document_context[user_id]
            logger.info(f"Очищен устаревший документный контекст для пользователя {user_id}")

        
    def _load_default_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации агента по умолчанию"""
        config_path = os.path.join(os.path.dirname(__file__), "configs", "rag_default.json")
        
        # Конфигурация по умолчанию если файл не найден
        default_config = {}
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    for key, value in loaded_config.items():
                        default_config[key] = value
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига RAG агента: {e}")
        
        return default_config
    
    def set_rag_manager(self, rag_manager):
        """Установка менеджера RAG"""
        self.rag_manager = rag_manager
    
    async def process(
        self,
        user_id: str,
        query: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Обработка запроса к RAG агенту с учетом временного документа
    
        Args:
            user_id: ID пользователя
            query: Запрос пользователя
            context: Контекст с managers (codebase_manager, file_manager, ai_interface)
        
        Returns:
            (success, response) - успех и ответ агента
        """
        try:
            # Очищаем устаревшие контексты
            self._clean_expired_contexts()
        
            codebase_manager = context.get('codebase_manager')
            ai_interface = context.get('ai_interface')
        
            if not all([codebase_manager, ai_interface, self.rag_manager]):
                return False, "❌ Недостаточно компонентов для работы RAG агента"
        
            # Определяем какую кодовую базу использовать
            if self.config.get('codebase') == 'default':
                # Используем активную базу пользователя
                user_codebases = await codebase_manager.get_user_codebases(user_id)
                active_codebase_id = user_codebases.get('active')
            
                if not active_codebase_id:
                    return False, "❌ Нет активной кодовой базы\\. Выберите базу командой /switch"
            
                logger.info(f"RAG: Используется активная база пользователя: {active_codebase_id}")
            else:
                # Используем указанную в конфиге базу
                active_codebase_id = self.config.get('codebase')
                logger.info(f"RAG: Используется база из конфига: {active_codebase_id}")
        
            # Получаем конфигурацию кодовой базы
            codebase_config = await codebase_manager.get_codebase_config(user_id, active_codebase_id)
            if not codebase_config:
                logger.error(f"RAG: Не найдена конфигурация для базы {active_codebase_id}")
                return False, f"❌ Не удалось получить конфигурацию кодовой базы '{escape_markdown_v2(active_codebase_id)}'"
        
            logger.info(f"RAG: Работаем с базой '{codebase_config['name']}' (ID: {active_codebase_id})")
        
            # Проверяем наличие временного документа
            temp_doc = self.temp_document_context.get(user_id)
            additional_context = ""
            temp_doc_info = None
        
            if temp_doc:
                # Проверяем актуальность (не старше 30 минут)
                time_diff = (datetime.now() - temp_doc['timestamp']).total_seconds()
                if time_diff <= 1800:
                    # Ограничиваем размер контекста из документа
                    max_doc_context = self.config.get('max_temp_document_size', 10000)
                    doc_content = temp_doc['content'][:max_doc_context]
                
                    additional_context = f"\n--- Загруженный документ: {temp_doc['filename']} ---\n"
                    additional_context += doc_content
                
                    if len(temp_doc['content']) > max_doc_context:
                        additional_context += f"\n... (показаны первые {max_doc_context} символов из {temp_doc['size']}) ..."
                
                    temp_doc_info = {
                        'filename': temp_doc['filename'],
                        'size': temp_doc['size'],
                        'time_remaining': int((1800 - time_diff) / 60)  # минут осталось
                    }
                
                    logger.info(f"RAG: Добавлен контекст документа {temp_doc['filename']} для пользователя {user_id}")
                else:
                    # Удаляем устаревший контекст
                    del self.temp_document_context[user_id]
                    logger.info(f"RAG: Удален устаревший контекст документа для пользователя {user_id}")
        
            # Используем утилиту для получения правильных параметров владельца
            owner_id, real_codebase_id, owner_rag_settings = _get_owner_params_and_settings(user_id, active_codebase_id)
        
            if owner_id != user_id:
                logger.info(f"RAG: Публичная база, владелец: {owner_id}, реальный ID: {real_codebase_id}")
            else:
                logger.info(f"RAG: Личная база пользователя {user_id}")
        
            # Путь к файлам базы
            codebase_dir = codebase_manager._get_codebase_dir(user_id, active_codebase_id)
            files_dir = os.path.join(codebase_dir, "files")
            logger.info(f"RAG: Путь к файлам: {files_dir}")
        
            # Проверяем статус индекса с правильными параметрами владельца
            index_status = await self.rag_manager.check_index_status(
                owner_id,
                real_codebase_id,
                files_dir
            )
        
            logger.info(f"RAG: Статус индекса - exists: {index_status.get('exists')}, needs_update: {index_status.get('needs_update')}")
        
            if not index_status.get('exists'):
                return False, f"❌ RAG индекс не найден для базы '{escape_markdown_v2(codebase_config['name'])}'\\. Выполните индексацию командой /index\\_rag"
        
            warning_msg = ""
            if index_status.get('needs_update'):
                warning_msg = f"⚠️ Внимание: {escape_markdown_v2(index_status.get('reason', 'Индекс требует обновления'))}\\. Рекомендуется обновить индекс\\.\n\n"
        
            # Подготавливаем настройки RAG
            rag_settings = self.config.get('rag_settings', {})
            # Если получили настройки владельца для публичной базы, используем их
            if owner_rag_settings:
                rag_settings.update(owner_rag_settings)
                logger.info(f"RAG: Используем настройки владельца базы")
        
            # Выполняем поиск по RAG
            search_results = await self.rag_manager.search(
                owner_id,
                real_codebase_id,
                query,
                top_k=rag_settings.get('max_context_chunks', 5)
            )
        
            logger.info(f"RAG: Найдено {len(search_results)} результатов поиска")
        
            # Строим контекст из результатов поиска
            rag_context = self._build_context_from_search(
                search_results,
                codebase_config['name'],
                rag_settings.get('search_threshold', 0.03)
            )
        
            # Формируем системный промпт
            system_prompt = self.config.get('system_prompt', '')
        
            # Добавляем контекст из загруженного документа
            if additional_context:
                system_prompt += f"\n\nКонтекст из загруженного документа:\n{additional_context}"
                logger.info(f"RAG: Добавлен временный документный контекст длиной {len(additional_context)} символов")
        
            # Добавляем контекст из RAG поиска
            if rag_context:
                system_prompt += f"\n\nКонтекст из кодовой базы '{codebase_config['name']}':\n{rag_context}"
                logger.info(f"RAG: Добавлен контекст из базы длиной {len(rag_context)} символов")
            elif not additional_context:
                # Если нет ни RAG контекста, ни документа
                logger.info("RAG: Контекст не добавлен - релевантные данные не найдены")
        
            # Определяем AI провайдера и модель
            ai_settings = self.config.get('ai_settings', {})
            ai_provider = ai_settings.get('provider', 'default')
            ai_model = ai_settings.get('model', 'default')
        
            if ai_provider == 'default':
                if ai_interface.has_api_key('openai'):
                    ai_provider = 'openai'
                elif ai_interface.has_api_key('anthropic'):
                    ai_provider = 'anthropic'
                else:
                    return False, "❌ Нет доступных API ключей для ИИ провайдеров"
        
            # Отправляем запрос к ИИ
            ai_params = {}
            if ai_provider == "openai":
                ai_params["max_completion_tokens"] = ai_settings.get("max_completion_tokens", ai_settings.get("max_tokens", None))
                ai_params["temperature"] = ai_settings.get('temperature', 1.0)
            else:
                ai_params["max_tokens"] = ai_settings.get("max_tokens", ai_settings.get("max_completion_tokens", None))
                ai_params["temperature"] = ai_settings.get('temperature', 1.0)
        
            response = await ai_interface.send_simple_request(
                user_id=user_id,
                provider=ai_provider,
                prompt=query,
                system_prompt=system_prompt,
                model=ai_model if ai_model != 'default' else None,
                **ai_params
            )
        
            if not response:
                return False, "❌ Не удалось получить ответ от ИИ"
        
            # Формируем финальный ответ с правильным экранированием
            result = escape_markdown_v2(response)
        
            # Добавляем информацию об использованных источниках
            sources_info = []
        
            # Информация о временном документе
            if temp_doc_info:
                sources_info.append(
                    f"📎 *Документ:* {escape_markdown_v2(temp_doc_info['filename'])} "
                    f"\\(активен еще {temp_doc_info['time_remaining']} мин\\)"
                )
        
            # Информация об использованных файлах из базы
            if search_results and rag_settings.get('include_filenames', True):
                files_used = list(set(r['filename'] for r in search_results))
                files_str = ", ".join([escape_markdown_v2(f) for f in files_used[:3]])
                if len(files_used) > 3:
                    files_str += f" и еще {len(files_used) - 3}"
                sources_info.append(f"📂 *Файлы из базы:* {files_str}")
        
            # Добавляем информацию об источниках
            if sources_info:
                result += "\n\n" + "\n".join(sources_info)
        
            # Добавляем информацию о базе
            result += f"\n\n📚 *База знаний:* {escape_markdown_v2(codebase_config['name'])}"
        
            # Добавляем статистику если включено
            if self.config.get('show_stats', False):
                stats = []
                if search_results:
                    avg_relevance = sum(r.get('relevance', 0) for r in search_results) / len(search_results)
                    stats.append(f"Релевантность: {avg_relevance:.2%}")
                if temp_doc_info:
                    stats.append(f"Документ: {temp_doc_info['size']:,} символов")
                if stats:
                    result += f"\n\n📊 *Статистика:* {', '.join(stats)}"
        
            if warning_msg:
                result = warning_msg + result
        
            return True, result
        
        except Exception as e:
            logger.error(f"Ошибка в RAG агенте: {e}", exc_info=True)
            return False, f"❌ Ошибка обработки: {escape_markdown_v2(str(e))}"

  
    def _build_context_from_search(
        self,
        search_results: List[Dict[str, Any]],
        codebase_name: str,
        threshold: float
    ) -> str:
        """Построение контекста из результатов поиска"""
        if not search_results:
            return ""
        
        # Фильтруем по порогу релевантности
        relevant_results = [
            r for r in search_results
            if r.get('relevance', 0) >= threshold
        ]
        
        if not relevant_results:
            # Берем топ-3 если ничего не прошло порог
            relevant_results = search_results[:3] if search_results else []
        
        # Группируем по файлам
        files_chunks = {}
        for result in relevant_results:
            filename = result['filename']
            if filename not in files_chunks:
                files_chunks[filename] = []
            files_chunks[filename].append(result)
        
        # Строим контекст
        context_parts = []
        for filename, chunks in files_chunks.items():
            context_parts.append(f"\n--- Файл: {filename} ---")
            
            # Сортируем чанки по индексу
            chunks.sort(key=lambda x: x.get('chunk_idx', 0))
            
            for chunk in chunks:
                text = chunk['text'].strip()
                if text:
                    context_parts.append(text)
        
        return "\n".join(context_parts)
    
    def get_config(self) -> Dict[str, Any]:
        """Получить текущую конфигурацию агента"""
        return self.config.copy()
    
    def set_config(self, config: Dict[str, Any]):
        """Установить новую конфигурацию агента"""
        # Сохраняем системные поля
        config['owner_id'] = self.config.get('owner_id', 'system')
        config['access'] = self.config.get('access', 'public')
        self.config = config