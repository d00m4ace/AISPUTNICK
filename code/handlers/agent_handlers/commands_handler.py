# code/handlers/agent_handlers/commands_handler.py

import logging
from datetime import datetime
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile
from utils.markdown_utils import escape_markdown_v2

logger = logging.getLogger(__name__)

class CommandsHandler:
    """Обработчик команд для управления агентами"""
    
    def __init__(self, parent_handler):
        self.parent = parent_handler
        self.bot = parent_handler.bot

    async def cmd_agent_stop(self, message: types.Message, state: FSMContext):
        """Универсальная команда остановки любого активного агента"""
        user_id = str(message.from_user.id)
    
        if not await self.parent.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
    
        stopped_agents = []
    
        # 1. Проверяем и останавливаем активный чат
        if hasattr(self.parent, 'chat_handler') and user_id in self.parent.chat_handler.active_chat_sessions:
            agent_name = self.parent.chat_handler.active_chat_sessions[user_id].get('agent_name', 'chat')
            del self.parent.chat_handler.active_chat_sessions[user_id]
            await state.clear()
            stopped_agents.append(('chat', agent_name))
            logger.info(f"Остановлен чат с агентом {agent_name} для пользователя {user_id}")
    
        # 2. Проверяем и останавливаем активные filejob задачи
        filejob_stopped = False
        if 'filejob' in self.parent.system_agents:
            filejob_agent = self.parent.system_agents['filejob']
            jobs_to_cancel = []
        
            # Находим все задачи пользователя
            for job_id, job_info in filejob_agent.active_jobs.items():
                if job_info['user_id'] == user_id and not job_info.get('cancelled', False):
                    jobs_to_cancel.append(job_id)
        
            # Отменяем найденные задачи
            for job_id in jobs_to_cancel:
                if filejob_agent.cancel_job(job_id):
                    filejob_stopped = True
                    logger.info(f"Отменена filejob задача {job_id} для пользователя {user_id}")
        
            if filejob_stopped:
                stopped_agents.append(('filejob', 'пакетная обработка'))
    
        # 3. Очищаем временные контексты для RAG
        rag_cleared = False
        if 'rag' in self.parent.system_agents:
            rag_agent = self.parent.system_agents['rag']
            if hasattr(rag_agent, 'temp_document_context') and user_id in rag_agent.temp_document_context:
                doc_info = rag_agent.temp_document_context[user_id]
                del rag_agent.temp_document_context[user_id]
                rag_cleared = True
                stopped_agents.append(('rag', f"документ {doc_info['filename']}"))
                logger.info(f"Очищен временный документ RAG для пользователя {user_id}")
    
        # 4. Очищаем информацию о последнем использованном агенте
        last_agent_cleared = False
        if hasattr(self.parent, '_last_agent_used'):
            if user_id in self.parent._last_agent_used:
                last_agent = self.parent._last_agent_used[user_id]
                del self.parent._last_agent_used[user_id]
                if user_id in self.parent._last_agent_used_time:
                    del self.parent._last_agent_used_time[user_id]
                last_agent_cleared = True
                logger.info(f"Очищена информация о последнем агенте {last_agent} для пользователя {user_id}")
    
        # 5. Очищаем временные файловые контексты всех агентов
        files_cleared = 0
    
        # ДОБАВЛЯЕМ: Очистка информации о последнем nethack агенте
        nethack_cleared = False
        if hasattr(self.parent, '_last_nethack_agent'):
            if user_id in self.parent._last_nethack_agent:
                last_nethack = self.parent._last_nethack_agent[user_id]
                del self.parent._last_nethack_agent[user_id]
                if user_id in self.parent._last_nethack_time:
                    del self.parent._last_nethack_time[user_id]
                nethack_cleared = True
                logger.info(f"Очищена информация о последнем nethack агенте {last_nethack} для пользователя {user_id}")
    
        # ДОБАВИТЬ: Очистка активной nethack сессии
        nethack_session_cleared = False
        if hasattr(self.parent, '_active_nethack_sessions'):
            if user_id in self.parent._active_nethack_sessions:
                session_info = self.parent._active_nethack_sessions[user_id]
                del self.parent._active_nethack_sessions[user_id]
                nethack_session_cleared = True
                logger.info(f"Завершена активная nethack сессия {session_info['agent_name']} для пользователя {user_id}")

        # Очищаем контексты в chat_handler
        if hasattr(self.parent, 'chat_handler') and hasattr(self.parent.chat_handler, 'user_file_contexts'):
            if user_id in self.parent.chat_handler.user_file_contexts:
                del self.parent.chat_handler.user_file_contexts[user_id]
                files_cleared += 1
    
        # Очищаем файлы в chat агенте
        if 'chat' in self.parent.system_agents:
            chat_agent = self.parent.system_agents['chat']
            if hasattr(chat_agent, 'user_file_contexts') and user_id in chat_agent.user_file_contexts:
                files_count = len(chat_agent.user_file_contexts[user_id])
                chat_agent.clear_user_files(user_id)
                files_cleared += files_count
    
        # Формируем ответ
        if stopped_agents or last_agent_cleared or files_cleared > 0:
            response = "✅ *Остановлены следующие агенты и процессы:*\n\n"
        
            for agent_type, details in stopped_agents:
                if agent_type == 'chat':
                    response += f"💬 Завершен чат с агентом *@{escape_markdown_v2(details)}*\n"
                elif agent_type == 'filejob':
                    response += f"📂 Отменена {escape_markdown_v2(details)} файлов\n"
                elif agent_type == 'rag':
                    response += f"🔍 Очищен временный контекст RAG: {escape_markdown_v2(details)}\n"
        
            if files_cleared > 0:
                response += f"📄 Очищено файловых контекстов: {files_cleared}\n"
        
            if last_agent_cleared:
                response += f"🔄 Сброшена привязка к последнему агенту\n"
        
            # В блоке формирования ответа добавить:
            if nethack_session_cleared:
                response += f"🌐 Завершена активная nethack сессия\n"

            response += "\n_Теперь вы можете начать новую работу с любым агентом_"
        
            await message.reply(response, parse_mode="MarkdownV2")
        else:
            await message.reply(
                "ℹ️ *Нет активных агентов или процессов*\n\n"
                "Все агенты уже остановлены\\.",
                parse_mode="MarkdownV2"
            )

    async def cmd_agent_status(self, message: types.Message):
        """Показать статус всех активных агентов и процессов"""
        user_id = str(message.from_user.id)

        if not await self.parent.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return

        active_items = []

        # Проверяем активный чат
        if hasattr(self.parent, 'chat_handler') and user_id in self.parent.chat_handler.active_chat_sessions:
            session = self.parent.chat_handler.active_chat_sessions[user_id]
            agent_name = session.get('agent_name', 'chat')
            started_at = session.get('started_at', 'неизвестно')
        
            # Получаем агента для дополнительной информации
            agent = await self.parent._get_agent_instance(user_id, agent_name)
            extra_info = ""
            if agent and hasattr(agent, 'get_user_files_info'):
                files_info = agent.get_user_files_info(user_id)
                if files_info['files_count'] > 0:
                    extra_info = f"\n   📁 Файлов: {files_info['files_count']}"
        
            active_items.append(f"💬 *Активный чат:* @{escape_markdown_v2(agent_name)}\n   Начат: {escape_markdown_v2(started_at[:19] if started_at != 'неизвестно' else started_at)}{extra_info}")

        # Проверяем активные filejob задачи
        if 'filejob' in self.parent.system_agents:
            filejob_agent = self.parent.system_agents['filejob']
            user_jobs = []
            for job_id, job_info in filejob_agent.active_jobs.items():
                if job_info['user_id'] == user_id and not job_info.get('cancelled', False):
                    processed = job_info.get('processed', 0)
                    total = len(job_info.get('files', []))
                    user_jobs.append(f"   Задача: {processed}/{total} файлов")
    
            if user_jobs:
                active_items.append(f"📂 *Активные filejob задачи:*\n" + "\n".join(user_jobs))

        # Проверяем временные документы RAG
        if 'rag' in self.parent.system_agents:
            rag_agent = self.parent.system_agents['rag']
            if hasattr(rag_agent, 'temp_document_context') and user_id in rag_agent.temp_document_context:
                doc_info = rag_agent.temp_document_context[user_id]
                time_diff = (datetime.now() - doc_info['timestamp']).total_seconds()
                time_remaining = int((1800 - time_diff) / 60)
                if time_remaining > 0:
                    active_items.append(f"🔍 *RAG документ:* {escape_markdown_v2(doc_info['filename'])}\n   Активен ещё: {time_remaining} мин")

        # Проверяем последнее использование агента
        if hasattr(self.parent, '_last_agent_used') and user_id in self.parent._last_agent_used:
            last_agent = self.parent._last_agent_used[user_id]
            last_time = self.parent._last_agent_used_time.get(user_id)
            if last_time:
                time_ago = int((datetime.now() - last_time).total_seconds() / 60)
                if time_ago < 5:
                    active_items.append(f"📄 *Последний агент:* @{escape_markdown_v2(last_agent)}\n   Использован: {time_ago} мин назад")

        # ДОБАВИТЬ: Проверка активной nethack сессии
        if hasattr(self.parent, '_active_nethack_sessions') and user_id in self.parent._active_nethack_sessions:
            session = self.parent._active_nethack_sessions[user_id]
            agent_name = session['agent_name']
            elapsed = int((datetime.now() - session['started_at']).total_seconds() / 60)
            remaining = 60*24 - elapsed
            if remaining > 0:
                active_items.append(
                    f"🌐 *Активная nethack сессия:* @{escape_markdown_v2(agent_name)}\n"
                    f"   _Пишите вопросы без @{escape_markdown_v2(agent_name)}_"
                )

        # Проверяем загруженные файлы в chat агенте
        if 'chat' in self.parent.system_agents:
            chat_agent = self.parent.system_agents['chat']
            if hasattr(chat_agent, 'get_user_files_info'):
                files_info = chat_agent.get_user_files_info(user_id)
                if files_info['files_count'] > 0:
                    active_items.append(f"📄 *Загружено файлов в чат:* {files_info['files_count']}\n   Общий размер: {files_info['total_size']:,} байт")

        if active_items:
            response = "📊 *Статус активных агентов и процессов:*\n\n"
            response += "\n\n".join(active_items)
            response += "\n\n_Используйте /agent\\_stop для остановки всех процессов_"
        else:
            response = "ℹ️ *Нет активных агентов или процессов*\n\n"
            response += "Вы можете начать работу с любым агентом:\n"
            response += "• `@chat` \\- начать чат\n"
            response += "• `@rag запрос` \\- поиск в базе\n"
            response += "• `@filejob` \\- обработка файлов"

        await message.reply(response, parse_mode="MarkdownV2")
    
        
    async def cmd_agents(self, message: types.Message):
        """Обновленная команда /agents с динамическими макро-командами"""
        user_id = str(message.from_user.id)
        
        if not await self.parent.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
        
        text = "*🤖 Система ИИ агентов*\n\n"
        text += "*Как использовать агентов:*\n"
        text += "`@имя_агента` \\<запрос\\> \\- вызов агента с запросом\n"
        text += "`@chat` \\- начать чат с ИИ\n"
        text += "`/stop_chat` \\- завершить активный чат\n\n"
        
        text += "*Системные агенты \\(доступны всем\\):*\n"
        
        for agent_name, agent in self.parent.system_agents.items():
            config = agent.get_config()
            # Делаем имя копируемым
            text += f"• `@{agent_name}` \\- {escape_markdown_v2(config.get('description', 'Без описания'))}\n"
            
            if agent_name == 'chat' or config.get('type') == 'chat':
                text += "  💬 Чат\\-режим с поддержкой файлов\n"
                # Получаем режим файлов
                file_config = config.get('file_context', {})
                multi_mode = file_config.get('multi_file_mode', 'merge')
                if multi_mode == 'merge':
                    text += "  📚 Режим: объединение файлов\n"
                else:
                    text += "  📄 Режим: только последний файл\n"
            
            elif agent_name == 'filejob' or config.get('type') == 'fileworker':
                text += "  📂 Пакетная обработка файлов\n"
            
            elif agent_name == 'rag' or config.get('type') == 'rag':
                text += "  🔍 Интеллектуальный поиск по базе\n"

            elif agent_name == 'nethack' or config.get('type') == 'nethack':
                text += "  🌐 Поиск ответов в документах из сети\n"
        
        # Добавляем секцию макро-команд
        text += "\n*📋 Быстрые макро команды:*\n"
        text += "_Используйте после конвертации файла в \\.md формат_\n\n"
        
        # Получаем приоритетные макро-команды динамически
        priority_macros = self.parent.get_priority_macro_commands(limit=5)
        
        for cmd_name, description in priority_macros:
            text += f"• `@{cmd_name}` \\- {escape_markdown_v2(description)}\n"
        
        # Получаем общее количество макро-команд
        total_macros = len(self.parent.macro_commands.get_all_commands())
        shown_macros = len(priority_macros)
        
        if total_macros > shown_macros:
            text += f"\n_\\.\\.\\.и ещё {total_macros - shown_macros} команд_\n"
            text += "Используйте `@macros` для полного списка\n"
        
        text += "\n*💬 Работа в чат\\-режиме:*\n"
        text += "• Отправьте `@chat` для активации\n"
        text += "• Загружайте файлы для контекста\n"
        text += "• `/stop_chat` \\- завершить чат\n\n"
        
        text += "*📄 Управление историей:*\n"
        text += "`/clear_history` \\- очистить историю и файлы\n"
        text += "`/export_history` \\- экспорт в файл\n"
        text += "`/history_info` \\- статистика и файлы\n\n"
        
        text += "*🔧 Управление агентами:*\n"
        text += "`/agent_stop` \\- остановить все активные агенты\n"
        text += "`/agent_status` \\- статус активных процессов\n"
        text += "`/stop_chat` \\- завершить чат \\(алиас\\)\n\n"

        text += "*Дополнительные команды:*\n"
        text += "`/agents_pub` \\- публичные агенты\n"
        text += "`/agents_user` \\- ваши личные агенты\n"
        
        # Проверяем активный чат
        if hasattr(self.parent, 'chat_handler') and user_id in self.parent.chat_handler.active_chat_sessions:
            agent_name = self.parent.chat_handler.active_chat_sessions[user_id].get('agent_name', 'chat')
            text += f"\n*🟢 Активный чат:* `@{agent_name}`\n"
            
            # Показываем информацию о загруженных файлах если есть
            if agent_name in self.parent.system_agents:
                agent = self.parent.system_agents[agent_name]
                if hasattr(agent, 'get_user_files_info'):
                    files_info = agent.get_user_files_info(user_id)
                    if files_info['files_count'] > 0:
                        text += f"📚 Загружено файлов: {files_info['files_count']}\n"
            
            text += "Используйте `/stop_chat` для завершения\n"
        
        text += "\n_💡 Нажмите на имя агента для копирования_"
        
        await message.reply(text, parse_mode="MarkdownV2")
        
    async def cmd_agents_pub(self, message: types.Message):
        """Список публичных агентов"""
        user_id = str(message.from_user.id)
        
        if not await self.parent.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
        
        if not self.parent.public_agents:
            await message.reply("*📢 Публичные агенты*\n\nПока нет публичных агентов\\.", parse_mode="MarkdownV2")
            return
        
        text = "*📢 Публичные агенты:*\n\n"
        
        for agent_name, agent_data in self.parent.public_agents.items():
            config = agent_data.get('config', {})
            owner_id = agent_data.get('owner_id', 'unknown')
            agent_type = config.get('type', 'unknown')
            
            # Делаем имя агента копируемым через inline код
            text += f"• `@{agent_name}`"
            
            # Добавляем эмодзи для типа агента
            if agent_type == 'chat':
                text += " 💬"
            elif agent_type == 'rag':
                text += " 🔍"
            elif agent_type == 'fileworker':
                text += " 📂"
            
            text += f"\n"
            text += f"  {escape_markdown_v2(config.get('description', 'Без описания'))}\n\n"
        
        # Добавляем подсказку
        text += "_💡 Нажмите на имя агента для копирования_"
        
        await message.reply(text, parse_mode="MarkdownV2")
        
    async def cmd_agents_user(self, message: types.Message):
        """Список личных агентов пользователя"""
        user_id = str(message.from_user.id)
        
        if not await self.parent.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
        
        user_agents = self.parent.user_agents.get(user_id, {})
        
        if not user_agents:
            text = "*👤 Ваши личные агенты*\n\n"
            text += "У вас пока нет личных агентов\\.\n\n"
            text += "Чтобы создать агента:\n"
            text += "1\\. Скачайте конфигурацию системного агента: `@rag config` или `@chat config`\n"
            text += "2\\. Отредактируйте \\.json файл\n"
            text += "3\\. Отправьте файл боту для создания агента"
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        text = "*👤 Ваши личные агенты:*\n\n"
        
        for agent_name, config in user_agents.items():
            agent_type = config.get('type', 'unknown')
            
            # Делаем имя агента копируемым
            text += f"• `@{agent_name}`"
            
            # Добавляем эмодзи для типа
            if agent_type == 'chat':
                text += " 💬"
            elif agent_type == 'rag':
                text += " 🔍"
            elif agent_type == 'fileworker':
                text += " 📂"
            
            text += f"\n"
            text += f"  {escape_markdown_v2(config.get('description', 'Без описания'))}\n\n"
        
        text += "_💡 Нажмите на имя агента для копирования_"
        
        await message.reply(text, parse_mode="MarkdownV2")
        
    async def cmd_stop_chat(self, message: types.Message, state: FSMContext):
        """Остановка активного чата"""
        user_id = str(message.from_user.id)
        
        if hasattr(self.parent, 'chat_handler') and user_id in self.parent.chat_handler.active_chat_sessions:
            agent_name = self.parent.chat_handler.active_chat_sessions[user_id].get('agent_name', 'chat')
            del self.parent.chat_handler.active_chat_sessions[user_id]
            await state.clear()
            await message.reply(
                f"✅ Чат с агентом *@{escape_markdown_v2(agent_name)}* завершен\\.\n\n"
                "Вы можете начать новый чат или использовать команды\\.",
                parse_mode="MarkdownV2"
            )
        else:
            await message.reply("У вас нет активного чата\\.", parse_mode="MarkdownV2")

    async def cmd_clear_history(self, message: types.Message):
        """Очистка истории и всех загруженных файлов"""
        user_id = str(message.from_user.id)
    
        if not await self.parent.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
    
        # Получаем chat агента (активного или последнего использованного)
        chat_agent = None
    
        # 1. Проверяем активный чат
        if hasattr(self.parent, 'chat_handler') and user_id in self.parent.chat_handler.active_chat_sessions:
            agent_name = self.parent.chat_handler.active_chat_sessions[user_id].get('agent_name', 'chat')
            chat_agent = await self.parent._get_agent_instance(user_id, agent_name)
    
        # 2. Если нет активного, проверяем последнего использованного chat агента
        if not chat_agent and hasattr(self.parent, '_last_agent_used'):
            last_agent = self.parent._last_agent_used.get(user_id)
            if last_agent:
                agent = await self.parent._get_agent_instance(user_id, last_agent)
                if agent and hasattr(agent, 'get_config'):
                    config = agent.get_config()
                    if config.get('type') == 'chat':
                        chat_agent = agent
    
        # 3. Если всё ещё нет, получаем системный chat агент
        if not chat_agent:
            chat_agent = self.parent.system_agents.get('chat')
    
        if not chat_agent:
            await message.reply("❌ Chat агент не найден", parse_mode="MarkdownV2")
            return
    
        # Получаем информацию перед очисткой
        files_info = None
        if hasattr(chat_agent, 'get_user_files_info'):
            files_info = chat_agent.get_user_files_info(user_id)
    
        if chat_agent.clear_user_history(user_id):
            msg = "✅ *История чата очищена*\n\n"
        
            # Добавляем информацию об очищенных файлах
            if files_info and files_info['files_count'] > 0:
                msg += f"🗑️ Также удалено файлов: *{files_info['files_count']}*\n"
                if files_info['total_size'] >= 1024*1024:
                    size_str = f"{files_info['total_size']/(1024*1024):.1f} МБ"
                elif files_info['total_size'] >= 1024:
                    size_str = f"{files_info['total_size']/1024:.1f} КБ"
                else:
                    size_str = f"{files_info['total_size']} байт"
                msg += f"📊 Освобождено: *{escape_markdown_v2(size_str)}*\n\n"
        
            msg += "Теперь вы можете начать новый разговор с чистого листа\\."
        
            await message.reply(msg, parse_mode="MarkdownV2")
        else:
            await message.reply(
                "ℹ️ *История уже пуста*\n\n"
                "У вас нет сохраненной истории чата\\.",
                parse_mode="MarkdownV2"
            )            

        chat_agent.clear_user_files(user_id)
       
    async def cmd_export_history(self, message: types.Message):
        """Экспортировать историю чата в файл"""
        user_id = str(message.from_user.id)
    
        if not await self.parent.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
    
        # Получаем chat агента
        chat_agent = None
    
        # 1. Проверяем активный чат
        if hasattr(self.parent, 'chat_handler') and user_id in self.parent.chat_handler.active_chat_sessions:
            agent_name = self.parent.chat_handler.active_chat_sessions[user_id].get('agent_name', 'chat')
            chat_agent = await self.parent._get_agent_instance(user_id, agent_name)
    
        # 2. Если нет активного, проверяем последнего использованного chat агента
        if not chat_agent and hasattr(self.parent, '_last_agent_used'):
            last_agent = self.parent._last_agent_used.get(user_id)
            if last_agent:
                agent = await self.parent._get_agent_instance(user_id, last_agent)
                if agent and hasattr(agent, 'get_config'):
                    config = agent.get_config()
                    if config.get('type') == 'chat':
                        chat_agent = agent
    
        # 3. Если всё ещё нет, получаем системный chat агент
        if not chat_agent:
            chat_agent = self.parent.system_agents.get('chat')
    
        if not chat_agent:
            await message.reply("❌ Chat агент не найден", parse_mode="MarkdownV2")
            return
    
        # Экспортируем историю
        history_text = chat_agent.export_history(user_id)
    
        if history_text == "История пуста":
            await message.reply(
                "ℹ️ *История пуста*\n\n"
                "У вас нет сохраненных сообщений в истории чата\\.",
                parse_mode="MarkdownV2"
            )
            return
    
        # Создаем файл с историей
        file_content = f"# Экспорт истории чата\n\n"
        file_content += f"**Пользователь:** {message.from_user.full_name}\n"
        file_content += f"**ID:** {user_id}\n"
        file_content += f"**Дата экспорта:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        file_content += "---\n\n"
        file_content += history_text
    
        file_bytes = file_content.encode('utf-8')
        input_file = BufferedInputFile(
            file=file_bytes,
            filename=f"chat_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
    
        await message.reply_document(
            document=input_file,
            caption="📜 *Экспорт истории чата*\n\nВаша история сохранена в файл",
            parse_mode="MarkdownV2"
        )

    async def cmd_history_info(self, message: types.Message):
        """Информация об истории чата и загруженных файлах"""
        user_id = str(message.from_user.id)
        
        if not await self.parent.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
        
        # Получаем chat агента (пытаемся найти активного или закэшированного)
        chat_agent = None
        
        # 1. Проверяем активный чат
        if hasattr(self.parent, 'chat_handler') and user_id in self.parent.chat_handler.active_chat_sessions:
            agent_name = self.parent.chat_handler.active_chat_sessions[user_id].get('agent_name', 'chat')
            chat_agent = await self.parent._get_agent_instance(user_id, agent_name)
        
        # 2. Если нет активного чата, проверяем последнего использованного chat агента
        if not chat_agent and hasattr(self.parent, '_last_agent_used'):
            last_agent = self.parent._last_agent_used.get(user_id)
            if last_agent:
                agent = await self.parent._get_agent_instance(user_id, last_agent)
                if agent and hasattr(agent, 'get_config'):
                    config = agent.get_config()
                    if config.get('type') == 'chat':
                        chat_agent = agent
        
        # 3. Если всё ещё нет, получаем системный chat агент
        if not chat_agent:
            chat_agent = self.parent.system_agents.get('chat')
        
        if not chat_agent or not hasattr(chat_agent, 'get_user_history'):
            await message.reply("❌ Chat агент не найден", parse_mode="MarkdownV2")
            return
        
        # Получаем данные из агента
        history = chat_agent.get_user_history(user_id)
        config = chat_agent.get_config()
        history_config = config.get('history', {})
        file_config = config.get('file_context', {})
        
        # Подсчитываем сообщения по ролям
        user_messages = sum(1 for msg in history if msg['role'] == 'user')
        assistant_messages = sum(1 for msg in history if msg['role'] == 'assistant')
        system_messages = sum(1 for msg in history if msg['role'] == 'system')
        
        text = "*📊 Информация об истории чата*\n\n"
        
        text += "*Настройки:*\n"
        text += f"• История: {'✅ Включена' if history_config.get('enabled', True) else '❌ Отключена'}\n"
        text += f"• Максимум сообщений: {escape_markdown_v2(str(history_config.get('max_messages', 20)))}\n"
        text += f"• Системные промпты: {'✅ Сохраняются' if history_config.get('include_system', False) else '❌ Не сохраняются'}\n"
        text += f"• Очистка при смене файла: {'✅ Да' if history_config.get('clear_on_context_change', True) else '❌ Нет'}\n"
        text += f"• Очистка файлов с историей: {'✅ Да' if history_config.get('clear_files_on_history_clear', True) else '❌ Нет'}\n\n"
        
        text += "*Режим файлов:*\n"
        multi_mode = file_config.get('multi_file_mode', 'merge')
        if multi_mode == 'merge':
            text += "• 📚 Объединение всех файлов в один контекст\n"
        else:
            text += "• 📄 Только последний загруженный файл\n"
        text += f"• Макс\\. размер: {escape_markdown_v2(str(file_config.get('max_content_length', 200000)))} символов\n\n"
        
        text += "*Текущая история:*\n"
        text += f"• Всего сообщений: {len(history)}\n"
        text += f"• Сообщений пользователя: {user_messages}\n"
        text += f"• Ответов ассистента: {assistant_messages}\n"
        if system_messages > 0:
            text += f"• Системных сообщений: {system_messages}\n"
        
        # Информация о загруженных файлах
        if hasattr(chat_agent, 'get_user_files_info'):
            files_info = chat_agent.get_user_files_info(user_id)
            if files_info['files_count'] > 0:
                text += "\n*Загруженные файлы:*\n"
                text += f"• Количество: {files_info['files_count']}\n"
                
                # Показываем первые 5 файлов
                for i, file in enumerate(files_info['files'][:5]):
                    text += f"  {i+1}\\. {escape_markdown_v2(file['filename'])} "
                    if file['size'] >= 1024:
                        size_kb = file['size']/1024
                        text += f"\\({escape_markdown_v2(f'{size_kb:.1f}')} КБ\\)\n"
                    else:
                        text += f"\\({file['size']} байт\\)\n"
                    
                if files_info['files_count'] > 5:
                    # Экранируем три точки
                    text += f"  \\.\\.\\.и ещё {files_info['files_count'] - 5} файлов\n"
                
                if files_info['total_size'] >= 1024*1024:
                    size_mb = files_info['total_size']/(1024*1024)
                    text += f"• Общий размер: {escape_markdown_v2(f'{size_mb:.1f}')} МБ\n"
                elif files_info['total_size'] >= 1024:
                    size_kb = files_info['total_size']/1024
                    text += f"• Общий размер: {escape_markdown_v2(f'{size_kb:.1f}')} КБ\n"
                else:
                    text += f"• Общий размер: {files_info['total_size']} байт\n"
        
        if history:
            first_time = history[0].get('timestamp', 'неизвестно')
            last_time = history[-1].get('timestamp', 'неизвестно')
            
            text += f"\n• Первое сообщение: {escape_markdown_v2(first_time[:19] if first_time != 'неизвестно' else first_time)}\n"
            text += f"• Последнее сообщение: {escape_markdown_v2(last_time[:19] if last_time != 'неизвестно' else last_time)}\n"
        
        text += "\n*Команды управления:*\n"
        text += "/clear\\_history \\- очистить историю и файлы\n"
        text += "/export\\_history \\- экспортировать в файл\n"
        
        await message.reply(text, parse_mode="MarkdownV2")