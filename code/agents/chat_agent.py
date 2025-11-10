# code/agents/chat_agent.py

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from utils.markdown_utils import escape_markdown_v2
from utils.info_utils import info_chat_help_message, info_cmd_chat_message 
from aiogram import types, F
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)

class ChatAgent:
    
    def __init__(self):
        self.name = "chat"
        self.config = self._load_default_config()
        
        # Храним историю и файлы внутри экземпляра агента
        self.chat_histories: Dict[str, List[Dict[str, str]]] = {}
        self.user_file_contexts: Dict[str, List[Dict[str, Any]]] = {}
        
        logger.info(f"ChatAgent инициализирован с локальным хранилищем")        

    def _load_default_config(self) -> Dict[str, Any]:
        config_path = os.path.join(os.path.dirname(__file__), "configs", "chat_default.json")
        
        default_config = {}
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    for key, value in loaded_config.items():
                        default_config[key] = value
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига Chat агента: {e}")
                
        return default_config


    def _delete_chat_history(self, user_id: str, chat_id: str) -> Tuple[bool, str]:
        """Удаление сохраненной истории чата"""
        try:
            from config import Config
        
            # Формируем путь к файлу
            histories_dir = os.path.join(Config.DATA_DIR, "chat_histories")
            filename = f"{user_id}_{chat_id}.json"
            filepath = os.path.join(histories_dir, filename)
        
            # Проверяем существование файла
            if not os.path.exists(filepath):
                return False, f"❌ История с ID {escape_markdown_v2(chat_id)} не найдена"
        
            # Проверяем, что это файл текущего пользователя
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data.get('user_id') != user_id:
                        return False, "❌ Эта история принадлежит другому пользователю"
            except:
                return False, "❌ Не удалось прочитать файл истории"
        
            # Удаляем файл
            os.remove(filepath)
            logger.info(f"История удалена: {filepath}")
        
            return True, f"🗑️ История с ID {escape_markdown_v2(chat_id)} удалена"
        
        except Exception as e:
            logger.error(f"Ошибка удаления истории: {e}", exc_info=True)
            return False, f"❌ Ошибка удаления: {escape_markdown_v2(str(e))}"

    def _rename_chat_history(self, user_id: str, old_id: str, new_id: str) -> Tuple[bool, str]:
        """Переименование сохраненной истории чата"""
        try:
            from config import Config
        
            # Проверяем валидность нового ID
            if not new_id.replace('_', '').replace('-', '').isalnum():
                return False, "❌ Новый ID может содержать только буквы, цифры, \\_ и \\-"
        
            histories_dir = os.path.join(Config.DATA_DIR, "chat_histories")
            old_filename = f"{user_id}_{old_id}.json"
            new_filename = f"{user_id}_{new_id}.json"
            old_filepath = os.path.join(histories_dir, old_filename)
            new_filepath = os.path.join(histories_dir, new_filename)
        
            # Проверяем существование старого файла
            if not os.path.exists(old_filepath):
                return False, f"❌ История с ID {escape_markdown_v2(old_id)} не найдена"
        
            # Проверяем, что новый файл не существует
            if os.path.exists(new_filepath):
                return False, f"❌ История с ID {escape_markdown_v2(new_id)} уже существует"
        
            # Проверяем владельца и обновляем chat_id в данных
            try:
                with open(old_filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data.get('user_id') != user_id:
                        return False, "❌ Эта история принадлежит другому пользователю"
                
                # Обновляем chat_id в данных
                data['chat_id'] = new_id
            
                # Сохраняем с новым именем
                with open(new_filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            
                # Удаляем старый файл
                os.remove(old_filepath)
            
            except Exception as e:
                logger.error(f"Ошибка при переименовании: {e}")
                return False, f"❌ Ошибка чтения/записи файла: {escape_markdown_v2(str(e))}"
        
            logger.info(f"История переименована: {old_filepath} -> {new_filepath}")
        
            return True, f"✏️ История переименована:\n{escape_markdown_v2(old_id)} → {escape_markdown_v2(new_id)}"
        
        except Exception as e:
            logger.error(f"Ошибка переименования истории: {e}", exc_info=True)
            return False, f"❌ Ошибка переименования: {escape_markdown_v2(str(e))}"

    def _save_chat_history(self, user_id: str, chat_id: str) -> Tuple[bool, str]:
        """Сохранение истории чата и файлов в файл"""
        try:
            from config import Config
        
            # Создаем директорию для хранения историй
            histories_dir = os.path.join(Config.DATA_DIR, "chat_histories")
            os.makedirs(histories_dir, exist_ok=True)
        
            # Формируем имя файла
            filename = f"{user_id}_{chat_id}.json"
            filepath = os.path.join(histories_dir, filename)
        
            # Подготавливаем данные для сохранения
            save_data = {
                'user_id': user_id,
                'chat_id': chat_id,
                'saved_at': datetime.now().isoformat(),
                'history': self._get_user_history(user_id),
                'files': self._get_user_files(user_id)
            }
        
            # Сохраняем в файл
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
        
            # Подсчитываем статистику
            history_count = len(save_data['history'])
            files_count = len(save_data['files'])
        
            logger.info(f"История чата сохранена: {filepath} (сообщений: {history_count}, файлов: {files_count})")
        
            return True, f"✅ История сохранена с ID: {escape_markdown_v2(chat_id)}\n📝 Сообщений: {history_count}\n📎 Файлов: {files_count}"
        
        except Exception as e:
            logger.error(f"Ошибка сохранения истории: {e}", exc_info=True)
            return False, f"❌ Ошибка сохранения: {escape_markdown_v2(str(e))}"

    def _load_chat_history(self, user_id: str, chat_id: str) -> Tuple[bool, str]:
        """Загрузка истории чата и файлов из файла"""
        try:
            from config import Config
        
            # Формируем путь к файлу
            histories_dir = os.path.join(Config.DATA_DIR, "chat_histories")
            filename = f"{user_id}_{chat_id}.json"
            filepath = os.path.join(histories_dir, filename)
        
            # Проверяем существование файла
            if not os.path.exists(filepath):
                return False, f"❌ История с ID {escape_markdown_v2(chat_id)} не найдена"
        
            # Загружаем данные
            with open(filepath, 'r', encoding='utf-8') as f:
                save_data = json.load(f)
        
            # Проверяем, что это история текущего пользователя
            if save_data.get('user_id') != user_id:
                return False, "❌ Эта история принадлежит другому пользователю"
        
            # Восстанавливаем историю
            if 'history' in save_data:
                self.chat_histories[user_id] = save_data['history']
            else:
                self.chat_histories[user_id] = []
        
            # Восстанавливаем файлы
            if 'files' in save_data:
                self.user_file_contexts[user_id] = save_data['files']
            else:
                self.user_file_contexts[user_id] = []
        
            # Подсчитываем статистику
            history_count = len(self.chat_histories[user_id])
            files_count = len(self.user_file_contexts[user_id])
            saved_at = save_data.get('saved_at', 'неизвестно')
        
            # Форматируем дату
            try:
                saved_date = datetime.fromisoformat(saved_at)
                date_str = saved_date.strftime('%d.%m.%Y %H:%M')
            except:
                date_str = saved_at
        
            logger.info(f"История чата загружена: {filepath} (сообщений: {history_count}, файлов: {files_count})")
        
            return True, f"✅ История загружена \\(ID: {escape_markdown_v2(chat_id)}\\)\n📅 Сохранена: {escape_markdown_v2(date_str)}\n📝 Сообщений: {history_count}\n📎 Файлов: {files_count}"
        
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            return False, "❌ Ошибка чтения файла истории \\(поврежден\\)"
        except Exception as e:
            logger.error(f"Ошибка загрузки истории: {e}", exc_info=True)
            return False, f"❌ Ошибка загрузки: {escape_markdown_v2(str(e))}"

    def _list_saved_histories(self, user_id: str) -> Tuple[bool, str]:
        """Получение списка сохраненных историй пользователя"""
        try:
            from config import Config
        
            histories_dir = os.path.join(Config.DATA_DIR, "chat_histories")
            if not os.path.exists(histories_dir):
                return True, "📂 У вас нет сохраненных историй"
        
            # Ищем файлы пользователя
            user_files = []
            prefix = f"{user_id}_"
        
            for filename in os.listdir(histories_dir):
                if filename.startswith(prefix) and filename.endswith('.json'):
                    # Извлекаем chat_id
                    chat_id = filename[len(prefix):-5]  # Убираем префикс и .json
                    filepath = os.path.join(histories_dir, filename)
                
                    # Пытаемся прочитать метаданные
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            saved_at = data.get('saved_at', 'неизвестно')
                            history_count = len(data.get('history', []))
                            files_count = len(data.get('files', []))
                        
                            user_files.append({
                                'chat_id': chat_id,
                                'saved_at': saved_at,
                                'messages': history_count,
                                'files': files_count
                            })
                    except:
                        # Если не удалось прочитать, добавляем с минимальной информацией
                        user_files.append({
                            'chat_id': chat_id,
                            'saved_at': 'неизвестно',
                            'messages': 0,
                            'files': 0
                        })
        
            if not user_files:
                return True, "📂 У вас нет сохраненных историй"
        
            # Сортируем по дате сохранения (новые первые)
            user_files.sort(key=lambda x: x['saved_at'], reverse=True)
        
            # Формируем ответ
            result = f"📚 *Ваши сохраненные истории \\({len(user_files)}\\):*\n"
        
            for item in user_files[:50]:  # Показываем максимум 50 последних
                try:
                    saved_date = datetime.fromisoformat(item['saved_at'])
                    date_str = saved_date.strftime('%d.%m %H:%M')
                except:
                    date_str = 'неизвестно'
            
                result += f"• ID: `{escape_markdown_v2(item['chat_id'])}` \\- {escape_markdown_v2(date_str)}\n"
                result += f"  📝 {item['messages']} сообщ\\., 📎 {item['files']} файлов\n"
        
            if len(user_files) > 50:
                result += f"\n_\\.\\.\\.и еще {len(user_files) - 50} историй_"
        
            result += "\n💡 Используйте:\n"
            result += "`save [ID]` \\- сохранить текущую\n"
            result += "`load [ID]` \\- загрузить историю"
        
            return True, result
        
        except Exception as e:
            logger.error(f"Ошибка получения списка историй: {e}", exc_info=True)
            return False, f"❌ Ошибка: {escape_markdown_v2(str(e))}"

        
    def _get_user_history(self, user_id: str) -> List[Dict[str, str]]:
        """Получить историю пользователя"""
        if user_id not in self.chat_histories:
            self.chat_histories[user_id] = []
        return self.chat_histories[user_id]
        
    def _get_user_files(self, user_id: str) -> List[Dict[str, str]]:
        """Получить список файлов пользователя"""
        if user_id not in self.user_file_contexts:
            self.user_file_contexts[user_id] = []
        return self.user_file_contexts[user_id]
        
    def add_file_context(self, user_id: str, filename: str, content: str) -> Dict[str, Any]:
        """Добавить файл в контекст пользователя"""
        file_context_config = self.config.get('file_context', {})
        multi_file_mode = file_context_config.get('multi_file_mode', 'merge')
        max_content_length = file_context_config.get('max_content_length', 200000)
        
        # В режиме "last" очищаем все предыдущие файлы
        if multi_file_mode == 'last':
            self.user_file_contexts[user_id] = []
            
        # Обрезаем содержимое если превышает лимит
        truncated = False
        original_size = len(content)
        
        if len(content) > max_content_length:
            content = content[:max_content_length]
            truncated = True
        
        # Инициализируем список если нужно
        if user_id not in self.user_file_contexts:
            self.user_file_contexts[user_id] = []
        
        # Добавляем файл
        self.user_file_contexts[user_id].append({
            'filename': filename,
            'content': content,
            'original_size': original_size,
            'truncated': truncated,
            'added_at': datetime.now().isoformat()
        })
        
        # Получаем обновленную информацию о файлах
        files_list = self.user_file_contexts[user_id]
        
        # Подсчет общего размера
        total_size = sum(len(f['content']) for f in files_list)
        total_original_size = sum(f['original_size'] for f in files_list)
        
        return {
            'files_count': len(files_list),
            'total_size': total_size,
            'total_original_size': total_original_size,
            'mode': multi_file_mode,
            'truncated': truncated,
            'last_file': filename
        }
       
    async def handle_document(self, message: types.Message, state: FSMContext, agent_handler):
        """Обработка документов в режиме чата"""
        user_id = str(message.from_user.id)
    
        if not message.document:
            return
    
        # Проверяем настройки файлового контекста
        file_config = self.config.get('file_context', {})
        if not file_config.get('enabled', True):
            await message.reply(
                "⚠️ Обработка файлов отключена в настройках этого агента.",
                parse_mode="MarkdownV2"
            )
            return
    
        # Проверяем тип файла
        from config import Config
        if not Config.is_text_file(message.document.file_name):
            await message.reply(
                "⚠️ В режиме чата поддерживаются только текстовые файлы\\.\n"
                "Для загрузки других файлов:\n"
                "1\\. Завершите чат командой /stop\n"
                "2\\. Загрузите файл обычным способом",
                parse_mode="MarkdownV2"
            )
            return
    
        # Проверяем размер файла
        max_file_size = file_config.get('max_content_length', 200000)
        if message.document.file_size > max_file_size:
            size_mb = max_file_size / (1024 * 1024)
            await message.reply(
                f"⚠️ Файл слишком большой\\.\n"
                f"Максимальный размер: {escape_markdown_v2(f'{size_mb:.1f}')} МБ\n\n"
                f"Попробуйте:\n"
                f"• Разделить файл на части\n"
                f"• Использовать /stop и загрузить в базу\n"
                f"• Изменить настройки агента",
                parse_mode="MarkdownV2"
            )
            return
    
        # Загружаем и обрабатываем файл
        processing_msg = await message.reply(f"📄 Загружаю файл для чата\\.\\.\\.", parse_mode="MarkdownV2")
    
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
        
            # Добавляем файл в контекст
            file_info = self.add_file_context(user_id, message.document.file_name, content)       
        
            await processing_msg.delete()
        
            # Формируем информационное сообщение
            await self._send_file_loaded_message(message, file_info, max_file_size)
        
        except Exception as e:
            logger.error(f"Ошибка загрузки файла в чат: {e}", exc_info=True)
            try:
                await processing_msg.delete()
            except:
                pass
            await message.reply(f"❌ Ошибка загрузки файла: {escape_markdown_v2(str(e))}", parse_mode="MarkdownV2")
   
    async def _send_file_loaded_message(self, message: types.Message, file_info: Dict, max_file_size: int):
        """Отправка сообщения об успешной загрузке файла"""
        if file_info['mode'] == 'merge':
            if file_info['files_count'] > 1:
                info_msg = f"✅ Файл *{escape_markdown_v2(message.document.file_name)}* добавлен в контекст чата\\.\n"
                info_msg += f"📚 Всего файлов в контексте: *{file_info['files_count']}*\n"
            
                # Форматируем размер
                if file_info['total_size'] >= 1024*1024:
                    size_mb = file_info['total_size']/(1024*1024)
                    size_str = f"{size_mb:.1f} МБ"
                elif file_info['total_size'] >= 1024:
                    size_kb = file_info['total_size']/1024
                    size_str = f"{size_kb:.1f} КБ"
                else:
                    size_str = f"{file_info['total_size']} байт"
            
                info_msg += f"📊 Общий размер: *{escape_markdown_v2(size_str)}*"
            
                if file_info['total_size'] < file_info['total_original_size']:
                    original_mb = file_info['total_original_size'] / (1024*1024)
                    info_msg += f"\n⚠️ Содержимое было обрезано с {escape_markdown_v2(f'{original_mb:.1f}')} МБ до лимита агента"
            
                info_msg += "\n\n💬 *Режим:* Объединение всех файлов"
                info_msg += "\n📄 Все файлы объединены в один контекст для ИИ"
            else:
                info_msg = f"✅ Файл *{escape_markdown_v2(message.document.file_name)}* загружен в контекст чата\\."
                if file_info['truncated']:
                    info_msg += f"\n⚠️ Файл был обрезан до {escape_markdown_v2(str(max_file_size))} символов из\\-за ограничений агента\\."
        else:  # mode == 'last'
            info_msg = f"✅ Файл *{escape_markdown_v2(message.document.file_name)}* заменил предыдущий контекст\\."
            info_msg += "\n\n💬 *Режим:* Только последний файл"
            if file_info['truncated']:
                info_msg += f"\n⚠️ Файл был обрезан до {escape_markdown_v2(str(max_file_size))} символов\\."
    
        info_msg += "\n\nТеперь вы можете задавать вопросы по содержимому файла\\(ов\\)\\."
        info_msg += "\n\n💡 _Используйте /stop для завершения чата и очистки файлов_"
    
        await message.reply(info_msg, parse_mode="MarkdownV2")

    def get_merged_file_context(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Получить объединенный контекст всех файлов"""
        if user_id not in self.user_file_contexts:
            return None
            
        files_list = self.user_file_contexts[user_id]
        
        if not files_list:
            return None
            
        file_context_config = self.config.get('file_context', {})
        
        if file_context_config.get('multi_file_mode', 'merge') == 'last':
            # В режиме "last" берем только последний файл
            if files_list:
                file_info = files_list[-1]
                return {
                    'filename': file_info['filename'],
                    'content': file_info['content'],
                    'files_count': 1,
                    'total_size': len(file_info['content']),
                    'original_size': file_info['original_size'],
                    'truncated': file_info['truncated']
                }
        else:
            # В режиме "merge" объединяем все файлы
            separator = file_context_config.get( 'merge_separator', "\n\n<file name='{filename}'>\n\n```{extension}\n")
            suffix = file_context_config.get('merge_suffix', "\n\n```\n\n</file>\n\n")
            max_length = file_context_config.get('max_content_length', 200000)
            
            merged_parts = []
            total_original_size = 0
            any_truncated = False
            
            for file_info in files_list:
                filename = file_info['filename']
                extension = os.path.splitext(filename)[1][1:] if '.' in filename else ''
                file_header = separator.format(filename=filename, extension=extension)
                merged_parts.append(file_header + file_info['content'] + suffix)
                total_original_size += file_info['original_size']
                if file_info['truncated']:
                    any_truncated = True
                    
            merged_content = ''.join(merged_parts)
            
            # Обрезаем общий результат, если превышает лимит
            merged_truncated = False
            if len(merged_content) > max_length:
                merged_content = merged_content[:max_length]
                merged_truncated = True
                
            filenames = [f['filename'] for f in files_list]
            
            return {
                'filename': ', '.join(filenames),  # Список файлов
                'content': merged_content,
                'files_count': len(files_list),
                'total_size': len(merged_content),
                'original_size': total_original_size,
                'truncated': any_truncated or merged_truncated,
                'filenames_list': filenames
            }
            
    def _add_to_history(self, user_id: str, role: str, content: str):
        """Добавить сообщение в историю"""
        history_config = self.config.get('history', {})
        
        if not history_config.get('enabled', True):
            logger.debug(f"История отключена в конфиге")
            return
        
        if user_id not in self.chat_histories:
            self.chat_histories[user_id] = []
        
        self.chat_histories[user_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        
        # Обрезаем историю если превышен лимит
        max_messages = history_config.get('max_messages', 20)
        if len(self.chat_histories[user_id]) > max_messages:
            self.chat_histories[user_id] = self.chat_histories[user_id][-max_messages:]
            
    def _clear_history(self, user_id: str):
        """Очистка истории и файлов (если настроено)"""
        # Очищаем историю
        if user_id in self.chat_histories:
            self.chat_histories[user_id] = []
            logger.info(f"История чата очищена для пользователя {user_id}")
        
        # Очищаем файлы, если включена опция
        history_config = self.config.get('history', {})
        if history_config.get('clear_files_on_history_clear', True):
            if user_id in self.user_file_contexts:
                files_count = len(self.user_file_contexts[user_id])
                self.user_file_contexts[user_id] = []
                if files_count > 0:
                    logger.info(f"Очищено {files_count} файлов для пользователя {user_id}")
                
    def _format_history_for_ai(self, user_id: str) -> List[Dict[str, str]]:
        history = self._get_user_history(user_id)
        history_config = self.config.get('history', {})
        
        formatted = []
        for msg in history:
            # Пропускаем системные сообщения если не настроено их включение
            if msg['role'] == 'system' and not history_config.get('include_system', False):
                continue
            
            formatted.append({
                "role": msg['role'],
                "content": msg['content']
            })
        
        logger.debug(f"Отформатировано {len(formatted)} сообщений для ИИ из {len(history)} в истории")
        return formatted
        
    def _check_context_change(self, user_id: str, new_context: Dict[str, Any]) -> bool:
        """Проверка изменения контекста - теперь учитывает множественные файлы"""
        last_file_content = new_context.get('last_file_content')
        
        history = self._get_user_history(user_id)
        
        # Ищем предыдущие метаданные файлов в истории
        for msg in reversed(history):
            if 'metadata' in msg:
                old_filenames = msg.get('metadata', {}).get('filenames', [])
                
                if last_file_content:
                    new_filenames = last_file_content.get('filenames_list', [last_file_content.get('filename')])
                    return old_filenames != new_filenames
                else:
                    # Были файлы, теперь нет
                    return True
        
        # Если метаданных не было в истории, но есть новые файлы - это изменение
        if last_file_content:
            return True
        
        return False
        
    async def process(
        self,
        user_id: str,
        query: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, str]:

        # Проверяем специальные команды для управления историей
        if query.lower().startswith('save '):
            chat_id = query[5:].strip()
            if not chat_id:
                return False, "❌ Укажите ID для сохранения: `save [ID]`"
            if not chat_id.replace('_', '').replace('-', '').isalnum():
                return False, "❌ ID может содержать только буквы, цифры, \\_ и \\-"
            return self._save_chat_history(user_id, chat_id)
    
        elif query.lower().startswith('load '):
            chat_id = query[5:].strip()
            if not chat_id:
                return False, "❌ Укажите ID для загрузки: `load [ID]`"
            return self._load_chat_history(user_id, chat_id)
    
        elif query.lower().startswith('delete '):
            chat_id = query[7:].strip()
            if not chat_id:
                return False, "❌ Укажите ID для удаления: `delete [ID]`"
            return self._delete_chat_history(user_id, chat_id)
    
        elif query.lower().startswith('rename '):
            parts = query[7:].strip().split()
            if len(parts) != 2:
                return False, "❌ Используйте: `rename [старый_ID] [новый_ID]`"
            return self._rename_chat_history(user_id, parts[0], parts[1])
    
        elif query.lower() == 'list':
            return self._list_saved_histories(user_id)
    
        elif query.lower() == 'help':
            help_text = info_cmd_chat_message()
            help_text += "\n" + info_chat_help_message()

            return True, help_text
        
        # Далее идет обычная обработка запроса
        try:
            ai_interface = context.get('ai_interface')
            user_manager = context.get('user_manager')
            
            if not ai_interface:
                return False, "❌ Нет доступа к ИИ интерфейсу"
                
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
                    
            history_config = self.config.get('history', {})
            
            # Проверка изменения контекста файлов
            if history_config.get('clear_on_context_change', False):
                if self._check_context_change(user_id, context):
                    self._clear_history(user_id)
                    logger.info(f"История очищена из-за изменения контекста для пользователя {user_id}")
                    
            system_prompt = self.config.get('system_prompt', '')
            
            # Обработка файлового контекста, получаем объединенный контекст
            merged_context = self.get_merged_file_context(user_id)

            if merged_context:
                system_prompt += merged_context['content']
                logger.info(f"Chat агент: добавлен контекст {merged_context['files_count']} файл(ов), общий размер {merged_context['total_size']} символов")
                
            # Формирование messages для ИИ
            messages = []
            
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            # ВАЖНО: Получаем историю ДО добавления нового сообщения пользователя
            if history_config.get('enabled', True):
                history_messages = self._format_history_for_ai(user_id)
                logger.debug(f"Добавляем {len(history_messages)} сообщений из истории в промпт")
                messages.extend(history_messages)
            
            # Добавляем текущий запрос пользователя в промпт
            messages.append({"role": "user", "content": query})
            
            # ВАЖНО: Добавляем user в историю ПОСЛЕ формирования промпта
            self._add_to_history(user_id, "user", query)
            
            logger.info(f"Отправка к ИИ: user_id={user_id}, провайдер={ai_provider}, модель={ai_model}, сообщений={len(messages)}")
                       
            # Отправляем запрос к ИИ
            ai_params = {}            
            if ai_provider == "openai":
                ai_params["max_completion_tokens"] = ai_settings.get("max_completion_tokens", ai_settings.get("max_tokens", None))
                ai_params["temperature"] = ai_settings.get('temperature', 1.0)
            else:
                ai_params["max_tokens"] = ai_settings.get("max_tokens", ai_settings.get("max_completion_tokens", None))
                ai_params["temperature"] = ai_settings.get('temperature', 1.0)
                
            response = await ai_interface.send_request(
                user_id=user_id,
                provider=ai_provider,
                messages=messages,
                model=ai_model if ai_model != 'default' else None,
                **ai_params
            )
            
            if not response:
                return False, "❌ Не удалось получить ответ от ИИ"
            
            logger.debug(f"Получен ответ от ИИ длиной {len(response)} символов")
                
            # ВАЖНО: Добавляем assistant в историю ПОСЛЕ получения ответа
            self._add_to_history(user_id, "assistant", response)
            
            result = escape_markdown_v2(response)           
                    
            if history_config.get('enabled', True) and history_config.get('show_history_info', False):
                history_len = len(self._get_user_history(user_id))
                result += f"\n\n📜 *История:* {history_len}/{history_config.get('max_messages', 20)} сообщений"
                
            return True, result
            
        except Exception as e:
            logger.error(f"Ошибка в Chat агенте: {e}", exc_info=True)
            return False, f"❌ Ошибка обработки: {escape_markdown_v2(str(e))}"
            
    def get_config(self) -> Dict[str, Any]:
        return self.config.copy()
        
    def set_config(self, config: Dict[str, Any]):
        config['owner_id'] = self.config.get('owner_id', 'system')
        config['access'] = self.config.get('access', 'public')
        config['type'] = 'chat'
        
        self.config = config
        
        if not config.get('history', {}).get('enabled', True):
            self.chat_histories.clear()
            logger.info("История чатов очищена из-за отключения в конфигурации")
            
    def clear_user_history(self, user_id: str) -> bool:
        """Публичный метод для очистки истории и файлов"""
        history_cleared = False
        
        if user_id in self.chat_histories:
            self.chat_histories[user_id] = []
            history_cleared = True
        
        # Очищаем файлы если настроено
        history_config = self.config.get('history', {})
        if history_config.get('clear_files_on_history_clear', True):
            if user_id in self.user_file_contexts:
                self.user_file_contexts[user_id] = []
        
        return history_cleared
        
    def clear_user_files(self, user_id: str) -> int:
        """Очистить только файлы пользователя"""
        if user_id not in self.user_file_contexts:
            return 0
        
        files_count = len(self.user_file_contexts[user_id])
        self.user_file_contexts[user_id] = []
        return files_count
        
    def get_user_history(self, user_id: str) -> List[Dict[str, str]]:
        """Получить копию истории пользователя"""
        return self._get_user_history(user_id).copy()
        
    def get_user_files_info(self, user_id: str) -> Dict[str, Any]:
        """Получить информацию о загруженных файлах пользователя"""
        files_list = self._get_user_files(user_id)
        
        return {
            'files_count': len(files_list),
            'files': [{'filename': f['filename'], 'size': f['original_size']} for f in files_list],
            'total_size': sum(f['original_size'] for f in files_list),
            'mode': self.config.get('file_context', {}).get('multi_file_mode', 'merge')
        }
        
    def export_history(self, user_id: str) -> str:
        """Экспортировать историю и файлы пользователя в текстовый формат"""
        history = self._get_user_history(user_id)
        files_info = self.get_user_files_info(user_id)
        
        if not history:
            return "История пуста"
            
        export_lines = ["# История чата\n"]
        
        # Добавляем информацию о файлах
        if files_info['files_count'] > 0:
            export_lines.append("## Загруженные файлы:\n")
            for file in files_info['files']:
                export_lines.append(f"- {file['filename']} ({file['size']} байт)")
            export_lines.append("\n---\n")
            
        for msg in history:
            timestamp = msg.get('timestamp', '')
            role = msg['role']
            content = msg['content']
            
            if role == 'user':
                export_lines.append(f"**Пользователь** ({timestamp}):")
            elif role == 'assistant':
                export_lines.append(f"**Ассистент** ({timestamp}):")
            elif role == 'system':
                export_lines.append(f"**Система** ({timestamp}):")
                
            export_lines.append(f"{content}\n")
            
        return "\n".join(export_lines)