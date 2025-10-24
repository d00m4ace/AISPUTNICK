# code/handlers/codebase_crud_handler.py
"""
Обработчик CRUD операций с кодовыми базами
"""

import re
import logging
from datetime import datetime
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils.markdown_utils import escape_markdown_v2

logger = logging.getLogger(__name__)

class CodebaseCrudStates(StatesGroup):
    create_name = State()
    create_description = State()


class CodebaseCrudHandler:
    """Обработчик создания и управления кодовыми базами"""
    
    def __init__(self, bot, user_manager, codebase_manager):
        self.bot = bot
        self.user_manager = user_manager
        self.codebase_manager = codebase_manager
    
    async def cmd_create_codebase(self, message: types.Message, state: FSMContext):
        """Начинает процесс создания новой кодовой базы"""
        user_id = str(message.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return
        
        await message.reply(
            "🆕 Создание новой кодовой базы\n\n"
            "Введите название кодовой базы \\(3\\-50 символов\\):",
            parse_mode="MarkdownV2"
        )
        await state.set_state(CodebaseCrudStates.create_name)
    
    async def process_codebase_name(self, message: types.Message, state: FSMContext):
        """Обработка названия кодовой базы"""
        # Заменяем переносы строк на пробелы и убираем лишние пробелы
        name = message.text.replace('\n', ' ').replace('\r', ' ').strip()
        name = ' '.join(name.split())
        
        # Валидация
        is_valid, error_msg = self.codebase_manager.validate_codebase_name(name)
        if not is_valid:
            error_escaped = escape_markdown_v2(error_msg)
            await message.reply(
                f"❌ Некорректное название\\.\n{error_escaped}\n\n"
                "Требования:\n"
                "• От 3 до 50 символов\n"
                "• Только русские/английские буквы, цифры, пробелы и дефис\n"
                "• Должно начинаться с буквы или цифры\n\n"
                "Попробуйте еще раз:",
                parse_mode="MarkdownV2"
            )
            return
        
        # Проверяем не существует ли уже такая папка
        user_id = str(message.from_user.id)
        folder_name = name.replace(" ", "_").lower()
        folder_name = re.sub(r'[^a-z0-9_\-а-яё]', '', folder_name)
        
        if self.codebase_manager.codebase_folder_exists(user_id, folder_name):
            folder_escaped = escape_markdown_v2(folder_name)
            await message.reply(
                f"❌ Кодовая база с похожим названием уже существует\\.\n"
                f"Папка: {folder_escaped}\n\n"
                "Выберите другое название:",
                parse_mode="MarkdownV2"
            )
            return
        
        await state.update_data(codebase_name=name)
        
        name_escaped = escape_markdown_v2(name)
        folder_escaped = escape_markdown_v2(folder_name)
        
        await message.reply(
            f"✅ Название принято: {name_escaped}\n"
            f"📁 Папка будет создана: {folder_escaped}\n\n"
            "Введите описание/назначение кодовой базы\n"
            "\\(или отправьте '\\-' чтобы пропустить\\):",
            parse_mode="MarkdownV2"
        )
        await state.set_state(CodebaseCrudStates.create_description)
    
    async def process_codebase_description(self, message: types.Message, state: FSMContext):
        """Обработка описания кодовой базы и создание"""
        logger.info(f"process_codebase_description вызван для пользователя {message.from_user.id}")
        
        # Заменяем переносы строк на пробелы
        description = message.text.replace('\n', ' ').replace('\r', ' ').strip() if message.text else ""
        description = ' '.join(description.split())
        
        logger.info(f"Обработанное описание: {repr(description)}")
        
        if description == "-":
            description = ""
        elif len(description) > 500:
            await message.reply(
                "❌ Описание слишком длинное \\(максимум 500 символов\\)\\.\n"
                "Сократите описание и попробуйте еще раз:",
                parse_mode="MarkdownV2"
            )
            return
        
        data = await state.get_data()
        user_id = str(message.from_user.id)
        
        logger.info(f"Создаем кодовую базу для пользователя {user_id}")
        
        # Создаем кодовую базу
        try:
            codebase_id = await self.codebase_manager.create_codebase(
                user_id,
                data["codebase_name"],
                description
            )
            
            logger.info(f"Результат создания: {codebase_id}")
            
            if codebase_id:
                folder_name = data['codebase_name'].replace(' ', '_').lower()
                folder_name = re.sub(r'[^a-z0-9_\-а-яё]', '', folder_name)
                
                desc_display = description if description else "Не указано"
                if len(desc_display) > 50:
                    desc_display = desc_display[:50] + "..."
                
                name_escaped = escape_markdown_v2(data['codebase_name'])
                id_escaped = escape_markdown_v2(codebase_id)
                folder_escaped = escape_markdown_v2(folder_name)
                desc_escaped = escape_markdown_v2(desc_display)
                
                await message.reply(
                    f"✅ Кодовая база '{name_escaped}' успешно создана\\!\n\n"
                    f"📌 Номер: \\#{id_escaped}\n"
                    f"📁 Папка: {folder_escaped}\n"
                    f"📝 Описание: {desc_escaped}\n"
                    f"🔒 Статус: Приватная\n"
                    f"✅ Активна\n\n"
                    "Теперь вы можете загружать файлы в эту кодовую базу\\.\n"
                    "Используйте /codebases для просмотра всех баз\\.",
                    parse_mode="MarkdownV2"
                )
                
                logger.info(f"Пользователь {user_id} создал кодовую базу #{codebase_id}: {data['codebase_name']}")
            else:
                await message.reply(
                    f"❌ Ошибка при создании кодовой базы\\.\n"
                    f"Возможно, папка с таким названием уже существует\\.\n"
                    "Попробуйте другое название через /create\\_codebase",
                    parse_mode="MarkdownV2"
                )
                logger.warning(f"Не удалось создать кодовую базу для пользователя {user_id}")
                
        except Exception as e:
            logger.error(f"Ошибка при создании кодовой базы: {e}", exc_info=True)
            error_escaped = escape_markdown_v2(str(e))
            await message.reply(
                "❌ Произошла ошибка при создании кодовой базы\\.\n"
                f"Попробуйте еще раз позже или используйте /cancel для отмены\\.",
                parse_mode="MarkdownV2"
            )
        
        # Очищаем состояние в любом случае
        await state.clear()
        logger.info(f"Состояние очищено для пользователя {user_id}")