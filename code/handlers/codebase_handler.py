# code/handlers/codebase_handler.py
"""
Модуль обработки операций с кодовыми базами
"""

import os
import re
import json
import logging
from datetime import datetime
from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from agents.rag_singleton import get_rag_manager
from utils.markdown_utils import escape_markdown_v2

# Используем относительные импорты
from handlers.public_access_handler import PublicAccessHandler
from handlers.codebase_visibility_handler import CodebaseVisibilityHandler, VisibilityStates
from handlers.rag_index_handler import RagIndexHandler
from handlers.codebase_crud_handler import CodebaseCrudHandler, CodebaseCrudStates


logger = logging.getLogger(__name__)

# FSM состояния для кодовых баз
class CodebaseStates(StatesGroup):
# Остаются только состояния для редактирования и других операций
    edit_selection = State()
    edit_field = State()
    share_users = State()
    #create_name = State()
    #create_description = State()
    #confirm_public = State()
    #confirm_hide = State()

class CodebaseHandler:
    """Обработчик операций с кодовыми базами"""
    
    def __init__(self, bot, user_manager, codebase_manager, file_manager):
        self.bot = bot
        self.user_manager = user_manager
        self.codebase_manager = codebase_manager
        self.file_manager = file_manager
        self.rag_manager = get_rag_manager()

        # Подключаем обработчики
        self.public_access_handler = PublicAccessHandler(bot, user_manager, codebase_manager)
        self.visibility_handler = CodebaseVisibilityHandler(bot, user_manager, codebase_manager, file_manager)
        self.rag_handler = RagIndexHandler(bot, user_manager, codebase_manager, self.rag_manager)
        self.crud_handler = CodebaseCrudHandler(bot, user_manager, codebase_manager)
    
    def register_handlers(self, dp):
        """Регистрация обработчиков в диспетчере"""
        # Команды для кодовых баз (остаются в основном классе)
        dp.message.register(self.cmd_codebases_page, F.text.regexp(r"^/codebases_(\d+)$"))
        dp.message.register(self.cmd_select_cb, F.text.regexp(r"^/select_cb_(.+)$"))
        dp.message.register(self.cmd_codebases, F.text == "/codebases")
        dp.message.register(self.cmd_active_codebase, F.text == "/active")
        dp.message.register(self.cmd_switch, F.text == "/switch")
    
        # CRUD операции
        dp.message.register(self.crud_handler.cmd_create_codebase, F.text == "/create_codebase")
        dp.message.register(self.crud_handler.process_codebase_name, CodebaseCrudStates.create_name)
        dp.message.register(self.crud_handler.process_codebase_description, CodebaseCrudStates.create_description)
    
        # Видимость
        dp.message.register(self.visibility_handler.cmd_make_public, F.text == "/make_public")
        dp.message.register(self.visibility_handler.cmd_hide_codebase, F.text == "/hide_codebase")
        dp.message.register(self.visibility_handler.process_public_confirm, VisibilityStates.confirm_public)
        dp.message.register(self.visibility_handler.process_hide_confirm, VisibilityStates.confirm_hide)
    
        # RAG
        dp.message.register(self.rag_handler.cmd_index_rag, F.text == "/index_rag")
    
        # Публичный доступ
        dp.message.register(self.public_access_handler.cmd_public_add_user, F.text.regexp(r"^/public_add_user\s+\d+"))
        dp.message.register(self.public_access_handler.cmd_public_add_user_help, F.text == "/public_add_user")
        dp.message.register(self.public_access_handler.cmd_public_remove_user, F.text.regexp(r"^/public_remove_user\s+\d+"))
        dp.message.register(self.public_access_handler.cmd_public_list_users, F.text == "/public_list_users")
        dp.message.register(self.public_access_handler.cmd_public_list_users, F.text.regexp(r"^/public_list_users_\d+$"))
    
        # Callback обработчики
        dp.callback_query.register(
            self.handle_codebase_callback,
            F.data.startswith("select_cb:")
        )
    
    async def cmd_codebases_page(self, message: types.Message):
        """Обработка команды с номером страницы"""
        m = re.match(r"^/codebases_(\d+)$", message.text)
        if not m:
            return
        page = int(m.group(1))
        await self.cmd_codebases(message, page)
    
    async def cmd_select_cb(self, message: types.Message):
        """Обработка команды выбора кодовой базы"""
        m = re.match(r"^/select_cb_(.+)$", message.text)
        if not m:
            return
        codebase_id = m.group(1)
        await self.select_codebase(message, codebase_id)
    
    def _get_help_text_escaped(self):
        """Возвращает экранированный текст справки для MarkdownV2"""
        text = ""
        text += "*📌 Команды:*\n"
        text += "/codebases \\- список ваших кодовых баз\n"
        text += "/create\\_codebase \\- создать новую\n"
        text += "/active \\- показать активную\n"
        text += "/switch \\- быстрое переключение\n"
        text += "/make\\_public \\- сделать базу публичной\n"
        text += "/hide\\_codebase \\- скрыть базу \\(необратимо\\)\n"
        text += "/index\\_rag \\- проиндексировать активную базу для RAG\n\n"
    
        text += "*👥 Управление доступом \\(для владельцев\\):*\n"
        text += "/public\\_list\\_users \\- список пользователей с доступом\n"
        text += "/public\\_add\\_user \\- добавить пользователя\n"
        text += "/public\\_remove\\_user \\- удалить доступ\n\n"

        text += "*📂 Управление файлами:*\n"
        text += "/files \\- постраничный просмотр всех файлов\n"
        text += "/search \\- поиск файлов по части имени\n"
        text += "/download \\- скачивание файлов\n"
        text += "/delete \\- удаление файлов\n"
    
        return text

    async def cmd_codebases(self, message: types.Message, page: int = 1):
        """Показывает список кодовых баз пользователя с пагинацией"""
        user_id = str(message.from_user.id)
    
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return
    
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
    
        if not user_codebases["codebases"]:
            text = (
                "У вас пока нет кодовых баз\\.\n"
                "Создайте первую командой /create\\_codebase"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        # Пагинация - 5 на страницу
        items_per_page = 5
        total_items = len(user_codebases["codebases"])
        total_pages = (total_items + items_per_page - 1) // items_per_page
    
        # Проверка корректности страницы
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
    
        start_idx = (page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)
    
        text = f"📚 *Ваши кодовые базы \\(стр\\. {escape_markdown_v2(str(page))}/{escape_markdown_v2(str(total_pages))}\\):*\n\n"
    
        # Сортируем по номеру для правильного отображения
        sorted_codebases = sorted(
            user_codebases["codebases"].items(),
            key=lambda x: x[1].get("number", 0)
        )
    
        for idx, (cb_id, cb_info) in enumerate(sorted_codebases[start_idx:end_idx], start_idx + 1):
            config = await self.codebase_manager.get_codebase_config(user_id, cb_id)
            if config:
                is_active = "✅" if user_codebases["active"] == cb_id else "  "
            
                # Определяем тип и иконку
                if cb_info.get("is_public_ref"):
                    # Это чужая публичная база
                    access_icon = "📥"  # Иконка для добавленной базы
                    name_prefix = "[ДОБАВЛЕНА] "
                else:
                    # Это своя база
                    access_icon = {"private": "🔒", "public": "🌍", "shared": "👥"}.get(
                        config["access"]["type"], "❓"
                    )
                    name_prefix = ""
            
                # Используем номер из конфига
                number = config.get("number", cb_id)
            
                # Экранируем все значения
                name_escaped = escape_markdown_v2(name_prefix + config['name'])
                number_escaped = escape_markdown_v2(str(number))
            
                text += f"{is_active} {number_escaped}\\. *{name_escaped}* {access_icon}\n"

                # Для своих публичных баз показываем команды управления
                if config.get("is_public") and config.get("public_id") and not cb_info.get("is_public_ref"):
                    text += f"    └ 👥 Управление: /public\\_list\\_users\n"

                # Для чужих публичных баз показываем владельца
                if cb_info.get("is_public_ref"):
                    owner_id = cb_info.get("owner_id")
                    owner_data = await self.user_manager.get_user(owner_id)
                    if owner_data:
                        owner_name = f"{owner_data.get('name', '')} {owner_data.get('surname', '')}".strip()
                        text += f"    └ 👤 Владелец: {escape_markdown_v2(owner_name)}\n"

                if config.get("description"):
                    desc_preview = config['description'][:40] + "..." if len(config['description']) > 40 else config['description']
                    desc_escaped = escape_markdown_v2(desc_preview)
                    text += f"    └ {desc_escaped}\n"
            
                # Команда с номером
                cb_id_escaped = escape_markdown_v2(cb_id)
                text += f"    └ Команда: /select\\_cb\\_{cb_id_escaped}\n"
            
                # Статистика
                files_count, _ = await self.codebase_manager.get_live_stats(user_id, cb_id)
                files_count_escaped = escape_markdown_v2(str(files_count))
                text += f"    └ Файлов: {files_count_escaped}"
            
                # Для своих публичных баз показываем количество пользователей с доступом
                if config.get("is_public") and not cb_info.get("is_public_ref"):
                    users_with_access = await self.codebase_manager.get_public_codebase_users(config.get("public_id"))
                    users_count = len(users_with_access)
                    text += f" \\| Пользователей: {escape_markdown_v2(str(users_count))}"
            
                text += "\n\n"
    
        # Навигация
        if total_pages > 1:
            text += "🔄 *Страницы:* "
            if page > 1:
                prev_page = escape_markdown_v2(str(page-1))
                text += f"/codebases\\_{prev_page} ◀️ "
        
            page_escaped = escape_markdown_v2(str(page))
            total_escaped = escape_markdown_v2(str(total_pages))
            text += f"\\[{page_escaped}/{total_escaped}\\]"
        
            if page < total_pages:
                next_page = escape_markdown_v2(str(page+1))
                text += f" ▶️ /codebases\\_{next_page}"
            text += "\n\n"
    
        # Обновленная справка
        text += self._get_help_text_escaped()
        text += "\n\n💡 Кликните на команду /select\\_cb\\_X чтобы сделать базу активной"
    
        await message.reply(text, parse_mode="MarkdownV2")
 
    async def cmd_active_codebase(self, message: types.Message):
        user_id = str(message.from_user.id)
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return

        # Обеспечиваем наличие devnull и получаем список баз
        await self.codebase_manager.ensure_devnull(user_id)
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
    
        # Теперь active всегда должен быть установлен (как минимум на devnull)
        if not user_codebases["active"]:
            # Это не должно произойти, но на всякий случай
            text = (
                "⚠️ Нет активной кодовой базы\\.\n"
                "Используйте /switch для выбора базы"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return

        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)

        # Если это devnull и есть другие базы, предложим переключиться
        if config and config.get("folder_name") == "devnull":
            non_devnull_count = sum(1 for cb_id, cb_info in user_codebases["codebases"].items() 
                                  if cb_info.get("folder_name") != "devnull")
        
            if non_devnull_count > 0:
                text = (
                    "📂 *Активная база: devnull \\(системная\\)*\n\n"
                    "Это временная системная база для новых пользователей\\.\n"
                    "У вас есть другие кодовые базы\\!\n\n"
                    "Используйте /switch чтобы выбрать рабочую базу\\.\n"
                    "Или /codebases чтобы посмотреть список\\."
                )
                await message.reply(text, parse_mode="MarkdownV2")
                return

        if not config:
            await message.reply("Ошибка: активная кодовая база не найдена\\.", parse_mode="MarkdownV2")
            return

        # Определяем тип базы
        is_owner = not cb_info.get("is_public_ref", False)

        # Используем вспомогательный метод для получения правильных параметров RAG
        rag_user_id, rag_codebase_id = self.codebase_manager.get_rag_params_for_codebase(user_id, codebase_id, cb_info)
    
        # Получаем RAG статус с правильными параметрами
        codebase_dir = self.codebase_manager._get_codebase_dir(rag_user_id, rag_codebase_id)
        files_dir = os.path.join(codebase_dir, "files")
        rag_status = await self.rag_manager.check_index_status(rag_user_id, rag_codebase_id, files_dir)
        rag_info = "✅ Актуален" if rag_status['exists'] and not rag_status.get('needs_update') else "⚠️ Требует обновления"
    
        # Получаем статистику файлов
        files_count, total_size = await self.codebase_manager.get_live_stats(user_id, codebase_id)

        # Получаем информацию о владельце для публичных баз
        owner_info = ""
        if not is_owner:
            owner_id = cb_info.get("owner_id")
            owner_data = await self.user_manager.get_user(owner_id)
            if owner_data:
                owner_name = f"{owner_data.get('name', '')} {owner_data.get('surname', '')}".strip()
                owner_telegram = owner_data.get('telegram_username', 'Не указан')
                owner_email = owner_data.get('email', '')
            
                owner_info = f"\n👤 *Владелец:* {escape_markdown_v2(owner_name)}\n"
                owner_info += f"💬 *Telegram:* {escape_markdown_v2(owner_telegram)}\n"
            
                # Показываем email только если он верифицирован
                if owner_data.get('email_verified', False) and owner_email:
                    owner_info += f"📧 *Email:* {escape_markdown_v2(owner_email)}\n"

        access_type = {"private": "🔒 Приватная", "public": "🌍 Публичная", "shared": "👥 Общая"}.get(
            config["access"]["type"], "❓ Неизвестно"
        )

        ai_info = "По умолчанию"
        ai_settings = config.get("ai_settings", {})
        if ai_settings.get("provider") != "default":
            ai_info = f"{ai_settings['provider']}/{ai_settings.get('model', 'default')}"

        # Экранируем все значения для MarkdownV2
        name = escape_markdown_v2(config['name'])
        description = escape_markdown_v2(config.get('description', 'Не указано'))
        folder_id = escape_markdown_v2(config['id'])
        access_escaped = escape_markdown_v2(access_type)
        rag_escaped = escape_markdown_v2(rag_info)
        ai_escaped = escape_markdown_v2(ai_info)
        created_date = escape_markdown_v2(config['created_at'][:10])
        files_count_escaped = escape_markdown_v2(str(files_count))
        size_formatted = escape_markdown_v2(self.file_manager.format_size(total_size))

        # Формируем заголовок в зависимости от типа базы
        if is_owner:
            header = "📂 *Активная кодовая база \\(владелец\\):*\n\n"
        else:
            header = "📥 *Активная кодовая база \\(добавлена\\):*\n\n"

        text = (
            f"{header}"
            f"📝 *Название:* {name}\n"
            f"📄 *Описание:* {description}\n"
            f"📁 *ID базы:* {folder_id}\n"
            f"🔐 *Доступ:* {access_escaped}\n"
        )

        # Добавляем информацию о владельце для публичных баз
        if owner_info:
            text += owner_info

        text += (
            f"🔍 *RAG индекс:* {rag_escaped}\n"
            f"🤖 *AI:* {ai_escaped}\n"
            f"📊 *Статистика:*\n"
            f"  • Файлов: {files_count_escaped}\n"
            f"  • Размер: {size_formatted}\n"
            f"  • Создана: {created_date}\n"
        )

        # Для владельца публичной базы показываем управление доступом
        if is_owner and config.get("is_public"):
            users_with_access = await self.codebase_manager.get_public_codebase_users(config.get("public_id"))
            users_count = len(users_with_access)
        
            text += (
                f"  • Пользователей: {escape_markdown_v2(str(users_count))}\n"
            )
    
        # Для пользователя с доступом показываем ограничения
        if not is_owner:
            text += (
                f"\n⚠️ *Ваши права:*\n"
                f"✅ Использование агентов для поиска\n"
                f"✅ Просмотр структуры файлов\n"
                f"❌ Изменение файлов\n"
                f"❌ Прямое скачивание файлов\n"
                f"❌ Управление доступом\n"
            )

        text += "\n" + self._get_help_text_escaped()
    
        await message.reply(text, parse_mode="MarkdownV2")

 
    async def cmd_switch(self, message: types.Message):
        """Быстрое переключение между кодовыми базами"""
        user_id = str(message.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
        
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        
        if len(user_codebases["codebases"]) < 2:
            await message.reply(
                "У вас недостаточно кодовых баз для переключения.\n"
                "Создайте еще одну командой /create_codebase"
            )
            return
        
        # Создаем inline клавиатуру для быстрого выбора
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        
        for cb_id, cb_info in user_codebases["codebases"].items():
            config = await self.codebase_manager.get_codebase_config(user_id, cb_id)
            if config:
                is_active = "✅ " if user_codebases["active"] == cb_id else ""
                access_icon = {"private": "🔒", "public": "🌍", "shared": "👥"}.get(
                    config["access"]["type"], "❓"
                )
                
                button_text = f"{is_active}{config['name'][:20]} {access_icon}"
                # Создаем callback data с префиксом
                callback_data = f"select_cb:{cb_id[:50]}"  # Ограничиваем длину
                
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(text=button_text, callback_data=callback_data)
                ])
        
        await message.reply(
            "🔄 Выберите кодовую базу для активации:",
            reply_markup=keyboard
        )
    
    def cb_help_info(self):
        """Возвращает текст справки (без экранирования, для обратной совместимости)"""
        text = ""
        text += "📌 Команды:\n"
        text += "/codebases - список ваших кодовых баз\n"
        text += "/create_codebase - создать новую\n"
        text += "/active - показать активную\n"
        text += "/switch - быстрое переключение\n"
        text += "/make_public - сделать базу публичной\n"
        text += "/hide_codebase - скрыть базу (необратимо)\n"
        text += "/index_rag - проиндексировать активную базу для RAG\n\n"
    
        text += "👥 Управление доступом (для владельцев):\n"
        text += "/public_list_users - список пользователей с доступом\n"
        text += "/public_add_user - добавить пользователя\n"
        text += "/public_remove_user - удалить доступ\n\n"

        text += "📂 Управление файлами:\n"
        text += "/files - постраничный просмотр всех файлов\n"
        text += "/search - поиск файлов по части имени\n"
        text += "/download - скачивание файлов\n"
        text += "/delete - удаление файлов\n"
        return text

    async def select_codebase(self, message: types.Message, codebase_id: str):
        """Делает выбранную кодовую базу активной"""
        user_id = str(message.from_user.id)
    
        # Проверяем существование кодовой базы
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
    
        if codebase_id not in user_codebases["codebases"]:
            text = (
                f"❌ Кодовая база \\#{escape_markdown_v2(codebase_id)} не найдена\\.\n"
                "Используйте /codebases для просмотра списка\\."
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        # Проверяем, не активна ли уже
        if user_codebases["active"] == codebase_id:
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            name_escaped = escape_markdown_v2(config['name'])
            cb_id_escaped = escape_markdown_v2(codebase_id)
            text = f"ℹ️ Кодовая база '{name_escaped}' \\(\\#{cb_id_escaped}\\) уже активна\\."
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        # Делаем активной
        success = await self.codebase_manager.set_active_codebase(user_id, codebase_id)
    
        if success:
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
            # Получаем информацию о владельце для публичных баз
            owner_info = ""
            if codebase_id.startswith("pub_"):
                cb_info = user_codebases["codebases"].get(codebase_id)
                if cb_info and cb_info.get("is_public_ref"):
                    owner_id = cb_info["owner_id"]
                    owner_data = await self.user_manager.get_user(owner_id)
                    if owner_data:
                        owner_name = f"{owner_data.get('name', '')} {owner_data.get('surname', '')}".strip()
                        owner_telegram = owner_data.get('telegram_username', 'Не указан')
                        owner_email = owner_data.get('email', '')
                    
                        owner_info_text = f"\n👤 *Владелец:* {escape_markdown_v2(owner_name)}\n"
                        owner_info_text += f"💬 *Telegram:* {escape_markdown_v2(owner_telegram)}\n"
                    
                        if owner_data.get('email_verified', False) and owner_email:
                            owner_info_text += f"📧 *Email:* {escape_markdown_v2(owner_email)}\n"
                    
                        owner_info = owner_info_text
        
            files_count, total_size = await self.codebase_manager.get_live_stats(user_id, codebase_id)
        
            access_type = {"private": "🔒 Приватная", "public": "🌍 Публичная", "shared": "👥 Общая"}.get(
                config["access"]["type"], "❓ Неизвестно"
            )
        
            ai_info = "По умолчанию"
            ai_settings = config.get("ai_settings", {})
            if ai_settings.get("provider") != "default":
                ai_info = f"{ai_settings['provider']}/{ai_settings.get('model', 'default')}"
        
            # Экранируем все значения для MarkdownV2
            name_escaped = escape_markdown_v2(config['name'])
            desc_escaped = escape_markdown_v2(config.get('description', 'Не указано'))
            folder_escaped = escape_markdown_v2(config['id'])
            access_escaped = escape_markdown_v2(access_type)
            ai_escaped = escape_markdown_v2(ai_info)
            files_escaped = escape_markdown_v2(str(files_count))
            size_formatted = escape_markdown_v2(self.file_manager.format_size(total_size))
            date_escaped = escape_markdown_v2(config['created_at'][:10])
        
            text = (
                f"📂 *Активная кодовая база:*\n\n"
                f"📝 *Название:* {name_escaped}\n"
                f"📄 *Описание:* {desc_escaped}\n"
                f"📁 *Папка:* {folder_escaped}\n"
                f"🔐 *Доступ:* {access_escaped}\n"
            )
        
            # Добавляем информацию о владельце
            if owner_info:
                text += owner_info
        
            text += (
                f"🤖 *AI:* {ai_escaped}\n"
                f"📊 *Статистика:*\n"
                f"  • Файлов: {files_escaped}\n"
                f"  • Размер: {size_formatted}\n"
                f"  • Создана: {date_escaped}\n"
            )
        
            text += "\n"
            # Экранируем справочную информацию
            help_lines = self.cb_help_info().split('\n')
            for line in help_lines:
                if line.startswith('/'):
                    text += line.replace('_', '\\_').replace('-', '\\-').replace('(', '\\(').replace(')', '\\)') + '\n'
                else:
                    text += escape_markdown_v2(line) + '\n'
        
            await message.reply(text, parse_mode="MarkdownV2")
        
            # Обновляем активность
            await self.user_manager.update_activity(user_id)
        else:
            await message.reply("❌ Ошибка при выборе кодовой базы\\.", parse_mode="MarkdownV2")
      
    async def handle_codebase_callback(self, callback: types.CallbackQuery, state: FSMContext = None):
        """Обработка callback от inline кнопок"""
        user_id = str(callback.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await callback.answer("У вас нет доступа к боту.", show_alert=True)
            return
        
        # Обработка выбора кодовой базы
        if callback.data.startswith("select_cb:"):
            codebase_id_part = callback.data[10:]
            
            # Находим полный ID
            user_codebases = await self.codebase_manager.get_user_codebases(user_id)
            full_codebase_id = None
            
            for cb_id in user_codebases["codebases"].keys():
                if cb_id.startswith(codebase_id_part) or codebase_id_part in cb_id:
                    full_codebase_id = cb_id
                    break
            
            if full_codebase_id:
                success = await self.codebase_manager.set_active_codebase(user_id, full_codebase_id)
                if success:
                    config = await self.codebase_manager.get_codebase_config(user_id, full_codebase_id)
                    await callback.answer(f"✅ Активирована: {config['name']}", show_alert=False)
                    
                    files_count, total_size = await self.codebase_manager.get_live_stats(user_id, full_codebase_id)
                    
                    # Обновляем сообщение
                    await callback.message.edit_text(
                        f"✅ Кодовая база '{config['name']}' активирована!\n\n"
                        f"📝 Описание: {config.get('description', 'Не указано')}\n"
                        f"📊 Файлов: {files_count}\n"
                        f"🔐 Доступ: {config['access']['type']}\n\n"
                        f"{self.cb_help_info()}"
                    )
                else:
                    await callback.answer("❌ Ошибка активации", show_alert=True)
            else:
                await callback.answer("❌ Кодовая база не найдена", show_alert=True)
    