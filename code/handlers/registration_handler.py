# code/handlers/registration_handler.py
"""
Модуль обработки регистрации пользователей
"""
import re
import logging
from datetime import datetime
from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

from utils.markdown_utils import escape_markdown_v2

# FSM состояния для регистрации
class Registration(StatesGroup):
    name_surname = State()
    company = State()  # Новое состояние
    position = State()
    department = State()
    email = State()
    telegram_username = State()


class EmailVerification(StatesGroup):
    enter_code = State()


class RegistrationHandler:
    """Обработчик регистрации и настроек пользователя"""
    
    def __init__(self, bot, user_manager, email_service):
        self.bot = bot
        self.user_manager = user_manager
        self.email_service = email_service
    
    def register_handlers(self, dp):
        """Регистрация обработчиков в диспетчере"""
        # Команда настроек
        dp.message.register(self.cmd_settings, F.text == "/settings")
        
        # Обработчики состояний регистрации
        dp.message.register(self.process_name_surname, Registration.name_surname)
        dp.message.register(self.process_company, Registration.company)  # Новый обработчик
        dp.message.register(self.process_position, Registration.position)
        dp.message.register(self.process_department, Registration.department)
        dp.message.register(self.process_email, Registration.email)
        dp.message.register(self.process_telegram_username, Registration.telegram_username)
        
        # Обработчик верификации email
        dp.message.register(self.process_verification_code, EmailVerification.enter_code)
        
        # Callback для верификации email
        dp.callback_query.register(
            self.handle_settings_callback,
            F.data == "verify_email"
        )
    
    async def start_registration(self, message: types.Message, state: FSMContext):
        """Начало процесса регистрации"""
        from config import Config
        text = (
            f"Добро пожаловать в *{escape_markdown_v2(Config.BOT_NAME)}*\\!\n\n"
            "Для начала работы необходимо пройти регистрацию\\.\n"
            "Введите ваши *Имя и Фамилию* \\(через пробел\\):\n"
            "Например: Иван Иванов"
        )
        await message.reply(text, parse_mode="MarkdownV2")
        await state.set_state(Registration.name_surname)

    
    async def process_name_surname(self, message: types.Message, state: FSMContext):
        """Обработка имени и фамилии при регистрации"""
        text = message.text.replace('\n', ' ').replace('\r', ' ').strip()
        text = ' '.join(text.split())
    
        is_valid, name, surname = self._validate_name_surname(text)
    
        if not is_valid:
            error_text = (
                "❌ *Некорректный ввод\\.*\n\n"
                "*Требования:*\n"
                "• Введите Имя и Фамилию через пробел\n"
                "• Минимум 2 буквы в каждом слове\n"
                "• Используйте только буквы \\(русские или английские\\)\n"
                "• Допускаются дефис и апостроф \\(О'Нил, Анна\\-Мария\\)\n"
                "• Не более 2 одинаковых букв подряд\n\n"
                "Например: Андрей Петров"
            )
            await message.reply(error_text, parse_mode="MarkdownV2")
            return
    
        await state.update_data(name=name, surname=surname)
        text = f"Отлично, *{escape_markdown_v2(name)} {escape_markdown_v2(surname)}*\\!\nТеперь введите название вашей компании:"
        await message.reply(text, parse_mode="MarkdownV2")
        await state.set_state(Registration.company)
    
    async def process_company(self, message: types.Message, state: FSMContext):
        """Обработка названия компании при регистрации"""
        text = message.text.replace('\n', ' ').replace('\r', ' ').strip()
        text = ' '.join(text.split())
    
        if not self._validate_text_field(text, min_length=2):
            error_text = (
                "❌ *Некорректное название компании\\.*\n"
                "Название должно содержать минимум 2 символа\\.\n"
                "Попробуйте еще раз:"
            )
            await message.reply(error_text, parse_mode="MarkdownV2")
            return
    
        await state.update_data(company=text)
        await message.reply("Введите вашу должность:", parse_mode="MarkdownV2")
        await state.set_state(Registration.position)
    
    async def process_position(self, message: types.Message, state: FSMContext):
        """Обработка должности при регистрации"""
        text = message.text.replace('\n', ' ').replace('\r', ' ').strip()
        text = ' '.join(text.split())
    
        if not self._validate_text_field(text, min_length=3):
            error_text = (
                "❌ *Некорректная должность\\.*\n"
                "Должность должна содержать минимум 3 символа\\.\n"
                "Попробуйте еще раз:"
            )
            await message.reply(error_text, parse_mode="MarkdownV2")
            return
    
        await state.update_data(position=text)
        await message.reply("Введите ваш проект или отдел:", parse_mode="MarkdownV2")
        await state.set_state(Registration.department)
    
    async def process_department(self, message: types.Message, state: FSMContext):
        """Обработка отдела при регистрации"""
        text = message.text.replace('\n', ' ').replace('\r', ' ').strip()
        text = ' '.join(text.split())
    
        if not self._validate_text_field(text, min_length=2):
            error_text = (
                "❌ *Некорректный отдел/проект\\.*\n"
                "Название должно содержать минимум 2 символа\\.\n"
                "Попробуйте еще раз:"
            )
            await message.reply(error_text, parse_mode="MarkdownV2")
            return
    
        await state.update_data(department=text)
        await message.reply("Введите ваш рабочий email:", parse_mode="MarkdownV2")
        await state.set_state(Registration.email)
    
    async def process_email(self, message: types.Message, state: FSMContext):
        """Обработка email"""
        email = message.text.strip().lower()
    
        if not self._validate_email(email):
            error_text = (
                "❌ *Некорректный email\\.*\n"
                "Пожалуйста, введите валидный email адрес\\.\n"
                "Например: user@company\\.com"
            )
            await message.reply(error_text, parse_mode="MarkdownV2")
            return
    
        await state.update_data(email=email)
    
        # Получаем username пользователя из Telegram
        tg_username = message.from_user.username
    
        if tg_username:
            # Если username есть, сохраняем автоматически
            await state.update_data(telegram_username=f"@{tg_username}")
            text = (
                f"Ваш Telegram username: *@{escape_markdown_v2(tg_username)}*\n"
                "Подтвердите регистрацию командой /confirm или измените username, отправив его в формате @username"
            )
            await message.reply(text, parse_mode="MarkdownV2")
        else:
            text = (
                "У вас не установлен username в Telegram\\.\n"
                "Введите желаемый никнейм для связи \\(в формате @username\\)\n"
                "или отправьте '\\-' если не хотите указывать:"
            )
            await message.reply(text, parse_mode="MarkdownV2")
    
        await state.set_state(Registration.telegram_username)
    
    async def process_telegram_username(self, message: types.Message, state: FSMContext):
        """Обработка telegram username и завершение регистрации"""
        text = message.text.strip()
    
        # Если пользователь подтверждает автоматически полученный username
        if text == "/confirm":
            user_data = await state.get_data()
            if "telegram_username" not in user_data:
                await message.reply("Ошибка: username не найден\\. Введите его вручную:", parse_mode="MarkdownV2")
                return
        else:
            # Валидация username
            if text == "-":
                await state.update_data(telegram_username="Не указан")
            elif text.startswith("@"):
                # Проверка формата username
                username = text[1:]
                if len(username) >= 5 and username.replace("_", "").isalnum():
                    await state.update_data(telegram_username=text)
                else:
                    error_text = (
                        "❌ *Некорректный username\\.*\n"
                        "*Username должен:*\n"
                        "\\- Начинаться с @\n"
                        "\\- Содержать минимум 5 символов\n"
                        "\\- Использовать только буквы, цифры и \\_\n"
                        "Попробуйте еще раз:"
                    )
                    await message.reply(error_text, parse_mode="MarkdownV2")
                    return
            else:
                error_text = (
                    "❌ Username должен начинаться с @\n"
                    "Например: @ivan\\_petrov\n"
                    "Или отправьте '\\-' если не хотите указывать"
                )
                await message.reply(error_text, parse_mode="MarkdownV2")
                return
    
        # Завершение регистрации
        user_data = await state.get_data()
        user_id = str(message.from_user.id)
    
        # Добавляем автоматически полученный username если его не было
        if "telegram_username" not in user_data:
            user_data["telegram_username"] = f"@{message.from_user.username}" if message.from_user.username else "Не указан"
    
        if await self.user_manager.create_user(user_id, user_data):
            success_text = (
                "✅ *Регистрация успешно завершена\\!*\n\n"
                f"*Имя:* {escape_markdown_v2(user_data['name'])} {escape_markdown_v2(user_data['surname'])}\n"
                f"*Компания:* {escape_markdown_v2(user_data['company'])}\n"  # Добавляем вывод компании
                f"*Должность:* {escape_markdown_v2(user_data['position'])}\n"
                f"*Отдел:* {escape_markdown_v2(user_data['department'])}\n"
                f"*Email:* {escape_markdown_v2(user_data['email'])}\n"
                f"*Telegram:* {escape_markdown_v2(user_data['telegram_username'])}\n\n"
                "⏳ Ожидайте активации аккаунта администратором\\.\n\n"
                "📨 Для связи с администратором пишите в ЛС @d00m4ace"
            )
            await message.reply(success_text, parse_mode="MarkdownV2")
            logger.info(f"Новая регистрация: {user_id} - {user_data['name']} {user_data['surname']} - {user_data['company']} - {user_data['telegram_username']}")
        else:
            await message.reply("Ошибка при регистрации\\. Возможно, вы уже зарегистрированы\\.", parse_mode="MarkdownV2")
    
        await state.clear()
    
    async def cmd_settings(self, message: types.Message):
        """Показывает настройки пользователя"""
        user_id = str(message.from_user.id)
    
        if not await self.user_manager.user_exists(user_id):
            text = "Вы не зарегистрированы\\. Используйте /start для регистрации\\."
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        user = await self.user_manager.get_user(user_id)
    
        # Формируем текст настроек
        email = user.get("email", "Не указан")
        email_verified = user.get("email_verified", False)
    
        text = (
            "⚙️ *Настройки профиля*\n\n"
            f"🆔 *Telegram ID:* `{user_id}`\n"
            f"👤 *Имя:* {escape_markdown_v2(user.get('name', ''))} {escape_markdown_v2(user.get('surname', ''))}\n"
            f"🏢 *Компания:* {escape_markdown_v2(user.get('company', 'Не указана'))}\n"  # Добавляем вывод компании
            f"💼 *Должность:* {escape_markdown_v2(user.get('position', 'Не указана'))}\n"
            f"🏢 *Отдел:* {escape_markdown_v2(user.get('department', 'Не указан'))}\n"
            f"📧 *Email:* {escape_markdown_v2(email)}\n"
        )
    
        if email_verified:
            text += "✅ Email подтвержден\n"
        else:
            text += "❌ Email не подтвержден\n"
    
        text += f"\n💬 *Telegram:* {escape_markdown_v2(user.get('telegram_username', 'Не указан'))}\n"
        text += f"🔐 *Статус:* {'✅ Активен' if user.get('active', False) else '⏳ Ожидает активации'}\n"
    
        if user.get('admin', False):
            text += "👑 Администратор\n"
    
        # Добавляем дату регистрации если есть
        if user.get('created_at'):
            created_date = user['created_at'][:10] if len(user['created_at']) > 10 else user['created_at']
            text += f"📅 *Зарегистрирован:* {escape_markdown_v2(created_date)}\n"
    
        # Добавляем кнопки действий
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
        from config import Config
        if not email_verified and email != "Не указан" and Config.EMAIL_ENABLED:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text="📧 Подтвердить email",
                    callback_data="verify_email"
                )
            ])
    
        await message.reply(text, reply_markup=keyboard if keyboard.inline_keyboard else None, parse_mode="MarkdownV2")

    async def handle_settings_callback(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка callback для настроек"""
        user_id = str(callback.from_user.id)
        
        if callback.data == "verify_email":
            user = await self.user_manager.get_user(user_id)
            email = user.get("email", "")
            
            if not email or email == "Не указан":
                await callback.answer("Email не указан в профиле", show_alert=True)
                return
            
            if user.get("email_verified", False):
                await callback.answer("Email уже подтвержден", show_alert=True)
                return
            
            # Отправляем код
            await callback.message.edit_text("📧 Отправляем код подтверждения...")
            
            user_name = f"{user.get('name', '')} {user.get('surname', '')}".strip()
            code = await self.email_service.send_verification_code(user_id, email, user_name)
            
            if code:
                await callback.message.edit_text(
                    f"✉️ Код подтверждения отправлен на {email}\n\n"
                    "Введите 6-значный код из письма:"
                )
                await state.set_state(EmailVerification.enter_code)
                logger.info(f"Verification code sent to {email} for user {user_id}")
            else:
                await callback.message.edit_text(
                    "❌ Не удалось отправить код.\n"
                    "Проверьте правильность email или попробуйте позже."
                )
            
            await callback.answer()
    
    async def process_verification_code(self, message: types.Message, state: FSMContext):
        """Обработка кода верификации"""
        user_id = str(message.from_user.id)
        code = message.text.strip()
    
        # Проверяем формат кода
        if not code.isdigit() or len(code) != 6:
            error_text = (
                "❌ *Неверный формат кода\\.*\n"
                "Код должен состоять из 6 цифр\\.\n"
                "Попробуйте еще раз:"
            )
            await message.reply(error_text, parse_mode="MarkdownV2")
            return
    
        # Проверяем код
        success, result = self.email_service.verify_code(user_id, code)
    
        if success:
            # Обновляем статус верификации
            await self.user_manager.verify_email(user_id)
            success_text = (
                f"✅ *Email успешно подтвержден\\!*\n"
                f"📧 {escape_markdown_v2(result)}"
            )
            await message.reply(success_text, parse_mode="MarkdownV2")
            await state.clear()
            logger.info(f"Email verified for user {user_id}")
        else:
            await message.reply(f"❌ {escape_markdown_v2(result)}", parse_mode="MarkdownV2")
            if "Код не найден" in result or "Код истек" in result or "Превышено" in result:
                await state.clear()
    
    # Вспомогательные методы валидации
    def _validate_name_surname(self, text: str) -> tuple[bool, str, str]:
        """Проверка и разбор имени и фамилии"""
        parts = text.strip().split()
        
        if len(parts) < 2:
            return False, "", ""
        
        name = parts[0]
        surname = ' '.join(parts[1:])
        
        # Проверка минимальной длины
        if len(name) < 2 or len(surname) < 2:
            return False, "", ""
        
        # Проверка, что имя и фамилия содержат только буквы (любого алфавита), дефисы и апострофы
        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                            "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
                            "-' ")
        
        # Проверка каждого символа
        for char in name + surname:
            if char not in allowed_chars:
                return False, "", ""
        
        # Проверка, что имя и фамилия начинаются с буквы
        if not name[0].isalpha() or not surname[0].isalpha():
            return False, "", ""
        
        # Проверка на слишком много повторяющихся символов подряд
        for part in [name, surname]:
            for i in range(len(part) - 2):
                if part[i] == part[i+1] == part[i+2] and part[i].isalpha():
                    return False, "", ""
        
        # Делаем первую букву заглавной
        name = name[0].upper() + name[1:].lower()
        surname = surname[0].upper() + surname[1:].lower()
        
        return True, name, surname
    
    def _validate_email(self, email: str) -> bool:
        """Проверка валидности email"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def _validate_text_field(self, text: str, min_length: int = 2) -> bool:
        """Базовая валидация текстового поля"""
        return len(text.strip()) >= min_length