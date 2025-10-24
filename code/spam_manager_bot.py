# code/spam_manager_bot.py
"""
Телеграм бот для управления рассылками основного бота
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import StateFilter

import holidays  # pip install holidays

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('spam_manager.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================
# КОНФИГУРАЦИЯ
# ============================================

# Токен бота-менеджера рассылок (укажите свой)
SPAM_BOT_TOKEN = "83...iM" # @hc_spam_bot
#SPAM_BOT_TOKEN = "80...Zg" # @d4_spm_bot

# ID пользователей, которые могут управлять рассылками
AUTHORIZED_USERS = [
    1119720393,  # Андрей Петров (админ)
    # Добавьте сюда ID других администраторов
    123456789 # пример
]

# Пути к файлам
SPAM_GROUP_FILE = os.path.join("sputnkik_bot_users", "spam_group.json")
SPAM_FILE = os.path.join("sputnkik_bot_users", "spam.json")
DOC_ACCESS_FILE = os.path.join("NETHACK/herocraft", "doc_access.json")
USERS_FILE = os.path.join("sputnkik_bot_users", "users.json")

# ============================================
# ПРАЗДНИКИ И ВЫХОДНЫЕ РФ
# ============================================

def is_working_day(date: datetime) -> bool:
    """
    Проверяет, является ли день рабочим (не выходной и не праздник).
    Использует библиотеку holidays для определения праздников РФ.
    """
    # Получаем праздники России
    ru_holidays = holidays.Russia(years=date.year)
    
    # Проверка выходных (суббота=5, воскресенье=6)
    if date.weekday() >= 5:
        return False
    
    # Проверка праздников
    if date.date() in ru_holidays:
        return False
    
    return True

def get_next_working_day(date: datetime, keep_time: bool = True, stay_in_month: bool = False) -> datetime:
    """
    Возвращает следующий рабочий день.
    
    Args:
        date: исходная дата
        keep_time: сохранять ли время из исходной даты
        stay_in_month: если True, не выходить за границы текущего месяца
    
    Returns:
        Следующий рабочий день
    """
    original_time = date.time() if keep_time else datetime.min.time()
    original_month = date.month
    original_year = date.year
    current = date
    
    # Ищем следующий рабочий день
    while not is_working_day(current):
        current += timedelta(days=1)
        
        # Если вышли за границы месяца и нужно остаться в месяце
        if stay_in_month and (current.month != original_month or current.year != original_year):
            return None  # Не нашли рабочий день в текущем месяце
    
    # Восстанавливаем время, если нужно
    if keep_time:
        current = datetime.combine(current.date(), original_time)
    
    return current

def get_previous_working_day(date: datetime, keep_time: bool = True, stay_in_month: bool = False) -> datetime:
    """
    Возвращает предыдущий рабочий день.
    
    Args:
        date: исходная дата
        keep_time: сохранять ли время из исходной даты
        stay_in_month: если True, не выходить за границы текущего месяца
    
    Returns:
        Предыдущий рабочий день или None, если не нашли в текущем месяце
    """
    original_time = date.time() if keep_time else datetime.min.time()
    original_month = date.month
    original_year = date.year
    current = date - timedelta(days=1)
    
    # Ищем предыдущий рабочий день
    while not is_working_day(current):
        current -= timedelta(days=1)
        
        # Если вышли за границы месяца и нужно остаться в месяце
        if stay_in_month and (current.month != original_month or current.year != original_year):
            return None  # Не нашли рабочий день в текущем месяце
    
    # Восстанавливаем время, если нужно
    if keep_time:
        current = datetime.combine(current.date(), original_time)
    
    return current

def get_working_day_in_same_month(date: datetime, keep_time: bool = True) -> datetime:
    """
    Находит рабочий день в том же месяце.
    Сначала пытается перенести вперёд, если это ведёт в другой месяц - переносит назад.
    
    Args:
        date: исходная дата
        keep_time: сохранять ли время из исходной даты
    
    Returns:
        Ближайший рабочий день в том же месяце
    """
    if is_working_day(date):
        return date
    
    original_month = date.month
    original_year = date.year
    original_time = date.time() if keep_time else datetime.min.time()
    
    # Пробуем перенести вперёд в пределах месяца
    forward_date = get_next_working_day(date, keep_time, stay_in_month=True)
    
    # Если нашли рабочий день вперёд в том же месяце - отлично
    if forward_date is not None:
        return forward_date
    
    # Иначе ищем назад в пределах месяца
    backward_date = get_previous_working_day(date, keep_time, stay_in_month=True)
    
    # Если нашли назад в том же месяце
    if backward_date is not None:
        return backward_date
    
    # Критическая ситуация: в месяце вообще нет рабочих дней
    # Такое практически невозможно, но на всякий случай возвращаем следующий рабочий день
    logger = logging.getLogger(__name__)
    logger.warning(
        f"⚠️ КРИТИЧНО: В месяце {original_month}/{original_year} "
        f"не найдено рабочих дней вокруг {date.strftime('%d.%m.%Y')}! "
        f"Переносим на следующий доступный рабочий день"
    )
    
    # Возвращаем следующий рабочий день без ограничения по месяцу
    return get_next_working_day(date, keep_time, stay_in_month=False)

def format_next_send_with_workdays(next_send_str: str, stay_in_month: bool = True) -> str:
    """
    Форматирует дату следующей отправки с учётом рабочих дней.
    Если дата попадает на выходной/праздник, возвращает ближайший рабочий день.
    
    Args:
        next_send_str: строка с датой в формате ISO
        stay_in_month: если True, переносит дату в пределах того же месяца
    
    Returns:
        Форматированная строка с датой и информацией о переносе
    """
    try:
        next_send = datetime.fromisoformat(next_send_str)
        
        # Если это не рабочий день, находим ближайший рабочий
        if not is_working_day(next_send):
            if stay_in_month:
                working_day = get_working_day_in_same_month(next_send)
            else:
                working_day = get_next_working_day(next_send)
            
            # Определяем причину переноса
            ru_holidays = holidays.Russia(years=next_send.year)
            if next_send.date() in ru_holidays:
                holiday_name = ru_holidays.get(next_send.date())
                reason = f"праздник: {holiday_name}"
            else:
                weekday_names = {5: "суббота", 6: "воскресенье"}
                reason = weekday_names.get(next_send.weekday(), "выходной")
            
            # Определяем направление переноса
            if working_day > next_send:
                direction = "➡️"
                direction_text = "вперёд"
            else:
                direction = "⬅️"
                direction_text = "назад"
            
            # Если остались в том же месяце
            if working_day.month == next_send.month and working_day.year == next_send.year:
                month_note = f" (остаёмся в {next_send.strftime('%B')})"
            else:
                month_note = f" (⚠️ перенос в {working_day.strftime('%B')})"
            
            return (
                f"<s>{next_send.strftime('%d.%m.%Y %H:%M')}</s> "
                f"{direction} <b>{working_day.strftime('%d.%m.%Y %H:%M')}</b> "
                f"<i>({reason}, {direction_text}{month_note})</i>"
            )
        
        return next_send.strftime('%d.%m.%Y %H:%M')
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка форматирования даты: {e}")
        return next_send_str

def get_holiday_name(date: datetime) -> Optional[str]:
    """Возвращает название праздника, если дата является праздником"""
    ru_holidays = holidays.Russia(years=date.year)
    return ru_holidays.get(date.date())

def get_transfer_direction_info(original_date: datetime, working_day: datetime) -> dict:
    """
    Возвращает информацию о направлении переноса даты.
    
    Args:
        original_date: исходная дата
        working_day: дата после переноса
    
    Returns:
        dict с ключами: direction (str), emoji (str), in_same_month (bool)
    """
    if working_day > original_date:
        direction = "вперёд"
        emoji = "➡️"
    else:
        direction = "назад"
        emoji = "⬅️"
    
    in_same_month = (
        working_day.month == original_date.month and 
        working_day.year == original_date.year
    )
    
    return {
        "direction": direction,
        "emoji": emoji,
        "in_same_month": in_same_month
    }

# ============================================
# FSM СОСТОЯНИЯ
# ============================================

def escape_markdown_v2(text: str) -> str:
    """Экранирование специальных символов для MarkdownV2"""
    if not text:
        return text
    # Символы, которые нужно экранировать в MarkdownV2
    escape_chars = '_*[]()~`>#+-=|{}.!'
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

# ============================================
# FSM СОСТОЯНИЯ
# ============================================

class CreateGroup(StatesGroup):
    await_group_key = State()
    await_group_name = State()
    
class ManageGroup(StatesGroup):
    await_user_id = State()
    await_action = State()
    await_import_list = State() # НОВОЕ: ожидание списка для импорта

class CreateBroadcast(StatesGroup):
    select_type = State()
    select_groups = State()
    enter_text = State()
    enter_link = State()
    select_date = State()  # Новое состояние для выбора даты
    select_time = State()  # Новое состояние для выбора времени
    enter_datetime = State()  # Оставим для ручного ввода как опцию
    enter_period = State()
    confirm = State()

# ============================================
# МЕНЕДЖЕР ДАННЫХ
# ============================================

class DataManager:
    """Управление данными рассылок и пользователей"""
    
    # ============================================
    # ГРУППЫ РАССЫЛКИ (вместо doc_access.json)
    # ============================================

    @staticmethod
    def load_spam_groups() -> Dict:
        """Загрузка групп рассылок"""               
        if os.path.exists(SPAM_GROUP_FILE):
            try:
                with open(SPAM_GROUP_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Ошибка загрузки spam_group.json: {e}")
        return {"groups": {}}

    @staticmethod
    def save_spam_groups(data: Dict):
        """Сохранение групп рассылок"""
        try:
            with open(SPAM_GROUP_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения spam_group.json: {e}")

    @staticmethod
    def add_group(group_key: str, name: str):
        """Создание новой группы"""
        data = DataManager.load_spam_groups()
        if group_key in data["groups"]:
            raise ValueError("Группа с таким ID уже существует")
        data["groups"][group_key] = {"name": name, "users": []}
        DataManager.save_spam_groups(data)

    @staticmethod
    def add_user_to_group(group_key: str, user_id: int):
        """Добавить пользователя в группу"""
        data = DataManager.load_spam_groups()
        if group_key not in data["groups"]:
            raise ValueError("Группа не найдена")
        if user_id not in data["groups"][group_key]["users"]:
            data["groups"][group_key]["users"].append(user_id)
            DataManager.save_spam_groups(data)

    @staticmethod
    def remove_user_from_group(group_key: str, user_id: int):
        """Удалить пользователя из группы"""
        data = DataManager.load_spam_groups()
        if group_key in data["groups"] and user_id in data["groups"][group_key]["users"]:
            data["groups"][group_key]["users"].remove(user_id)
            DataManager.save_spam_groups(data)

    @staticmethod
    def get_available_groups() -> Dict:
        """Переопределено: теперь берём группы из spam_group.json"""
        return DataManager.load_spam_groups().get("groups", {})        
    
    @staticmethod
    def load_spam_data() -> Dict:
        """Загрузка данных о рассылках"""
        default_data = {
            "broadcasts": [],
            "last_check": None,
            "stats": {
                "total_sent": 0,
                "total_scheduled": 0
            }
        }
        
        if os.path.exists(SPAM_FILE):
            try:
                with open(SPAM_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # Убеждаемся, что все необходимые поля существуют
                    if "broadcasts" not in data:
                        data["broadcasts"] = []
                    if "stats" not in data:
                        data["stats"] = {}
                    if "total_sent" not in data["stats"]:
                        data["stats"]["total_sent"] = 0
                    if "total_scheduled" not in data["stats"]:
                        data["stats"]["total_scheduled"] = 0
                    
                    return data
            except Exception as e:
                logger.error(f"Ошибка загрузки spam.json: {e}")
                return default_data
        
        return default_data
    
    @staticmethod
    def save_spam_data(data: Dict):
        """Сохранение данных о рассылках"""
        try:
            with open(SPAM_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("Данные рассылок сохранены")
        except Exception as e:
            logger.error(f"Ошибка сохранения spam.json: {e}")
    
    @staticmethod
    def load_doc_access() -> Dict:
        """Загрузка групп пользователей"""
        try:
            with open(DOC_ACCESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки doc_access.json: {e}")
            return {"groups": {}}
    
    @staticmethod
    def load_users() -> Dict:
        """Загрузка данных пользователей"""
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                jsn = json.load(f)
                #print(jsn)
                return jsn
                #return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки users.json: {e}")
            return {}
        
    @staticmethod
    def get_users_by_groups(group_keys: List[str]) -> List[int]:
        """
        Возвращает список user_id по ключам групп из spam_group.json.
        Учитывает только активных пользователей из users.json.
        """
        groups_data = DataManager.load_spam_groups()
        users_data = DataManager.load_users()
        all_user_ids = set()

        for group_key in group_keys:
            group_info = groups_data.get("groups", {}).get(group_key)
            if not group_info:
                continue

            for user_id in group_info.get("users", []):
                user_id_str = str(user_id)
                if user_id_str in users_data and users_data[user_id_str].get("active", False):
                    all_user_ids.add(user_id)

        return list(all_user_ids)

    @staticmethod
    def add_broadcast(broadcast_data: Dict) -> str:
        """Добавление новой рассылки (без сохранения user_ids)"""
        from uuid import uuid4
        
        spam_data = DataManager.load_spam_data()
        
        # Генерируем уникальный ID
        broadcast_id = str(uuid4())[:8]
        broadcast_data["id"] = broadcast_id
        broadcast_data["created_at"] = datetime.now().isoformat()
        broadcast_data["status"] = "scheduled"
        broadcast_data["sent_count"] = 0
        broadcast_data["last_sent"] = None
        
        # ВАЖНО: Удаляем target_user_ids, не сохраняем ID пользователей
        if "target_user_ids" in broadcast_data:
            del broadcast_data["target_user_ids"]
        
        spam_data["broadcasts"].append(broadcast_data)
        
        # Безопасное обновление статистики
        if "stats" not in spam_data:
            spam_data["stats"] = {}
        if "total_scheduled" not in spam_data["stats"]:
            spam_data["stats"]["total_scheduled"] = 0
        spam_data["stats"]["total_scheduled"] += 1
        
        DataManager.save_spam_data(spam_data)
        
        return broadcast_id

# ============================================
# БОТ-МЕНЕДЖЕР РАССЫЛОК
# ============================================

class SpamManagerBot:
    def __init__(self):
        self.bot = Bot(token=SPAM_BOT_TOKEN)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.setup_handlers()
    
    def setup_handlers(self):
        """Регистрация обработчиков"""

        # ==============================
        # 🔹 Команды
        # ==============================
        self.dp.message.register(self.cmd_start, F.text == "/start")
        self.dp.message.register(self.cmd_help, F.text == "/help")
        self.dp.message.register(self.cmd_create, F.text == "/create")
        self.dp.message.register(self.cmd_list, F.text == "/list")
        self.dp.message.register(self.cmd_delete, F.text.startswith("/delete_"))
        self.dp.message.register(self.cmd_stats, F.text == "/stats")

        # ==============================
        # 🔹 Управление группами
        # ==============================
        self.dp.message.register(self.cmd_groups, F.text == "/groups")
        self.dp.message.register(self.cmd_group_create, F.text == "/group_create")
        self.dp.message.register(self.process_group_key, CreateGroup.await_group_key)
        self.dp.message.register(self.process_group_name, CreateGroup.await_group_name)
        self.dp.callback_query.register(self.process_import_list, F.data.startswith("import|"))
        self.dp.message.register(self.process_import_list_input, ManageGroup.await_import_list)

        # Главное меню управления группой
        self.dp.callback_query.register(self.process_group_manage, F.data.startswith("manage_"))
        
        self.dp.callback_query.register(self.process_add_user, F.data.startswith("adduser|"), StateFilter("*"))
        self.dp.callback_query.register(self.process_remove_user, F.data.startswith("deluser|"), StateFilter("*"))
        self.dp.callback_query.register(self.confirm_add_user, F.data.startswith("addconfirm|"), StateFilter("*"))
        self.dp.callback_query.register(self.confirm_remove_user, F.data.startswith("remove|"), StateFilter("*"))        

        self.dp.callback_query.register(self.process_cancel, F.data.startswith("cancel|"))
        self.dp.callback_query.register(self.process_manage_back, F.data.startswith("manage|"))

        self.dp.callback_query.register(self.process_list_users, F.data.startswith("listusers|"))

        # Ввод ID вручную
        self.dp.message.register(self.process_add_user_input, ManageGroup.await_user_id)

        self.dp.message.register(self.cmd_check_workday, F.text.startswith("/check_workday"))

        # ==============================
        # 🔹 FSM: создание рассылок
        # ==============================
        self.dp.callback_query.register(self.process_broadcast_type, CreateBroadcast.select_type)
        self.dp.callback_query.register(self.process_group_selection, CreateBroadcast.select_groups)
        self.dp.message.register(self.process_text_input, CreateBroadcast.enter_text)
        self.dp.message.register(self.process_link_input, CreateBroadcast.enter_link)

        # Выбор даты и времени
        self.dp.callback_query.register(self.process_date_selection, CreateBroadcast.select_date)
        self.dp.callback_query.register(self.process_time_selection, CreateBroadcast.select_time)

        # Ручной ввод даты / периода
        self.dp.message.register(self.process_datetime_input, CreateBroadcast.enter_datetime)
        self.dp.message.register(self.process_period_input, CreateBroadcast.enter_period)

        # Подтверждение рассылки
        self.dp.callback_query.register(self.process_confirmation, CreateBroadcast.confirm)


    async def process_import_list(self, callback: types.CallbackQuery, state: FSMContext):
        """Начало импорта списка пользователей"""
        parts = callback.data.split("|")
        if len(parts) < 2:
            await callback.answer("Ошибка формата данных!", show_alert=True)
            return
    
        group_id = parts[1]
        groups = DataManager.get_available_groups()
    
        if group_id not in groups:
            await callback.answer("Группа не найдена!", show_alert=True)
            return
    
        group = groups[group_id]
    
        await state.update_data(import_group_id=group_id)
        await state.set_state(ManageGroup.await_import_list)
    
        await callback.message.edit_text(
            f"📋 <b>Импорт пользователей в группу: {group['name']}</b>\n\n"
            "Отправьте текст с никами пользователей в любом формате.\n"
            "Бот автоматически найдёт все ники Telegram (с @ или без) и добавит их в группу.\n\n"
            "<b>Примеры форматов:</b>\n"
            "<code>@username1 @username2\n"
            "Список: username3, username4\n"
            "Имя (@username5)</code>\n\n"
            "⚠️ <b>Формат не важен</b> — бот найдёт все ники автоматически!\n\n"
            "Отправьте /cancel для отмены.",
            parse_mode="HTML"
        )
        await callback.answer()

    async def process_import_list_input(self, message: types.Message, state: FSMContext):
        """Обработка импортированного списка пользователей"""
        import re
        
        if message.text == "/cancel":
            await message.reply("❌ Импорт отменён")
            await state.clear()
            return
    
        data = await state.get_data()
        group_id = data.get("import_group_id")
    
        if not group_id:
            await message.reply("❌ Ошибка: группа не найдена")
            await state.clear()
            return
    
        groups_data = DataManager.load_spam_groups()
        users_data = DataManager.load_users()
    
        if group_id not in groups_data.get("groups", {}):
            await message.reply("❌ Группа не найдена в базе данных")
            await state.clear()
            return
    
        group = groups_data["groups"][group_id]
    
        # НОВЫЙ ПАРСИНГ: ищем все ники telegram в тексте
        # Ник может быть с @ или без, состоит из букв, цифр и подчёркиваний
        pattern = r'@?([a-zA-Z0-9_]{5,32})\b'
        found_usernames = re.findall(pattern, message.text)
        
        # Убираем дубликаты и приводим к нижнему регистру
        found_usernames = list(set(username.lower() for username in found_usernames))
    
        found_users = []
        not_found = []
        already_in_group = []
    
        # Создаём словарь username -> user_id для быстрого поиска
        username_to_id = {}
        username_to_name = {}
        for user_id, user_info in users_data.items():
            username = user_info.get("telegram_username", "").strip().lower()
            if username:
                # Убираем @ если есть
                username = username.lstrip("@")
                username_to_id[username] = int(user_id)
                # Сохраняем полное имя для отчёта
                name = user_info.get("name", "")
                surname = user_info.get("surname", "")
                full_name = f"{name} {surname}".strip() or "Без имени"
                username_to_name[username] = full_name
    
        # Обрабатываем найденные username
        for username in found_usernames:
            if username in username_to_id:
                user_id = username_to_id[username]
                user_name = username_to_name[username]
            
                # Проверяем, не в группе ли уже
                if user_id in group.get("users", []):
                    already_in_group.append(f"{user_name} (@{username})")
                else:
                    # Добавляем в группу
                    if "users" not in group:
                        group["users"] = []
                    group["users"].append(user_id)
                    found_users.append(f"{user_name} (@{username})")
            else:
                # Пользователь не найден в базе
                not_found.append(f"@{username}")
    
        # Сохраняем изменения
        if found_users:
            DataManager.save_spam_groups(groups_data)
    
        # Формируем отчёт
        report = f"📊 <b>Результаты импорта в группу: {group['name']}</b>\n\n"
        report += f"🔍 <b>Найдено ников в тексте: {len(found_usernames)}</b>\n\n"
    
        if found_users:
            report += f"✅ <b>Добавлено пользователей: {len(found_users)}</b>\n"
            for user in found_users[:10]:  # Показываем первые 10
                report += f"  • {user}\n"
            if len(found_users) > 10:
                report += f"  ... и ещё {len(found_users) - 10}\n"
            report += "\n"
    
        if already_in_group:
            report += f"ℹ️ <b>Уже в группе: {len(already_in_group)}</b>\n"
            for user in already_in_group[:5]:  # Показываем первые 5
                report += f"  • {user}\n"
            if len(already_in_group) > 5:
                report += f"  ... и ещё {len(already_in_group) - 5}\n"
            report += "\n"
    
        if not_found:
            report += f"❌ <b>Не найдено в базе: {len(not_found)}</b>\n"
            for user in not_found[:10]:  # Показываем первые 10
                report += f"  • {user}\n"
            if len(not_found) > 10:
                report += f"  ... и ещё {len(not_found) - 10}\n"
            report += "\n"
    
        if not found_users and not already_in_group:
            report += "⚠️ Ни один пользователь не был добавлен.\n"
            report += "Проверьте наличие пользователей в базе users.json."
    
        await message.reply(report, parse_mode="HTML")
        await state.clear()

    async def process_list_users(self, callback: types.CallbackQuery, state: FSMContext):
        """Постраничный просмотр пользователей в группе"""
        try:
            parts = callback.data.split("|")
            if len(parts) < 3:
                await callback.answer("Ошибка формата данных!", show_alert=True)
                return

            group_id = parts[1]
            page = int(parts[2]) if parts[2].isdigit() else 1
            page_size = 25

            groups = DataManager.get_available_groups()
            users_data = DataManager.load_users()

            group_id = group_id.strip().lower()
            group_keys = {k.strip().lower(): k for k in groups.keys()}
            if group_id not in group_keys:
                await callback.answer("Группа не найдена!", show_alert=True)
                return

            real_group_id = group_keys[group_id]
            group = groups[real_group_id]
            user_list = group.get("users", [])

            if not user_list:
                await callback.message.edit_text(
                    f"📭 В группе <b>{group['name']}</b> пока нет пользователей.",
                    parse_mode="HTML"
                )
                await callback.answer()
                return

            total_pages = max(1, (len(user_list) + page_size - 1) // page_size)
            start = (page - 1) * page_size
            end = start + page_size
            current_slice = user_list[start:end]

            text = f"👥 <b>Пользователи группы:</b> <b>{group['name']}</b>\n"
            text += f"📄 Страница {page}/{total_pages} (всего {len(user_list)})\n\n"

            for uid in current_slice:
                user = users_data.get(str(uid))
                if user:
                    name = user.get("name", "")
                    surname = user.get("surname", "")
                    full_name = f"{name} {surname}".strip() or "Без имени"
                    username = user.get("telegram_username", "")
                    text += f"• {uid} — {full_name} {username}\n"
                else:
                    text += f"• {uid} — неизвестный пользователь\n"

            # Кнопки навигации
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])

            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(text="⏪ Назад", callback_data=f"listusers|{real_group_id}|{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(text="⏩ Далее", callback_data=f"listusers|{real_group_id}|{page+1}"))
            if nav_buttons:
                keyboard.inline_keyboard.append(nav_buttons)

            # Кнопка возврата
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="🔙 Назад", callback_data=f"manage|{real_group_id}")
            ])

            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
            await callback.answer()

        except Exception as e:
            print(f"[ERROR process_list_users] {e}")
            await callback.answer("Ошибка при отображении списка пользователей!", show_alert=True)


    async def _refresh_add_user_list(self, callback: types.CallbackQuery, state: FSMContext, group_id: str, page: int = 1):
        """Перерисовка списка пользователей после добавления без изменения callback.data"""
        users_data = DataManager.load_users()
        groups = DataManager.load_spam_groups()

        if group_id not in groups.get("groups", {}):
            await callback.message.edit_text("⚠️ Группа не найдена.", parse_mode="HTML")
            return

        group = groups["groups"][group_id]
        group_users = set(group.get("users", []))

        available_users = [
            (uid, uinfo)
            for uid, uinfo in users_data.items()
            if uinfo.get("active", False) and int(uid) not in group_users
        ]

        if not available_users:
            await callback.message.edit_text("✅ Нет доступных пользователей для добавления.", parse_mode="HTML")
            return

        page_size = 25
        total_pages = max(1, (len(available_users) + page_size - 1) // page_size)
        start = (page - 1) * page_size
        end = start + page_size
        current_slice = available_users[start:end]

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{uinfo.get('name', '')} {uinfo.get('surname', '')} ({uinfo.get('telegram_username', '-')})",
                    callback_data=f"addconfirm|{group_id}|{uid}"
                )
            ]
            for uid, uinfo in current_slice
        ])

        # Навигация
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⏪ Назад", callback_data=f"adduser|{group_id}|{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="⏩ Далее", callback_data=f"adduser|{group_id}|{page+1}"))
        if nav_buttons:
            keyboard.inline_keyboard.append(nav_buttons)

        # Кнопка назад
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"manage|{group_id}")
        ])

        await callback.message.edit_text(
            f"👥 Выберите пользователя для добавления в группу <b>{group['name']}</b>\n"
            f"📄 Страница {page}/{total_pages} (всего {len(available_users)} пользователей)",
            parse_mode="HTML",
            reply_markup=keyboard
        )


    async def process_manage_back(self, callback: types.CallbackQuery, state: FSMContext):
        """Возврат в меню управления конкретной группой (по кнопке Назад)"""
        try:
            parts = callback.data.split("|")
            if len(parts) < 2:
                await callback.answer("Ошибка формата callback!", show_alert=True)
                return

            group_id = parts[1]
            groups = DataManager.get_available_groups()
            users_data = DataManager.load_users()

            if group_id not in groups:
                await callback.answer("Группа не найдена!", show_alert=True)
                return

            group = groups[group_id]
            text = f"⚙️ <b>{group['name']}</b>\n\n"

            text += "\nВыберите действие:"

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👥 Список пользователей", callback_data=f"listusers|{group_id}|1")],
                [InlineKeyboardButton(text="➕ Добавить пользователя", callback_data=f"adduser|{group_id}|1")],
                [InlineKeyboardButton(text="➖ Удалить пользователя", callback_data=f"deluser|{group_id}|1")],
                [InlineKeyboardButton(text="📋 Импорт из списка", callback_data=f"import|{group_id}")],  # НОВАЯ КНОПКА
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"cancel|{group_id}")]
            ])

            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
            await callback.answer()

        except Exception as e:
            print(f"[ERROR process_manage_back] {e}")
            await callback.answer("Ошибка при возврате!", show_alert=True)


    async def process_cancel(self, callback: types.CallbackQuery, state: FSMContext):
        """Возврат в меню групп"""
        await state.clear()
        groups = DataManager.get_available_groups()
        if not groups:
            await callback.message.edit_text("📭 Группы пока не созданы.\nИспользуй /group_create для добавления.")
            return

        text = "📋 <b>Группы рассылок:</b>\n\n"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for key, info in groups.items():
            text += f"<b>{info['name']}</b> (ID: <code>{key}</code>)\n"
            text += f"👥 {len(info.get('users', []))} пользователей\n\n"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"⚙️ Управлять {info['name']}", callback_data=f"manage_{key}")
            ])

        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()    

    async def confirm_add_user(self, callback: types.CallbackQuery, state: FSMContext):
        """Добавление пользователя в группу без закрытия списка"""
        try:
            parts = callback.data.split("|")
            if len(parts) < 3:
                await callback.answer("Ошибка формата данных!", show_alert=True)
                return

            group_id = parts[1]
            user_id = int(parts[2])

            groups = DataManager.load_spam_groups()
            users = DataManager.load_users()

            group_id = group_id.strip().lower()
            group_keys = {k.strip().lower(): k for k in groups.get("groups", {}).keys()}

            if group_id not in group_keys:
                await callback.answer("Группа не найдена!", show_alert=True)
                return

            real_group_id = group_keys[group_id]
            group = groups["groups"][real_group_id]

            # Добавляем пользователя, если его ещё нет
            if user_id not in group.get("users", []):
                group["users"].append(user_id)
                DataManager.save_spam_groups(groups)
                await callback.answer("✅ Пользователь добавлен!", show_alert=False)
            else:
                await callback.answer("⚠️ Уже в группе!", show_alert=False)

            # 🔁 Обновляем список заново
            await self._refresh_add_user_list(callback, state, real_group_id, page=1)

        except Exception as e:
            print(f"[ERROR confirm_add_user] {e}")
            await callback.answer("Ошибка при добавлении пользователя!", show_alert=True)


    async def process_add_user_input(self, message: types.Message, state: FSMContext):
        """Добавление пользователя в группу после ввода ID"""
        data = await state.get_data()
        group_id = data.get("group_id")
        users_data = DataManager.load_users()

        try:
            user_id = int(message.text.strip())
        except ValueError:
            await message.reply("❌ Введите корректный числовой ID пользователя.")
            return

        user_info = users_data.get(str(user_id))
        if not user_info:
            await message.reply("⚠️ Пользователь с таким ID не найден в users.json")
            await state.clear()
            return

        DataManager.add_user_to_group(group_id, user_id)
        name = user_info.get("fullname", "Без имени")
        username = f"@{user_info.get('username')}" if user_info.get("username") else ""
        await message.reply(f"✅ Пользователь {name} {username} добавлен в группу <b>{group_id}</b>", parse_mode="HTML")
        await state.clear()
    
    async def process_add_user(self, callback: types.CallbackQuery, state: FSMContext):
        """Выбор пользователя для добавления в группу (по 25 пользователей на страницу, устойчив к '_' в ID)"""
        await state.clear()

        # Формат callback_data: adduser|group_id|page
        parts = callback.data.split("|")
        group_id = parts[1] if len(parts) > 1 else None
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
        
        page_size = 25

        if not group_id:
            await callback.answer("Ошибка: не указан ID группы.", show_alert=True)
            return

        users_data = DataManager.load_users()
        groups = DataManager.load_spam_groups()

        group_id = group_id.strip().lower()
        group_keys = {k.strip().lower(): k for k in groups.get("groups", {}).keys()}

        if group_id not in group_keys:
            await callback.message.edit_text("⚠️ Группа не найдена.", parse_mode="HTML")
            await callback.answer()
            return

        group_key_real = group_keys[group_id]
        group = groups["groups"][group_key_real]
        group_users = set(group.get("users", []))

        # Отбираем активных пользователей, которых нет в группе
        available_users = [
            (uid, uinfo)
            for uid, uinfo in users_data.items()
            if uinfo.get("active", False) and int(uid) not in group_users
        ]

        if not available_users:
            await callback.message.edit_text("✅ Нет доступных пользователей для добавления.", parse_mode="HTML")
            await callback.answer()
            return

        total_pages = max(1, (len(available_users) + page_size - 1) // page_size)
        start = (page - 1) * page_size
        end = start + page_size
        current_slice = available_users[start:end]

        # Клавиатура выбора пользователей
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{uinfo.get('name', '')} {uinfo.get('surname', '')} ({uinfo.get('telegram_username', '-')})",
                    callback_data=f"addconfirm|{group_key_real}|{uid}"
                )
            ]
            for uid, uinfo in current_slice
        ])

        # Навигация
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⏪ Назад", callback_data=f"adduser|{group_key_real}|{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="⏩ Далее", callback_data=f"adduser|{group_key_real}|{page+1}"))
        if nav_buttons:
            keyboard.inline_keyboard.append(nav_buttons)

        # Кнопка назад к управлению группой
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"manage|{group_key_real}")
        ])

        await callback.message.edit_text(
            f"👥 Выберите пользователя для добавления в группу <b>{group['name']}</b>\n"
            f"📄 Страница {page}/{total_pages} (всего {len(available_users)} пользователей)",
            parse_mode="HTML",
            reply_markup=keyboard
        )

        await callback.answer()


    async def process_remove_user(self, callback: types.CallbackQuery, state: FSMContext):
        """Удаление пользователя из группы (по 25 пользователей на страницу, устойчив к '_' в ID)"""
        # Формат callback_data: deluser|group_id|page
        parts = callback.data.split("|")
        group_id = parts[1] if len(parts) > 1 else None
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
        page_size = 25

        if not group_id:
            await callback.answer("Ошибка: не указан ID группы.", show_alert=True)
            return

        groups = DataManager.get_available_groups()
        users_data = DataManager.load_users()

        group_id = group_id.strip().lower()
        group_keys = {k.strip().lower(): k for k in groups.keys()}

        if group_id not in group_keys:
            await callback.message.edit_text("⚠️ Группа не найдена.", parse_mode="HTML")
            await callback.answer()
            return

        group_key_real = group_keys[group_id]
        group = groups[group_key_real]
        user_list = group.get("users", [])

        if not user_list:
            await callback.message.edit_text("📭 В группе нет пользователей.", parse_mode="HTML")
            await callback.answer()
            return

        total_pages = max(1, (len(user_list) + page_size - 1) // page_size)
        start = (page - 1) * page_size
        end = start + page_size
        current_slice = user_list[start:end]

        # Клавиатура с пользователями
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{users_data.get(str(uid), {}).get('name', '')} "
                         f"{users_data.get(str(uid), {}).get('surname', '')} "
                         f"({users_data.get(str(uid), {}).get('telegram_username', '-')})",
                    callback_data=f"remove|{group_key_real}|{uid}"
                )
            ]
            for uid in current_slice
        ])

        # Навигация
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⏪ Назад", callback_data=f"deluser|{group_key_real}|{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="⏩ Далее", callback_data=f"deluser|{group_key_real}|{page+1}"))
        if nav_buttons:
            keyboard.inline_keyboard.append(nav_buttons)

        # Кнопка назад к управлению
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"manage|{group_key_real}")
        ])

        await callback.message.edit_text(
            f"🗑️ Выберите пользователя для удаления из группы <b>{group['name']}</b>\n"
            f"📄 Страница {page}/{total_pages} (всего {len(user_list)} пользователей)",
            parse_mode="HTML",
            reply_markup=keyboard
        )

        await callback.answer()


    async def confirm_remove_user(self, callback: types.CallbackQuery, state: FSMContext):
        """Подтверждение удаления пользователя из группы"""
        try:
            parts = callback.data.split("|")
            if len(parts) < 3:
                await callback.answer("Ошибка формата данных!", show_alert=True)
                return

            group_id = parts[1]
            user_id = int(parts[2])

            groups = DataManager.load_spam_groups()
            users = DataManager.load_users()

            # Защита от разных регистров/пробелов
            group_id = group_id.strip().lower()
            group_keys = {k.strip().lower(): k for k in groups.get("groups", {}).keys()}

            if group_id not in group_keys:
                await callback.answer("Группа не найдена!", show_alert=True)
                return

            real_group_id = group_keys[group_id]
            group = groups["groups"][real_group_id]

            if user_id in group.get("users", []):
                group["users"].remove(user_id)
                DataManager.save_spam_groups(groups)

            # Получаем информацию о пользователе
            user_info = users.get(str(user_id))
            username = user_info.get("telegram_username", "-") if user_info else "-"
            name = user_info.get("name", "") if user_info else ""
            surname = user_info.get("surname", "") if user_info else ""

            await callback.message.edit_text(
                f"❌ Пользователь <b>{name} {surname}</b> {username} удалён из группы <b>{group['name']}</b>.",
                parse_mode="HTML"
            )
            await callback.answer()

        except Exception as e:
            print(f"[ERROR confirm_remove_user] {e}")
            await callback.answer("Ошибка при удалении пользователя!", show_alert=True)
        
    
    async def cmd_groups(self, message: types.Message):
        """Показ всех групп"""
        groups = DataManager.get_available_groups()
        if not groups:
            await message.reply("📭 Группы пока не созданы.\nИспользуй /group_create для добавления.")
            return

        text = "📋 <b>Группы рассылок:</b>\n\n"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for key, info in groups.items():
            text += f"<b>{info['name']}</b> (ID: <code>{key}</code>)\n"
            text += f"👥 {len(info.get('users', []))} пользователей\n\n"
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text=f"⚙️ Управлять {info['name']}", callback_data=f"manage_{key}")
            ])

        await message.reply(text, parse_mode="HTML", reply_markup=keyboard)

    async def cmd_group_create(self, message: types.Message, state: FSMContext):
        """Создание новой группы"""
        if message.from_user.id not in AUTHORIZED_USERS:
            await message.reply("⛔ У вас нет доступа к управлению группами.")
            return
        await message.reply("Введите ID группы (латиницей, например: hr_team):")
        await state.set_state(CreateGroup.await_group_key)

    async def process_group_key(self, message: types.Message, state: FSMContext):
        """Обработка ID группы"""
        key = message.text.strip()
        if not key.isascii() or " " in key:
            await message.reply("❌ Используйте только латиницу, без пробелов (например: dev_team)")
            return
        await state.update_data(group_key=key)
        await message.reply("Теперь введите название группы:")
        await state.set_state(CreateGroup.await_group_name)

    async def process_group_name(self, message: types.Message, state: FSMContext):
        """Создание группы после ввода имени"""
        data = await state.get_data()
        key = data.get("group_key")
        name = message.text.strip()

        try:
            DataManager.add_group(key, name)
            await message.reply(f"✅ Группа <b>{name}</b> создана (ID: <code>{key}</code>)", parse_mode="HTML")
        except ValueError as e:
            await message.reply(f"❌ Ошибка: {e}")
        await state.clear()

    async def process_group_manage(self, callback: types.CallbackQuery):
        """Управление пользователями группы"""
        print(f"[DEBUG] manage callback: {callback.data}")
        
        if not callback.data.startswith("manage_"):
            print(f"[DEBUG] if not callback.data.startswith('manage_')")
            return
            
            
        group_id = callback.data.replace("manage_", "")
        groups = DataManager.get_available_groups()
        users_data = DataManager.load_users()

        if group_id not in groups:
            await callback.answer("Группа не найдена!", show_alert=True)
            return

        group = groups[group_id]
        text = f"⚙️ <b>{group['name']}</b>\n\n"

        text += "\nВыберите действие:"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Список пользователей", callback_data=f"listusers|{group_id}|1")],
            [InlineKeyboardButton(text="➕ Добавить пользователя", callback_data=f"adduser|{group_id}|1")],
            [InlineKeyboardButton(text="➖ Удалить пользователя", callback_data=f"deluser|{group_id}|1")],
            [InlineKeyboardButton(text="📋 Импорт из списка", callback_data=f"import|{group_id}")],  # НОВАЯ КНОПКА
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"cancel|{group_id}")]
        ])
                
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    
    
    # ============================================
    # КОМАНДЫ
    # ============================================
    
    async def cmd_start(self, message: types.Message):
        """Команда /start"""
        if message.from_user.id not in AUTHORIZED_USERS:
            await message.reply("⛔ У вас нет доступа к этому боту.")
            return
        
        text = (
            "🤖 <b>Бот управления рассылками</b>\n\n"
            "Доступные команды:\n"
            "/create - Создать новую рассылку\n"
            "/list - Список запланированных рассылок\n"
            "/stats - Статистика рассылок\n"
            "/help - Справка"
        )
        await message.reply(text, parse_mode="HTML")
    
    async def cmd_help(self, message: types.Message):
        """Команда /help — справка по работе с ботом"""
        if message.from_user.id not in AUTHORIZED_USERS:
            return

        groups = DataManager.get_available_groups()

        text = "📖 <b>Справка по боту рассылок</b>\n\n"

        text += "<b>Типы рассылок:</b>\n"
        text += "• Одноразовая — отправляется один раз в указанную дату и время\n"
        text += "• Периодическая — повторяется по расписанию (ежемесячно или через интервал)\n\n"
    
        text += "⚠️ <b>ВАЖНО:</b> При расчёте дат отправки учитываются:\n"
        text += "• Выходные дни (суббота, воскресенье)\n"
        text += "• Праздничные дни РФ\n"
        text += "• Если дата попадает на нерабочий день, отправка переносится на ближайший рабочий день\n\n"

        text += "Команды для управления группами:\n"
        text += "• /groups — показать список всех групп\n"
        text += "• /group_create — создать новую группу\n\n"

        text += "<b>Как создать группу:</b>\n"
        text += "1️⃣ Отправь команду /group_create\n"
        text += "2️⃣ Введи уникальный ID группы (латиницей, например: <code>dev_team</code>)\n"
        text += "3️⃣ Введи отображаемое имя (например: <b>Команда разработчиков</b>)\n"
        text += "4️⃣ После создания — используй ⚙️ Управлять, чтобы добавить пользователей\n\n"

        text += "<b>Импорт списка пользователей:</b>\n"
        text += "<b>📥 Импорт списка</b> позволяет массово добавить пользователей.\n"
        text += "Просто отправь текст с никами в любом формате — бот автоматически найдёт все ники Telegram!\n"
        text += "Формат не важен: можно прислать список через запятую, столбиком, или даже текст с вкраплениями ников.\n\n"

        text += "<b>Добавление / удаление отдельных пользователей:</b>\n"
        text += "После выбора группы ты увидишь список пользователей (из файла <code>users.json</code>).\n"
        text += "Ты можешь добавить или удалить их из группы через кнопки:\n"
        text += "➕ Добавить пользователя\n"
        text += "➖ Удалить пользователя\n\n"

        text += "<b>Использование групп при создании рассылок:</b>\n"
        text += "Когда создаёшь рассылку (/create), ты можешь выбрать одну или несколько групп из списка.\n"
        text += "Сообщение получат только пользователи, входящие в выбранные группы.\n\n"

        text += "<b>Общие команды:</b>\n"
        text += "/create — создать новую рассылку\n"
        text += "/list — список запланированных рассылок\n"
        text += "/stats — статистика рассылок\n"
        text += "/help — эта справка\n"

        await message.reply(text, parse_mode="HTML")
    
    async def cmd_check_workday(self, message: types.Message):
        """
        ОПЦИОНАЛЬНАЯ команда для проверки рабочего дня
        Использование: /check_workday 25.12.2024
        """
        if message.from_user.id not in AUTHORIZED_USERS:
            return
    
        try:
            parts = message.text.split()
            if len(parts) != 2:
                await message.reply("Использование: /check_workday ДД.ММ.ГГГГ\nПример: /check_workday 31.12.2024")
                return
        
            date_str = parts[1]
            check_date = datetime.strptime(date_str, "%d.%m.%Y")
        
            is_work = is_working_day(check_date)
            holiday_name = get_holiday_name(check_date)
            weekday_names = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        
            text = f"📅 <b>Проверка даты:</b> {check_date.strftime('%d.%m.%Y')}\n"
            text += f"<b>День недели:</b> {weekday_names[check_date.weekday()]}\n\n"
        
            if is_work:
                text += "✅ <b>Рабочий день</b>"
            else:
                if holiday_name:
                    text += f"🎉 <b>Праздник:</b> {holiday_name}"
                else:
                    text += "🏖 <b>Выходной день</b>"
        
            if not is_work:
                next_work = get_next_working_day(check_date)
                text += f"\n\n<b>Ближайший рабочий день:</b> {next_work.strftime('%d.%m.%Y')} ({weekday_names[next_work.weekday()]})"
        
            await message.reply(text, parse_mode="HTML")
        except ValueError:
            await message.reply("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")
        except Exception as e:
            await message.reply(f"❌ Ошибка: {e}")

    async def cmd_create(self, message: types.Message, state: FSMContext):
        """Команда /create - начало создания рассылки"""
        if message.from_user.id not in AUTHORIZED_USERS:
            return
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Одноразовая", callback_data="type_once")],
            [InlineKeyboardButton(text="🔄 Периодическая", callback_data="type_periodic")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
        
        await message.reply(
            "Выберите тип рассылки:",
            reply_markup=keyboard
        )
        await state.set_state(CreateBroadcast.select_type)
    
    async def cmd_list(self, message: types.Message):
        """Команда /list - список рассылок С УЧЁТОМ РАБОЧИХ ДНЕЙ"""
        if message.from_user.id not in AUTHORIZED_USERS:
            return
    
        spam_data = DataManager.load_spam_data()
        broadcasts = spam_data.get("broadcasts", [])
    
        if not broadcasts:
            await message.reply("📭 Нет запланированных рассылок")
            return
    
        # Фильтруем активные рассылки
        active_broadcasts = [b for b in broadcasts if b.get("status") != "deleted"]
    
        if not active_broadcasts:
            await message.reply("📭 Нет активных рассылок")
            return
    
        text = "📬 <b>Запланированные рассылки:</b>\n\n"
    
        for bc in active_broadcasts:
            bc_type = "🔄 Периодическая" if bc.get("type") == "periodic" else "📅 Одноразовая"
            bc_id = bc.get("id", "unknown")
            bc_text = bc.get("message_text", "")[:50] + "..." if len(bc.get("message_text", "")) > 50 else bc.get("message_text", "")
            bc_groups = ", ".join(bc.get("groups", []))
        
            # Получаем актуальное количество получателей
            user_count = len(DataManager.get_users_by_groups(bc.get("groups", [])))
        
            text += f"<b>ID:</b> <code>{bc_id}</code>\n"
            text += f"<b>Тип:</b> {bc_type}\n"
            text += f"<b>Текст:</b> {bc_text}\n"
            text += f"<b>Группы:</b> {bc_groups}\n"
            text += f"<b>Получателей:</b> {user_count}\n"
        
            if bc.get("type") == "once":
                scheduled_dt = bc.get('scheduled_datetime', '')
                text += f"<b>Дата отправки:</b> {format_next_send_with_workdays(scheduled_dt)}\n"
            else:
                period_type = bc.get('period_type')
                if period_type == 'monthly':
                    monthly_day = bc.get('monthly_day')
                    text += f"<b>Период:</b> Ежемесячно, {monthly_day} числа\n"
                else:
                    # Обработка периода в секундах
                    period_seconds = bc.get('period_seconds')
                    if period_seconds is None and bc.get('period_hours'):
                        period_seconds = bc.get('period_hours') * 3600
                
                    if period_seconds:
                        if period_seconds < 3600:
                            period_str = f"{period_seconds // 60} мин"
                        elif period_seconds < 86400:
                            period_str = f"{period_seconds // 3600} ч {(period_seconds % 3600) // 60} мин"
                        else:
                            period_str = f"{period_seconds // 86400} дн {(period_seconds % 86400) // 3600} ч"
                        text += f"<b>Период:</b> каждые {period_str} ({period_seconds} сек)\n"
                    else:
                        text += f"<b>Период:</b> не указан\n"
            
                # ИЗМЕНЁННАЯ ЧАСТЬ: Показываем следующую отправку с учётом рабочих дней
                next_send = bc.get('next_send_time', '')
                text += f"<b>Следующая отправка:</b> {format_next_send_with_workdays(next_send)}\n"
        
            text += f"<b>Статус:</b> {bc.get('status')}\n"
            text += f"<b>Отправлено:</b> {bc.get('sent_count', 0)} раз\n"
            text += f"<b>Удалить:</b> /delete_{bc_id}\n"
            text += "─" * 30 + "\n"
    
        await message.reply(text, parse_mode="HTML")

    async def cmd_delete(self, message: types.Message):
        """Команда /delete_ID - удаление рассылки"""
        if message.from_user.id not in AUTHORIZED_USERS:
            return
        
        # Извлекаем ID из команды
        parts = message.text.split("_")
        if len(parts) != 2:
            await message.reply("❌ Неверный формат команды. Используйте /delete_ID")
            return
        
        broadcast_id = parts[1]
        
        spam_data = DataManager.load_spam_data()
        broadcasts = spam_data.get("broadcasts", [])
        
        # Ищем рассылку
        for bc in broadcasts:
            if bc.get("id") == broadcast_id:
                bc["status"] = "deleted"
                DataManager.save_spam_data(spam_data)
                await message.reply(f"✅ Рассылка {broadcast_id} удалена")
                return
        
        await message.reply(f"❌ Рассылка {broadcast_id} не найдена")
    
    async def cmd_stats(self, message: types.Message):
        """Команда /stats - статистика"""
        if message.from_user.id not in AUTHORIZED_USERS:
            return
        
        spam_data = DataManager.load_spam_data()
        stats = spam_data.get("stats", {})
        broadcasts = spam_data.get("broadcasts", [])
        
        active_count = len([b for b in broadcasts if b.get("status") == "scheduled"])
        completed_count = len([b for b in broadcasts if b.get("status") == "completed"])
        
        text = (
            "📊 <b>Статистика рассылок:</b>\n\n"
            f"Всего создано: {stats.get('total_scheduled', 0)}\n"
            f"Всего отправлено: {stats.get('total_sent', 0)}\n"
            f"Активных: {active_count}\n"
            f"Завершенных: {completed_count}\n"
        )
        
        await message.reply(text, parse_mode="HTML")
    
    # ============================================
    # FSM ОБРАБОТЧИКИ
    # ============================================
    
    async def process_broadcast_type(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка выбора типа рассылки"""
        if callback.data == "cancel":
            await callback.message.edit_text("❌ Создание рассылки отменено")
            await state.clear()
            return
        
        broadcast_type = "once" if callback.data == "type_once" else "periodic"
        await state.update_data(broadcast_type=broadcast_type)
        
        # Загружаем актуальные группы
        groups = DataManager.get_available_groups()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        
        # Добавляем кнопки для каждой группы
        for group_key, group_info in groups.items():
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"◻️ {group_info['name']}",
                    callback_data=f"group_{group_key}"
                )
            ])
        
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="✅ Подтвердить выбор", callback_data="confirm_groups")
        ])
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
        ])
        
        await callback.message.edit_text(
            "Выберите группы для рассылки (можно несколько):",
            reply_markup=keyboard
        )
        await state.update_data(selected_groups=[])
        await state.set_state(CreateBroadcast.select_groups)
        await callback.answer()
    
    async def process_group_selection(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка выбора групп"""
        if callback.data == "cancel":
            await callback.message.edit_text("❌ Создание рассылки отменено")
            await state.clear()
            return
        
        data = await state.get_data()
        selected_groups = data.get("selected_groups", [])
        
        if callback.data.startswith("group_"):
            group_key = callback.data.replace("group_", "")
            # Загружаем актуальные группы
            groups = DataManager.get_available_groups()
            
            if group_key in selected_groups:
                selected_groups.remove(group_key)
            else:
                selected_groups.append(group_key)
            
            await state.update_data(selected_groups=selected_groups)
            
            # Обновляем клавиатуру
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            
            for gk, group_info in groups.items():
                icon = "✅" if gk in selected_groups else "◻️"
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(
                        text=f"{icon} {group_info['name']}",
                        callback_data=f"group_{gk}"
                    )
                ])
            
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="✅ Подтвердить выбор", callback_data="confirm_groups")
            ])
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
            ])
            
            await callback.message.edit_reply_markup(reply_markup=keyboard)
            await callback.answer()
        
        elif callback.data == "confirm_groups":
            if not selected_groups:
                await callback.answer("Выберите хотя бы одну группу!", show_alert=True)
                return
            
            # Подсчитываем количество пользователей
            user_ids = DataManager.get_users_by_groups(selected_groups)
            
            await callback.message.edit_text(
                f"Выбрано групп: {len(selected_groups)}\n"
                f"Всего пользователей: {len(user_ids)}\n\n"
                f"Введите текст сообщения для рассылки:"
            )
            await state.set_state(CreateBroadcast.enter_text)
            await callback.answer()
    
    async def process_text_input(self, message: types.Message, state: FSMContext):
        """Обработка ввода текста сообщения"""
        if len(message.text) > 4000:
            await message.reply("❌ Текст слишком длинный (макс. 4000 символов)")
            return
        
        await state.update_data(message_text=message.text)
        
        await message.reply(
            "Введите ссылку (URL) для прикрепления к сообщению\n"
            "или отправьте '-' если ссылка не нужна:"
        )
        await state.set_state(CreateBroadcast.enter_link)
    
    async def process_link_input(self, message: types.Message, state: FSMContext):
        """Обработка ввода ссылки"""
        link = None if message.text == "-" else message.text
        
        if link and not (link.startswith("http://") or link.startswith("https://")):
            await message.reply("❌ Ссылка должна начинаться с http:// или https://")
            return
        
        await state.update_data(link=link)
        
        data = await state.get_data()
        broadcast_type = data.get("broadcast_type")
        
        if broadcast_type == "once":
            # Для одноразовой рассылки - показываем кнопки выбора даты
            await self.show_date_selection(message, state)
        else:
            text = (
                "📅 <b>Укажите периодичность рассылки:</b>\n\n"
                "<b>Ежемесячно в конкретный день:</b>\n"
                "Введите число от 1 до 31 - день месяца\n"
                "Примеры:\n"
                "• 1 - первого числа каждого месяца\n"
                "• 15 - пятнадцатого числа\n"
                "• 31 - последний день месяца\n\n"
                "<b>Повтор через интервал:</b>\n"
                "Введите число больше 31 - период в секундах\n"
                "Примеры:\n"
                "• 60 - каждую минуту\n"
                "• 300 - каждые 5 минут\n"
                "• 3600 - каждый час\n"
                "• 86400 - каждый день"
            )
            await message.reply(text, parse_mode="HTML")
            await state.set_state(CreateBroadcast.enter_period)
    
    async def show_date_selection(self, message: types.Message, state: FSMContext):
        """Пошаговый выбор даты: сначала год"""
        now = datetime.now()
        current_year = now.year
        years = [current_year, current_year + 1, current_year + 2, current_year + 3]

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=str(y), callback_data=f"year_{y}")] for y in years
            ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]]
        )

        await message.reply(
            "📅 <b>Выберите год отправки:</b>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await state.set_state(CreateBroadcast.select_date)

    async def process_date_selection(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка выбора года, месяца, дня"""
        if callback.data == "cancel":
            await callback.message.edit_text("❌ Создание рассылки отменено")
            await state.clear()
            return
    
        data = await state.get_data()
    
        # --- выбор года ---
        if callback.data.startswith("year_"):
            year = int(callback.data.replace("year_", ""))
            await state.update_data(selected_year=year)
    
            months = [
                ("Янв", 1), ("Фев", 2), ("Мар", 3), ("Апр", 4),
                ("Май", 5), ("Июн", 6), ("Июл", 7), ("Авг", 8),
                ("Сен", 9), ("Окт", 10), ("Ноя", 11), ("Дек", 12)
            ]
    
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=name, callback_data=f"month_{num}") for name, num in months[i:i+3]]
                    for i in range(0, 12, 3)
                ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_year"),
                      InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]]
            )
    
            await callback.message.edit_text(
                f"📆 <b>Выбран год:</b> {year}\nТеперь выберите месяц:",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            return
    
        # --- возврат к выбору года ---
        if callback.data == "back_year":
            await self.show_date_selection(callback.message, state)
            return
    
        # --- выбор месяца ---
        if callback.data.startswith("month_"):
            month = int(callback.data.replace("month_", ""))
            data = await state.get_data()
            year = data.get("selected_year")
    
            from calendar import monthrange
            days_in_month = monthrange(year, month)[1]                   
            
            # формируем кнопки дней по 5 в ряд
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=str(day), callback_data=f"day_{day}") for day in range(i, min(i + 5, days_in_month + 1))]
                    for i in range(1, days_in_month + 1, 5)
                ]
            )

            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_month"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
            ])
                            
            await state.update_data(selected_month=month)
            await callback.message.edit_text(
                f"📆 <b>{year}</b>, месяц <b>{month:02d}</b>\nВыберите день:",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            return
    
        # --- возврат к выбору месяца ---
        if callback.data == "back_month":
            year = (await state.get_data()).get("selected_year")
            await state.update_data(selected_year=year)
            # повторно показываем месяцы
            months = [
                ("Янв", 1), ("Фев", 2), ("Мар", 3), ("Апр", 4),
                ("Май", 5), ("Июн", 6), ("Июл", 7), ("Авг", 8),
                ("Сен", 9), ("Окт", 10), ("Ноя", 11), ("Дек", 12)
            ]
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=name, callback_data=f"month_{num}") for name, num in months[i:i+3]]
                    for i in range(0, 12, 3)
                ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_year"),
                      InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]]
            )
            await callback.message.edit_text(
                f"📆 <b>Выбран год:</b> {year}\nТеперь выберите месяц:",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            return
    
        # --- выбор дня ---
        if callback.data.startswith("day_"):
            day = int(callback.data.replace("day_", ""))
            data = await state.get_data()
            year = data.get("selected_year")
            month = data.get("selected_month")
    
            date_str = f"{year}-{month:02d}-{day:02d}"
            await state.update_data(selected_date=date_str)
            await self.show_time_selection(callback, state)
            return
    
    async def show_time_selection(self, callback: types.CallbackQuery, state: FSMContext):
        """Показать кнопки для выбора времени"""
        # Создаем кнопки с популярными вариантами времени
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            # Утренние часы
            [InlineKeyboardButton(text="🌅 09:00", callback_data="time_09:00"),
             InlineKeyboardButton(text="🌅 10:00", callback_data="time_10:00"),
             InlineKeyboardButton(text="🌅 11:00", callback_data="time_11:00")],
            # Дневные часы
            [InlineKeyboardButton(text="☀️ 12:00", callback_data="time_12:00"),
             InlineKeyboardButton(text="☀️ 13:00", callback_data="time_13:00"),
             InlineKeyboardButton(text="☀️ 14:00", callback_data="time_14:00")],
            # Вечерние часы
            [InlineKeyboardButton(text="🌇 15:00", callback_data="time_15:00"),
             InlineKeyboardButton(text="🌇 16:00", callback_data="time_16:00"),
             InlineKeyboardButton(text="🌇 17:00", callback_data="time_17:00")],
            # Поздние часы
            [InlineKeyboardButton(text="🌙 18:00", callback_data="time_18:00"),
             InlineKeyboardButton(text="🌙 19:00", callback_data="time_19:00"),
             InlineKeyboardButton(text="🌙 20:00", callback_data="time_20:00")],
            # Опции
            [InlineKeyboardButton(text="⏰ Другое время", callback_data="time_custom")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
        
        await callback.message.edit_text(
            "⏰ <b>Выберите время отправки:</b>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await state.set_state(CreateBroadcast.select_time)
    
    async def process_time_selection(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка выбора времени"""
        if callback.data == "cancel":
            await callback.message.edit_text("❌ Создание рассылки отменено")
            await state.clear()
            return
        
        if callback.data == "time_custom":
            # Переходим к ручному вводу времени
            data = await state.get_data()
            selected_date = data.get("selected_date")
            
            await callback.message.edit_text(
                f"Выбранная дата: {selected_date}\n\n"
                "Введите время в формате ЧЧ:ММ\n"
                "Пример: 14:30"
            )
            await state.set_state(CreateBroadcast.enter_datetime)
            await callback.answer()
        else:
            # Извлекаем выбранное время
            time_str = callback.data.replace("time_", "")
            data = await state.get_data()
            date_str = data.get("selected_date")
            
            # Формируем полную дату и время
            scheduled_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            
            # Проверяем, что дата не в прошлом
            if scheduled_dt <= datetime.now():
                await callback.answer("❌ Выбранное время уже прошло! Выберите другое.", show_alert=True)
                await self.show_time_selection(callback, state)
                return
            
            await state.update_data(scheduled_datetime=scheduled_dt.isoformat())
            
            # Показываем подтверждение
            await self.show_confirmation_from_callback(callback, state)
            await callback.answer()
    
    async def process_datetime_input(self, message: types.Message, state: FSMContext):
        """Обработка ручного ввода даты и времени"""
        data = await state.get_data()
        selected_date = data.get("selected_date")
        
        try:
            if selected_date and ":" in message.text and "." not in message.text:
                # Это ввод только времени для предварительно выбранной даты
                time_str = message.text.strip()
                scheduled_dt = datetime.strptime(f"{selected_date} {time_str}", "%Y-%m-%d %H:%M")
            else:
                # Это полный ввод даты и времени
                scheduled_dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
            
            if scheduled_dt <= datetime.now():
                await message.reply("❌ Дата должна быть в будущем")
                return
            
            await state.update_data(scheduled_datetime=scheduled_dt.isoformat())
            await self.show_confirmation(message, state)
            
        except ValueError:
            await message.reply(
                "❌ Неверный формат\n"
                "Используйте: ДД.ММ.ГГГГ ЧЧ:ММ или просто ЧЧ:ММ если дата уже выбрана"
            )
    
    async def process_period_input(self, message: types.Message, state: FSMContext):
        """Обработка ввода периода"""
        try:
            period_value = int(message.text.strip())
            
            if period_value < 1:
                await message.reply("❌ Введите положительное число")
                return
            
            if period_value <= 31:
                # Это день месяца для ежемесячной рассылки
                await state.update_data(
                    period_type="monthly",
                    monthly_day=period_value
                )
                
                # Рассчитываем следующую дату отправки
                from calendar import monthrange
                now = datetime.now()
                year = now.year
                month = now.month
                
                # Определяем день для текущего месяца
                max_day = monthrange(year, month)[1]
                day = min(period_value, max_day)
                
                # Если день уже прошел в этом месяце, переходим на следующий
                if day < now.day or (day == now.day and now.hour >= 10):
                    month += 1
                    if month > 12:
                        month = 1
                        year += 1
                    max_day = monthrange(year, month)[1]
                    day = min(period_value, max_day)
                
                next_send_time = datetime(year, month, day, 10, 0)  # В 10:00
                await state.update_data(next_send_time=next_send_time.isoformat())
                
            else:
                # Это период в секундах
                if period_value > 2592000:  # Больше 30 дней
                    await message.reply("❌ Максимальный период - 2592000 секунд (30 дней)")
                    return
                
                await state.update_data(
                    period_type="interval",
                    period_seconds=period_value
                )
                
                # Рассчитываем время следующей отправки
                next_send_time = datetime.now() + timedelta(seconds=period_value)
                await state.update_data(next_send_time=next_send_time.isoformat())
            
            await self.show_confirmation(message, state)
            
        except ValueError:
            await message.reply("❌ Введите число")
    
    async def show_confirmation(self, message: types.Message, state: FSMContext):
        """Показ подтверждения создания рассылки"""
        data = await state.get_data()
        
        # Загружаем актуальные данные о группах
        groups = DataManager.get_available_groups()
        
        group_names = [groups[g]['name'] for g in data.get("selected_groups", []) if g in groups]
        user_count = len(DataManager.get_users_by_groups(data.get("selected_groups", [])))
        
        message_text = data.get('message_text', '')[:100]
        group_names_str = ', '.join(group_names)
        
        text = "📋 <b>Подтверждение рассылки:</b>\n\n"
        text += f"<b>Тип:</b> {'Одноразовая' if data.get('broadcast_type') == 'once' else 'Периодическая'}\n"
        text += f"<b>Группы:</b> {group_names_str}\n"
        text += f"<b>Получателей:</b> {user_count}\n"
        text += f"<b>Текст:</b> {message_text}...\n"
        
        if data.get("link"):
            text += f"<b>Ссылка:</b> {data.get('link')}\n"
        
        if data.get("broadcast_type") == "once":
            text += f"<b>Дата отправки:</b> {data.get('scheduled_datetime', '')}\n"
        else:
            period_type = data.get('period_type')
            if period_type == 'monthly':
                monthly_day = data.get('monthly_day')
                text += f"<b>Период:</b> Ежемесячно, {monthly_day} числа\n"
            else:
                period_seconds = data.get('period_seconds')
                # Форматируем период для удобного отображения
                if period_seconds < 3600:
                    period_str = f"{period_seconds // 60} мин"
                elif period_seconds < 86400:
                    period_str = f"{period_seconds // 3600} ч {(period_seconds % 3600) // 60} мин"
                else:
                    period_str = f"{period_seconds // 86400} дн {(period_seconds % 86400) // 3600} ч"
                
                text += f"<b>Период:</b> каждые {period_str} ({period_seconds} сек)\n"
            
            text += f"<b>Первая отправка:</b> {data.get('next_send_time', '')}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать рассылку", callback_data="confirm_create")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_create")]
        ])
        
        await message.reply(text, parse_mode="HTML", reply_markup=keyboard)
        await state.set_state(CreateBroadcast.confirm)
    
    async def show_confirmation_from_callback(self, callback: types.CallbackQuery, state: FSMContext):
        """Показ подтверждения создания рассылки из callback"""
        data = await state.get_data()
        
        # Загружаем актуальные данные о группах
        groups = DataManager.get_available_groups()
        
        group_names = [groups[g]['name'] for g in data.get("selected_groups", []) if g in groups]
        user_count = len(DataManager.get_users_by_groups(data.get("selected_groups", [])))
        
        message_text = data.get('message_text', '')[:100]
        group_names_str = ', '.join(group_names)
        
        text = "📋 <b>Подтверждение рассылки:</b>\n\n"
        text += f"<b>Тип:</b> {'Одноразовая' if data.get('broadcast_type') == 'once' else 'Периодическая'}\n"
        text += f"<b>Группы:</b> {group_names_str}\n"
        text += f"<b>Получателей:</b> {user_count}\n"
        text += f"<b>Текст:</b> {message_text}...\n"
        
        if data.get("link"):
            text += f"<b>Ссылка:</b> {data.get('link')}\n"
        
        if data.get("broadcast_type") == "once":
            text += f"<b>Дата отправки:</b> {data.get('scheduled_datetime', '')}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать рассылку", callback_data="confirm_create")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_create")]
        ])
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await state.set_state(CreateBroadcast.confirm)
    
    async def process_confirmation(self, callback: types.CallbackQuery, state: FSMContext):
        """Обработка подтверждения создания"""
        if callback.data == "cancel_create":
            await callback.message.edit_text("❌ Создание рассылки отменено")
            await state.clear()
            return
        
        data = await state.get_data()
        
        # Формируем данные рассылки (БЕЗ target_user_ids)
        broadcast_data = {
            "type": data.get("broadcast_type"),
            "groups": data.get("selected_groups"),  # Сохраняем только имена групп
            "message_text": data.get("message_text"),
            "link": data.get("link"),
            "created_by": callback.from_user.id
            # НЕ сохраняем target_user_ids!
        }
        
        if data.get("broadcast_type") == "once":
            broadcast_data["scheduled_datetime"] = data.get("scheduled_datetime")
        else:
            period_type = data.get('period_type')
            broadcast_data["period_type"] = period_type
            broadcast_data["next_send_time"] = data.get("next_send_time")
            
            if period_type == 'monthly':
                broadcast_data["monthly_day"] = data.get("monthly_day")
            else:
                broadcast_data["period_seconds"] = data.get("period_seconds")
        
        # Сохраняем рассылку
        broadcast_id = DataManager.add_broadcast(broadcast_data)
        
        await callback.message.edit_text(
            f"✅ Рассылка создана!\n"
            f"ID: <code>{broadcast_id}</code>\n\n"
            f"Используйте /list для просмотра всех рассылок",
            parse_mode="HTML"
        )
        
        await state.clear()
        await callback.answer()
    
    async def run(self):
        """Запуск бота"""
        logger.info("Запуск бота управления рассылками...")
        
        if not SPAM_BOT_TOKEN or SPAM_BOT_TOKEN == "YOUR_SPAM_BOT_TOKEN_HERE":
            logger.error("Не указан токен бота! Установите SPAM_BOT_TOKEN")
            return
        
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Ошибка при запуске бота: {e}")
        finally:
            await self.bot.session.close()

# ============================================
# ТОЧКА ВХОДА
# ============================================

def main():
    """Главная функция"""
    bot = SpamManagerBot()
    asyncio.run(bot.run())

if __name__ == "__main__":
    main()