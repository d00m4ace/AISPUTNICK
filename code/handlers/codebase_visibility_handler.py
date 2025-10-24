# code/handlers/codebase_visibility_handler.py
"""
Обработчик команд управления видимостью кодовых баз
"""

import logging
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils.markdown_utils import escape_markdown_v2

logger = logging.getLogger(__name__)

class VisibilityStates(StatesGroup):
    confirm_public = State()
    confirm_hide = State()


class CodebaseVisibilityHandler:
    """Обработчик управления видимостью кодовых баз"""
    
    def __init__(self, bot, user_manager, codebase_manager, file_manager):
        self.bot = bot
        self.user_manager = user_manager
        self.codebase_manager = codebase_manager
        self.file_manager = file_manager
    
    async def cmd_make_public(self, message: types.Message, state: FSMContext):
        """Сделать кодовую базу публичной"""
        user_id = str(message.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
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
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        if not config:
            await message.reply("❌ Конфигурация базы не найдена", parse_mode="MarkdownV2")
            return
        
        # Проверки
        if config.get("is_system") or config.get("folder_name") == "devnull":
            await message.reply("❌ Системную базу devnull нельзя сделать публичной", parse_mode="MarkdownV2")
            return
        
        if config.get("is_public"):
            name_escaped = escape_markdown_v2(config['name'])
            text = (
                f"ℹ️ База '{name_escaped}' уже публичная\\!\n\n"
                f"*Управление доступом:*\n"
                f"/public\\_list\\_users \\- список пользователей с доступом\n"
                f"/public\\_add\\_user `<telegram_id>` \\- добавить пользователя\n"
                f"/public\\_remove\\_user `<telegram_id>` \\- удалить доступ\n\n"
                f"Чтобы добавить пользователя, узнайте его Telegram ID\\.\n"
                f"Пользователь может узнать свой ID командой /settings"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
        
        if config.get("hidden"):
            await message.reply("❌ Скрытую базу нельзя сделать публичной", parse_mode="MarkdownV2")
            return
        
        # Сохраняем данные для подтверждения
        await state.update_data(
            codebase_id=codebase_id,
            codebase_name=config['name'],
            action="make_public"
        )
        
        files_count, total_size = await self.codebase_manager.get_live_stats(user_id, codebase_id)
        
        name_escaped = escape_markdown_v2(config['name'])
        files_escaped = escape_markdown_v2(str(files_count))
        size_escaped = escape_markdown_v2(self.file_manager.format_size(total_size))
        
        text = (
            f"⚠️ *ВНИМАНИЕ\\! Публикация кодовой базы*\n\n"
            f"📂 База: {name_escaped}\n"
            f"📊 Файлов: {files_escaped}\n"
            f"💾 Размер: {size_escaped}\n\n"
            f"*После публикации вы сможете:*\n"
            f"✅ Предоставлять доступ выбранным пользователям\n"
            f"✅ Видеть список пользователей с доступом\n"
            f"✅ Отзывать доступ в любое время\n"
            f"✅ Продолжать изменять файлы\n\n"
            f"*Пользователи с доступом смогут:*\n"
            f"✅ Использовать агентов для поиска\n"
            f"✅ Читать содержимое файлов через агентов\n"
            f"✅ Использовать RAG индекс базы\n\n"
            f"*Пользователи НЕ смогут:*\n"
            f"❌ Изменять или удалять файлы\n"
            f"❌ Скачивать файлы напрямую\n"
            f"❌ Управлять доступом других\n\n"
            f"⚠️ *Важно:*\n"
            f"• Это действие НЕОБРАТИМО\n"
            f"• База останется публичной даже после скрытия\n"
            f"• Вы всегда сохраните полный контроль\n\n"
            f"Введите 'ДА' для подтверждения или /cancel для отмены:"
        )
        
        await message.reply(text, parse_mode="MarkdownV2")
        await state.set_state(VisibilityStates.confirm_public)
    
    async def process_public_confirm(self, message: types.Message, state: FSMContext):
        """Подтверждение публикации базы"""
        user_id = str(message.from_user.id)
        
        if message.text != "ДА":
            await message.reply("❌ Публикация отменена", parse_mode="MarkdownV2")
            await state.clear()
            return
        
        data = await state.get_data()
        codebase_id = data['codebase_id']
        codebase_name = data['codebase_name']
        
        public_id = await self.codebase_manager.make_public(user_id, codebase_id)
        
        if public_id:
            name_escaped = escape_markdown_v2(codebase_name)
            text = (
                f"✅ *База '{name_escaped}' теперь публичная\\!*\n\n"
                f"*Что дальше:*\n\n"
                f"1️⃣ *Добавьте пользователей:*\n"
                f"   `/public_add_user <telegram_id>`\n\n"
                f"2️⃣ *Управляйте доступом:*\n"
                f"   /public\\_list\\_users \\- список пользователей\n"
                f"   /public\\_remove\\_user \\- удалить доступ\n\n"
                f"3️⃣ *Как пользователь узнает свой ID:*\n"
                f"   Он должен использовать команду /settings\n"
                f"   Там будет показан его Telegram ID\n\n"
                f"💡 *Совет:* Попросите пользователей сначала\n"
                f"зарегистрироваться в боте через /start,\n"
                f"затем прислать вам свой Telegram ID\\.\n\n"
                f"⚠️ Помните: это действие необратимо\\!"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            
            logger.info(f"User {user_id} made codebase {codebase_id} public with ID {public_id}")
        else:
            await message.reply("❌ Ошибка при публикации базы", parse_mode="MarkdownV2")
        
        await state.clear()
    
    async def cmd_hide_codebase(self, message: types.Message, state: FSMContext):
        """Скрыть кодовую базу"""
        user_id = str(message.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
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
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        if not config:
            await message.reply("❌ Конфигурация базы не найдена", parse_mode="MarkdownV2")
            return
        
        # Проверки
        if config.get("is_system") or config.get("folder_name") == "devnull":
            await message.reply("❌ Системную базу devnull нельзя скрыть", parse_mode="MarkdownV2")
            return
        
        if config.get("hidden"):
            name_escaped = escape_markdown_v2(config['name'])
            await message.reply(f"ℹ️ База '{name_escaped}' уже скрыта", parse_mode="MarkdownV2")
            return
        
        # Сохраняем данные для подтверждения
        await state.update_data(
            codebase_id=codebase_id,
            codebase_name=config['name'],
            is_public=config.get('is_public', False),
            public_id=config.get('public_id'),
            action="hide"
        )
        
        name_escaped = escape_markdown_v2(config['name'])
        warning_text = (
            f"⚠️ ВНИМАНИЕ\\! Скрытие кодовой базы\n\n"
            f"📂 База: {name_escaped}\n"
        )
        
        if config.get('is_public'):
            public_id_escaped = escape_markdown_v2(str(config.get('public_id', '')))
            warning_text += (
                f"🔗 Публичный ID: {public_id_escaped}\n\n"
                f"⚠️ База ПУБЛИЧНАЯ\\!\n"
                f"После скрытия:\n"
                f"❌ База исчезнет из вашего списка\n"
                f"❌ Вы не сможете её выбрать\n"
                f"✅ Пользователи с доступом СОХРАНЯТ его\n"
                f"✅ Их агенты продолжат читать файлы\n"
                f"❌ Это действие НЕОБРАТИМО\n\n"
            )
        else:
            warning_text += (
                f"\nПосле скрытия:\n"
                f"❌ База исчезнет из списка\n"
                f"❌ Нельзя будет выбрать как активную\n"
                f"❌ Файлы останутся на диске\n"
                f"❌ Это действие НЕОБРАТИМО\n\n"
            )
        
        warning_text += "Введите 'СКРЫТЬ' для подтверждения или /cancel для отмены:"
        
        await message.reply(warning_text, parse_mode="MarkdownV2")
        await state.set_state(VisibilityStates.confirm_hide)
    
    async def process_hide_confirm(self, message: types.Message, state: FSMContext):
        """Подтверждение скрытия базы"""
        user_id = str(message.from_user.id)
        
        if message.text != "СКРЫТЬ":
            await message.reply("❌ Скрытие отменено", parse_mode="MarkdownV2")
            await state.clear()
            return
        
        data = await state.get_data()
        codebase_id = data['codebase_id']
        codebase_name = data['codebase_name']
        is_public = data.get('is_public', False)
        public_id = data.get('public_id')
        
        # Проверяем не активная ли это база
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if user_codebases.get("active") == codebase_id:
            # Переключаемся на devnull
            await self.codebase_manager.ensure_devnull(user_id)
            await self.codebase_manager.set_active_codebase(user_id, "0")
        
        # Скрываем базу
        success = await self.codebase_manager.toggle_hidden(user_id, codebase_id, hidden=True)
        
        if success:
            name_escaped = escape_markdown_v2(codebase_name)
            msg = f"✅ База '{name_escaped}' скрыта\\!\n\n"
            
            if is_public:
                msg += (
                    f"⚠️ ВАЖНО:\n"
                    f"Публичный ID: `{public_id}`\n"
                    f"Пользователи с этим ID сохранят доступ\\!\n"
                    f"База продолжит работать для них\\.\n\n"
                )
            
            msg += (
                f"База больше не отображается в списке\\.\n"
                f"Файлы сохранены на диске\\.\n"
                f"Это действие необратимо\\!"
            )
            
            await message.reply(msg, parse_mode="MarkdownV2")
        else:
            await message.reply("❌ Ошибка при скрытии базы", parse_mode="MarkdownV2")
        
        await state.clear()