# code/run.py
import os
import sys
import io
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage

from datetime import datetime, timedelta

from config import Config
from user_manager import UserManager
from ai_interface import AIInterface
from codebase_manager import CodebaseManager
from email_service import EmailService
from file_manager import FileManager

from utils.markdown_utils import escape_markdown_v2

from handlers.registration_handler import RegistrationHandler
from handlers.codebase_handler import CodebaseHandler
from handlers.file_handler import FileHandler

from spam_executor import SpamExecutor

# Новый упрощенный обработчик агентов
from handlers.agent_handlers.simple_agent_handler import SimpleAgentHandler

from agents.rag_singleton import init_rag_manager

from user_activity_logger import activity_logger

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class AIBot:

    def __init__(self):
        self.bot = Bot(token=Config.BOT_TOKEN)
        self.dp = Dispatcher(storage=MemoryStorage())

        self.user_manager = UserManager()
        self.codebase_manager = CodebaseManager(self.user_manager)
        self.rag_manager = init_rag_manager(self.codebase_manager)
        self.ai = AIInterface()
        self.email_service = EmailService()
        self.file_manager = FileManager(self.codebase_manager, self.ai)

        self.registration_handler = RegistrationHandler(
            self.bot, self.user_manager, self.email_service
        )
        self.codebase_handler = CodebaseHandler(
            self.bot, self.user_manager, self.codebase_manager, self.file_manager
        )
        self.file_handler = FileHandler(
            self.bot, self.user_manager, self.codebase_manager, self.file_manager
        )        

        # Новый упрощенный обработчик агентов
        self.agent_handler = SimpleAgentHandler(
            self.bot, self.user_manager, self.codebase_manager,
            self.file_manager, self.ai
        )

        self.file_handler.upload_handler.set_agent_handler(self.agent_handler)

        self.file_handler.set_agent_handler(self.agent_handler)

        self._setup_handlers()
        
        self.spam_executor = SpamExecutor(self.bot, self.user_manager)              

    async def cmd_check_spam(self, message: types.Message):
        user_id = str(message.from_user.id)

        if not await self.user_manager.is_admin(user_id):
            await message.reply("⛔ Команда доступна только администраторам")
            return

        # Получаем расписание
        schedule_text = self.spam_executor.get_broadcasts_schedule(months=6)
    
        # Разбиваем на части, если текст слишком длинный (лимит Telegram - 4096 символов)
        max_length = 4000
    
        if len(schedule_text) <= max_length:
            await message.reply(schedule_text, parse_mode="Markdown")
        else:
            # Разбиваем на части
            parts = []
            current_part = ""
        
            for line in schedule_text.split("\n"):
                if len(current_part) + len(line) + 1 > max_length:
                    parts.append(current_part)
                    current_part = line + "\n"
                else:
                    current_part += line + "\n"
        
            if current_part:
                parts.append(current_part)
        
            # Отправляем по частям
            for i, part in enumerate(parts, 1):
                header = f"📄 Часть {i}/{len(parts)}\n\n" if len(parts) > 1 else ""
                await message.reply(header + part, parse_mode="Markdown")
                await asyncio.sleep(0.5)  # Небольшая задержка между сообщениями

    def _setup_handlers(self):

        self.registration_handler.register_handlers(self.dp)
        self.codebase_handler.register_handlers(self.dp)
        self.file_handler.register_handlers(self.dp)

        # Регистрация упрощенной системы агентов
        self.agent_handler.register_handlers(self.dp)

        self.dp.message.register(self.cmd_start, F.text == "/start")
        self.dp.message.register(self.cmd_help, F.text == "/help")
        self.dp.message.register(self.cmd_status, F.text == "/status")
        self.dp.message.register(self.cmd_cancel, F.text == "/cancel")
        
        self.dp.message.register(self.cmd_check_spam, F.text == "/check_spam")

    async def cmd_start(self, message: types.Message, state):
        user_id = str(message.from_user.id)

        if await self.user_manager.user_exists(user_id):
            if await self.user_manager.is_active(user_id):
                text = (
                    f"Привет\\! Я {escape_markdown_v2(Config.BOT_NAME)}\\.\n"
                    "Чем могу помочь?\n\n"
                    "*Доступные команды:*\n"
                    "/help \\- справка\n"
                    "/settings \\- настройки профиля\n"
                    "/status \\- статус ИИ провайдеров\n"
                    "/codebases \\- управление кодовыми базами\n"
                    "/agents \\- 🆕 справка по ИИ агентам"
                    "\n\n"
                    "Или просто напишите мне что\\-нибудь\\!"
                )
                await message.reply(text, parse_mode="MarkdownV2")
            else:
                text = (
                    "Ваш аккаунт зарегистрирован, но не активирован\\.\n"
                    "Обратитесь к администратору для активации\\."
                )
                await message.reply(text, parse_mode="MarkdownV2")
        else:
            await self.registration_handler.start_registration(message, state)

    async def cmd_help(self, message: types.Message):
        user_id = str(message.from_user.id)

        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return

        help_text = (
            f"🤖 *{escape_markdown_v2(Config.BOT_NAME)} \\- Справка*\n\n"
            "*📌 Основные команды:*\n"
            "/start \\- начало работы\n"
            "/help \\- эта справка\n"
            "/status \\- статус ИИ провайдеров\n"
            "/settings \\- настройки профиля и верификация email\n\n"
            
            "*📚 Кодовые базы:*\n"
            "/codebases \\- список ваших кодовых баз\n"
            "/create\\_codebase \\- создать новую\n"
            "/active \\- показать активную базу\n"
            "/switch \\- быстрое переключение между базами\n"
            "/index\\_rag \\- проиндексировать активную базу для RAG\n\n"
            
            "*🤖 ИИ Агенты \\(НОВОЕ\\!\\):*\n"
            "/agents \\- справка и список системных агентов\n"
            "*Использование:* @имя\\_агента запрос\n"
            "*Пример:* @rag как работает эта функция?\n\n"
            
            "*📤 Загрузка файлов:*\n"
            "Просто отправьте файл боту \\- он автоматически сохранится в активную кодовую базу\n\n"
            
            "*📂 Управление файлами:*\n"
            "/files \\- постраничный просмотр всех файлов\n"
            "/search \\- поиск файлов по части имени\n"
            "/download \\- скачивание файлов\n"
            "/delete \\- удаление файлов\n"
        )

        await message.reply(help_text, parse_mode="MarkdownV2")

    async def cmd_status(self, message: types.Message):
        user_id = str(message.from_user.id)

        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return

        status = self.ai.get_provider_status()

        text = "*📊 Статус ИИ провайдеров:*\n\n"
        for provider, info in status.items():
            emoji = "✅" if info["available"] else "❌"
            provider_escaped = escape_markdown_v2(provider.upper())
            text += f"{emoji} *{provider_escaped}*\n"
            text += f"  • Доступно моделей: {escape_markdown_v2(str(info['models_count']))}\n"
            if info["default_model"]:
                text += f"  • Модель по умолчанию: {escape_markdown_v2(info['default_model'])}\n"
            text += "\n"

        text += "*🤖 Система агентов:* ✅ Активна\n"
        text += "  • Используйте @имя\\_агента для вызова\n"
        text += "  • Доступен агент @rag для поиска по коду\n"
        text += "  • /agents для справки\n"

        await message.reply(text, parse_mode="MarkdownV2")

    async def cmd_cancel(self, message: types.Message, state):
        current_state = await state.get_state()
        if current_state:
            await state.clear()
            await message.reply("❌ Операция отменена\\.", parse_mode="MarkdownV2")
        else:
            await message.reply("Нет активных операций для отмены\\.", parse_mode="MarkdownV2")

    async def run(self):
        logger.info(f"Запуск {Config.BOT_NAME}...")
        logger.info("Система ИИ агентов активирована (упрощенная версия)")

        if not Config.BOT_TOKEN:
            logger.error("BOT_TOKEN не установлен в конфигурации!")
            return

        if not self.ai.has_api_key("openai") and not self.ai.has_api_key("anthropic"):
            logger.warning("Нет API ключей для ИИ провайдеров!")

        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")
        finally:
            await self.bot.session.close()

def ensure_directories():
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    os.makedirs(Config.USERS_DIR, exist_ok=True)

    os.makedirs(os.path.join(Config.DATA_DIR, "rag_indexes"), exist_ok=True)
    os.makedirs(os.path.join(Config.DATA_DIR, "rag_logs"), exist_ok=True)
    
    # Директории для новой системы агентов
    os.makedirs(os.path.join(Config.DATA_DIR, "agents"), exist_ok=True)
    os.makedirs(os.path.join(Config.DATA_DIR, "agents", "users"), exist_ok=True)
    os.makedirs(os.path.join(Config.DATA_DIR, "agents", "configs"), exist_ok=True)

async def main():
    ensure_directories()
    bot = AIBot()    
    # Запускаем исполнитель рассылок
    await bot.spam_executor.start()    
    await activity_logger.start()

    try:
        await bot.run()
    finally:
        # Останавливаем исполнитель рассылок
        await bot.spam_executor.stop()
        await activity_logger.stop()

if __name__ == "__main__":
    asyncio.run(main())