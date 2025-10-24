# code/handlers/public_access_handler.py
"""
Обработчик команд управления доступом к публичным базам
"""

import logging
from aiogram import types
from utils.markdown_utils import escape_markdown_v2

logger = logging.getLogger(__name__)


class PublicAccessHandler:
    """Обработчик управления доступом к публичным базам"""
    
    def __init__(self, bot, user_manager, codebase_manager):
        self.bot = bot
        self.user_manager = user_manager
        self.codebase_manager = codebase_manager
    
    async def cmd_public_add_user(self, message: types.Message):
        """Добавить пользователя к публичной кодовой базе"""
        user_id = str(message.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return
        
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await self.cmd_public_add_user_help(message)
            return
        
        target_user_id = parts[1].strip()
        
        if not target_user_id.isdigit():
            text = "❌ Некорректный Telegram ID\\. Используйте только цифры\\."
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if not user_codebases["active"]:
            text = (
                "❌ Нет активной кодовой базы\\.\n"
                "Выберите кодовую базу командой /switch"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
        
        if cb_info.get("is_public_ref"):
            text = (
                "❌ *Вы не являетесь владельцем этой базы\\!*\n\n"
                "Только владелец может управлять доступом\\.\n"
                "Это добавленная вам публичная база\\."
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        if not config:
            await message.reply("❌ Конфигурация базы не найдена", parse_mode="MarkdownV2")
            return
        
        if config.get("owner_id") and config["owner_id"] != user_id:
            text = "❌ Вы не являетесь владельцем этой базы"
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        if config.get("is_system") or config.get("folder_name") == "devnull":
            await message.reply("❌ Нельзя добавлять пользователей к системной базе", parse_mode="MarkdownV2")
            return
        
        if not config.get("is_public"):
            name_escaped = escape_markdown_v2(config['name'])
            text = (
                f"❌ База '{name_escaped}' не является публичной\\.\n"
                f"Сначала сделайте её публичной командой /make\\_public"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        target_user = await self.user_manager.get_user(target_user_id)
        if not target_user:
            text = (
                f"❌ Пользователь с ID `{target_user_id}` не найден\\.\n"
                f"Пользователь должен быть зарегистрирован в боте\\."
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        if target_user_id == user_id:
            await message.reply("❌ Вы уже являетесь владельцем этой базы", parse_mode="MarkdownV2")
            return
        
        public_id = config.get("public_id")
        success, msg = await self.codebase_manager.add_public_codebase(target_user_id, public_id)
        
        if success:
            target_name = f"{target_user.get('name', '')} {target_user.get('surname', '')}".strip()
            target_telegram = target_user.get('telegram_username', 'Не указан')
            
            response = (
                f"✅ *Доступ предоставлен\\!*\n\n"
                f"📂 *База:* {escape_markdown_v2(config['name'])}\n"
                f"👤 *Пользователь:* {escape_markdown_v2(target_name)}\n"
                f"🆔 *Telegram ID:* `{target_user_id}`\n"
                f"💬 *Username:* {escape_markdown_v2(target_telegram)}\n\n"
                f"Пользователь может теперь:\n"
                f"• Выбрать базу через /switch\n"
                f"• Использовать агентов для работы с ней\n"
                f"• Просматривать файлы через агентов\n\n"
                f"⚠️ Пользователь НЕ может:\n"
                f"• Изменять файлы\n"
                f"• Скачивать файлы напрямую\n"
                f"• Управлять доступом других"
            )
            
            await message.reply(response, parse_mode="MarkdownV2")
            
            # Отправляем уведомление целевому пользователю
            if target_user.get('active', False):
                try:
                    owner_user = await self.user_manager.get_user(user_id)
                    owner_name = f"{owner_user.get('name', '')} {owner_user.get('surname', '')}".strip() if owner_user else "Неизвестный"
                    
                    notification = (
                        f"🎉 *Вам предоставлен доступ\\!*\n\n"
                        f"📂 База: {escape_markdown_v2(config['name'])}\n"
                        f"👤 Владелец: {escape_markdown_v2(owner_name)}\n\n"
                        f"Используйте /switch для выбора базы\\."
                    )
                    await self.bot.send_message(target_user_id, notification, parse_mode="MarkdownV2")
                except:
                    pass
        else:
            if msg == "База уже добавлена":
                text = f"ℹ️ Пользователь уже имеет доступ к этой базе"
            else:
                text = f"❌ {escape_markdown_v2(msg)}"
            await message.reply(text, parse_mode="MarkdownV2")
    
    async def cmd_public_add_user_help(self, message: types.Message):
        """Показать справку по команде public_add_user"""
        text = (
            f"📚 *Добавление пользователя к публичной базе*\n\n"
            f"*Использование:*\n"
            f"`/public_add_user <telegram_id>`\n\n"
            f"*Требования:*\n"
            f"• Вы должны быть владельцем базы\n"
            f"• База должна быть публичной\n"
            f"• База должна быть активной\n\n"
            f"*Пример:*\n"
            f"`/public_add_user 123456789`\n\n"
            f"*Дополнительные команды:*\n"
            f"/public\\_list\\_users \\- список пользователей с доступом\n"
            f"/public\\_remove\\_user \\- удалить доступ пользователя"
        )
        await message.reply(text, parse_mode="MarkdownV2")
    
    async def cmd_public_remove_user(self, message: types.Message):
        """Удалить доступ пользователя к публичной базе"""
        user_id = str(message.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return
        
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            text = (
                f"📚 *Удаление доступа пользователя*\n\n"
                f"*Использование:*\n"
                f"`/public_remove_user <telegram_id>`\n\n"
                f"*Пример:*\n"
                f"`/public_remove_user 123456789`"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        target_user_id = parts[1].strip()
        
        if not target_user_id.isdigit():
            await message.reply("❌ Некорректный Telegram ID", parse_mode="MarkdownV2")
            return
        
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if not user_codebases["active"]:
            await message.reply("❌ Нет активной кодовой базы", parse_mode="MarkdownV2")
            return
        
        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
        
        if cb_info.get("is_public_ref"):
            text = "❌ Только владелец может управлять доступом к базе"
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        if not config or not config.get("is_public"):
            await message.reply("❌ База не является публичной", parse_mode="MarkdownV2")
            return
        
        public_id = config.get("public_id")
        virtual_id = f"pub_{public_id}"
        
        success = await self.codebase_manager.remove_public_codebase(target_user_id, virtual_id)
        
        if success:
            text = (
                f"✅ Доступ удален\\!\n\n"
                f"Пользователь `{target_user_id}` больше не имеет доступа к базе\\."
            )
            await message.reply(text, parse_mode="MarkdownV2")
        else:
            text = "❌ Не удалось удалить доступ\\. Возможно, пользователь не имел доступа\\."
            await message.reply(text, parse_mode="MarkdownV2")
    
    async def cmd_public_list_users(self, message: types.Message):
        """Показать список пользователей с доступом к публичной базе"""
        user_id = str(message.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return
        
        # Извлекаем номер страницы из команды если есть
        parts = message.text.split('_')
        page = 1
        if len(parts) > 3 and parts[-1].isdigit():
            page = int(parts[-1])
        
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if not user_codebases["active"]:
            await message.reply("❌ Нет активной кодовой базы", parse_mode="MarkdownV2")
            return
        
        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
        
        if cb_info.get("is_public_ref"):
            text = "❌ Только владелец может просматривать список пользователей с доступом"
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        if not config or not config.get("is_public"):
            await message.reply("❌ База не является публичной", parse_mode="MarkdownV2")
            return
        
        public_id = config.get("public_id")
        users_with_access = await self.codebase_manager.get_public_codebase_users(public_id)
        
        # Пагинация
        items_per_page = 10
        total_users = len(users_with_access)
        total_pages = max(1, (total_users + items_per_page - 1) // items_per_page)
        
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        
        start_idx = (page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_users)
        
        base_name = escape_markdown_v2(config['name'])
        text = f"👥 *Доступ к базе '{base_name}'*\n"
        text += f"Всего пользователей: {total_users}\n\n"
        
        if users_with_access:
            for user_info in users_with_access[start_idx:end_idx]:
                user_data = await self.user_manager.get_user(user_info['user_id'])
                if user_data:
                    name = f"{user_data.get('name', '')} {user_data.get('surname', '')}".strip()
                    telegram = user_data.get('telegram_username', '')
                    
                    text += f"🆔 `{user_info['user_id']}` "
                    text += f"{escape_markdown_v2(name)}"
                    
                    if telegram and telegram != 'Не указан':
                        text += f" {escape_markdown_v2(telegram)}"
                    
                    text += "\n"
        else:
            text += "_Пока никто не добавлен_\n"
        
        text += "\n"
        
        # Навигация
        if total_pages > 1:
            text += "🔄 "
            if page > 1:
                text += f"/public\\_list\\_users\\_{page-1} ◀️ "
            text += f"{page}/{total_pages}"
            if page < total_pages:
                text += f" ▶️ /public\\_list\\_users\\_{page+1}"
            text += "\n\n"
        
        text += (
            "*Команды:*\n"
            f"`/public_add_user <id>` \\- добавить\n"
            f"`/public_remove_user <id>` \\- удалить"
        )
        
        await message.reply(text, parse_mode="MarkdownV2")