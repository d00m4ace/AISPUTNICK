# code/spam_executor.py
"""
Модуль выполнения рассылок для основного бота
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
import holidays

from utils.markdown_utils import escape_markdown_v2

logger = logging.getLogger(__name__)

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

def get_next_working_day(date: datetime, keep_time: bool = True) -> datetime:
    """
    Возвращает следующий рабочий день.
    Если keep_time=True, сохраняет время из исходной даты.
    """
    original_time = date.time() if keep_time else datetime.min.time()
    current = date
    
    # Ищем следующий рабочий день
    while not is_working_day(current):
        current += timedelta(days=1)
    
    # Восстанавливаем время, если нужно
    if keep_time:
        current = datetime.combine(current.date(), original_time)
    
    return current

def get_previous_working_day(date: datetime, keep_time: bool = True) -> datetime:
    """
    Возвращает предыдущий рабочий день.
    Если keep_time=True, сохраняет время из исходной даты.
    """
    original_time = date.time() if keep_time else datetime.min.time()
    current = date - timedelta(days=1)
    
    # Ищем предыдущий рабочий день
    while not is_working_day(current):
        current -= timedelta(days=1)
    
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
    
    # Пробуем перенести вперёд
    forward_date = get_next_working_day(date, keep_time)
    
    # Если остались в том же месяце - отлично
    if forward_date.month == original_month and forward_date.year == original_year:
        return forward_date
    
    # Иначе ищем назад
    backward_date = get_previous_working_day(date, keep_time)
    
    # Проверяем, что нашли в том же месяце
    if backward_date.month == original_month and backward_date.year == original_year:
        return backward_date
    
    # Критическая ситуация: в месяце вообще нет рабочих дней
    # Такое практически невозможно, но на всякий случай возвращаем forward_date
    logger.warning(
        f"⚠️ КРИТИЧНО: В месяце {original_month}/{original_year} "
        f"не найдено рабочих дней вокруг {date.strftime('%d.%m.%Y')}! "
        f"Перенос на {forward_date.strftime('%d.%m.%Y')}"
    )
    return forward_date

def get_holiday_name(date: datetime) -> Optional[str]:
    """Возвращает название праздника, если дата является праздником"""
    ru_holidays = holidays.Russia(years=date.year)
    return ru_holidays.get(date.date())

def format_next_send_with_workdays(next_send_str: str) -> str:
    """
    Форматирует дату следующей отправки с учётом рабочих дней.
    Если дата попадает на выходной/праздник, возвращает ближайший рабочий день.
    """
    try:
        next_send = datetime.fromisoformat(next_send_str)
        
        # Если это не рабочий день, находим следующий рабочий
        if not is_working_day(next_send):
            working_day = get_working_day_in_same_month(next_send)
            
            # Определяем причину переноса
            holiday_name = get_holiday_name(next_send)
            if holiday_name:
                reason = f"праздник: {holiday_name}"
            else:
                weekday_names = {5: "суббота", 6: "воскресенье"}
                reason = weekday_names.get(next_send.weekday(), "выходной")
            
            # Определяем направление переноса
            direction = "➡️" if working_day > next_send else "⬅️"
            
            return (
                f"<s>{next_send.strftime('%d.%m.%Y %H:%M')}</s> "
                f"{direction} <b>{working_day.strftime('%d.%m.%Y %H:%M')}</b> "
                f"<i>({reason})</i>"
            )
        
        return next_send.strftime('%d.%m.%Y %H:%M')
    except:
        return next_send_str


class SpamExecutor:
    """Исполнитель рассылок для основного бота"""
    
    def __init__(self, bot: Bot, user_manager):
        self.bot = bot
        self.user_manager = user_manager
        self.spam_file = os.path.join("sputnkik_bot_users", "spam.json")
        self.users_file = os.path.join("sputnkik_bot_users", "users.json")
        self.groups_file = os.path.join("sputnkik_bot_users", "spam_group.json")
        self.spam_log_file = "spam_execution.log"
        self.check_interval = 60  # Проверка каждые 60 секунд
        self.is_running = False
        self._task = None

        # Настройка логирования рассылок
        self.spam_logger = logging.getLogger('spam_executor')
        handler = logging.FileHandler(self.spam_log_file, encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.spam_logger.addHandler(handler)
        self.spam_logger.setLevel(logging.INFO)

    # ============================================================
    # ОСНОВНОЙ ЦИКЛ
    # ============================================================

    async def start(self):
        """Запуск проверки рассылок"""
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("SpamExecutor запущен")

    async def stop(self):
        """Остановка проверки рассылок"""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SpamExecutor остановлен")

    async def _check_loop(self):
        """Периодическая проверка"""
        while self.is_running:
            try:
                await self._check_and_execute_broadcasts()
            except Exception as e:
                logger.error(f"Ошибка в цикле проверки рассылок: {e}", exc_info=True)
            await asyncio.sleep(self.check_interval)

    # ============================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================

    def _load_spam_data(self) -> Dict:
        """Загрузка данных о рассылках"""
        if not os.path.exists(self.spam_file):
            return {"broadcasts": [], "stats": {"total_sent": 0, "total_scheduled": 0}}
        try:
            with open(self.spam_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки spam.json: {e}")
            return {"broadcasts": [], "stats": {"total_sent": 0, "total_scheduled": 0}}

    def _save_spam_data(self, data: Dict):
        """Сохранение spam.json"""
        try:
            with open(self.spam_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения spam.json: {e}")

    def _load_users(self) -> Dict:
        """Загрузка users.json"""
        try:
            with open(self.users_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки users.json: {e}")
            return {}

    def _load_groups(self) -> Dict:
        """Загрузка групп из spam_group.json"""
        try:
            with open(self.groups_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки spam_group.json: {e}")
            return {"groups": {}}

    def _get_users_by_groups(self, group_names: List[str]) -> List[int]:
        """Получение списка активных пользователей из выбранных групп"""
        groups_data = self._load_groups()
        users_data = self._load_users()
        all_user_ids: Set[int] = set()

        for group_name in group_names:
            group = groups_data.get("groups", {}).get(group_name)
            if not group:
                continue

            for uid in group.get("users", []):
                user_info = users_data.get(str(uid))
                if user_info and user_info.get("active", False):
                    all_user_ids.add(uid)

        return list(all_user_ids)

    # ============================================================
    # ПРОВЕРКА И ВЫПОЛНЕНИЕ РАССЫЛОК
    # ============================================================

    async def _check_and_execute_broadcasts(self):
        """Основная логика проверки и запуска рассылок С УЧЁТОМ РАБОЧИХ ДНЕЙ"""
        spam_data = self._load_spam_data()
        broadcasts = spam_data.get("broadcasts", [])
        current_time = datetime.now()
        spam_data["last_check"] = current_time.isoformat()

        # Счётчик для периодических рассылок
        periodic_broadcast_index = 0

        for broadcast in broadcasts:
            if broadcast.get("status") in ["deleted", "completed"]:
                continue

            # Определяем индекс для периодических рассылок
            if broadcast.get("type") == "periodic":
                hour_offset = periodic_broadcast_index
                periodic_broadcast_index += 1
            else:
                hour_offset = 0

            try:
                if broadcast.get("type") == "once":
                    # --- ОДНОРАЗОВАЯ РАССЫЛКА ---
                    scheduled_time = datetime.fromisoformat(broadcast.get("scheduled_datetime"))
            
                    if current_time >= scheduled_time and broadcast.get("status") == "scheduled":
                        # Проверяем, не попадает ли на нерабочий день
                        if not is_working_day(scheduled_time):
                            # Переносим на рабочий день в том же месяце
                            working_day = get_working_day_in_same_month(scheduled_time)
                            holiday_name = get_holiday_name(scheduled_time)
                            reason = f"праздник: {holiday_name}" if holiday_name else "выходной"
                        
                            direction = "вперёд" if working_day > scheduled_time else "назад"
                    
                            self.spam_logger.info(
                                f"⚠️ Рассылка {broadcast.get('id')}: дата {scheduled_time.strftime('%d.%m.%Y')} "
                                f"({reason}) перенесена {direction} на {working_day.strftime('%d.%m.%Y %H:%M')} "
                                f"(остаёмся в месяце {scheduled_time.strftime('%B %Y')})"
                            )
                    
                            # Обновляем время отправки
                            broadcast["scheduled_datetime"] = working_day.isoformat()
                            self._save_spam_data(spam_data)
                    
                            # Если новое время ещё не наступило, пропускаем
                            if current_time < working_day:
                                continue
                
                        # Выполняем рассылку
                        await self._execute_broadcast(broadcast, spam_data)
                        broadcast["status"] = "completed"
                        broadcast["completed_at"] = current_time.isoformat()

                elif broadcast.get("type") == "periodic":
                    # --- ПЕРИОДИЧЕСКАЯ РАССЫЛКА ---
                    next_send_str = broadcast.get("next_send_time")
                    if not next_send_str:
                        logger.warning(f"Рассылка {broadcast.get('id')} не имеет next_send_time")
                        continue
            
                    next_send_time = datetime.fromisoformat(next_send_str)
            
                    # Если время отправки ещё не наступило, пропускаем
                    if current_time < next_send_time:
                        continue
            
                    # Проверяем, не попадает ли на нерабочий день
                    if not is_working_day(next_send_time):
                        # Переносим на рабочий день в том же месяце
                        working_day = get_working_day_in_same_month(next_send_time)
                        holiday_name = get_holiday_name(next_send_time)
                        reason = f"праздник: {holiday_name}" if holiday_name else "выходной"
                    
                        direction = "вперёд" if working_day > next_send_time else "назад"
                
                        self.spam_logger.info(
                            f"⚠️ Рассылка {broadcast.get('id')}: дата {next_send_time.strftime('%d.%m.%Y')} "
                            f"({reason}) перенесена {direction} на {working_day.strftime('%d.%m.%Y %H:%M')} "
                            f"(остаёмся в месяце {next_send_time.strftime('%B %Y')})"
                        )
                
                        # Обновляем время отправки
                        broadcast["next_send_time"] = working_day.isoformat()
                        self._save_spam_data(spam_data)
                
                        # Если новое время ещё не наступило, пропускаем
                        if current_time < working_day:
                            continue
            
                    # Выполняем рассылку
                    await self._execute_broadcast(broadcast, spam_data)

                    # --- РАСЧЁТ СЛЕДУЮЩЕГО ВРЕМЕНИ ОТПРАВКИ ---
                    period_type = broadcast.get("period_type")

                    if period_type == "monthly":
                        # === ЕЖЕМЕСЯЧНАЯ РАССЫЛКА ===
                        from calendar import monthrange

                        monthly_day = broadcast.get("monthly_day", 1)
                
                        # Вычисляем следующий месяц
                        year = current_time.year
                        month = current_time.month + 1
                        if month > 12:
                            month = 1
                            year += 1

                        # Корректируем день месяца (если в месяце нет такого дня)
                        max_day = monthrange(year, month)[1]
                        day = min(monthly_day, max_day)
                
                        # Создаём дату следующей отправки с учетом индекса (10:00 + N часов)
                        base_hour = 10 + hour_offset
                        next_date = datetime(year, month, day, base_hour, 0, 0)

                        # ВАЖНО: Если дата попадает на нерабочий день, переносим в пределах месяца
                        if not is_working_day(next_date):
                            original_date = next_date.strftime('%d.%m.%Y')
                            next_date = get_working_day_in_same_month(next_date)
                    
                            holiday_name = get_holiday_name(datetime(year, month, day))
                            reason = f"праздник: {holiday_name}" if holiday_name else "выходной"
                        
                            direction = "вперёд" if next_date.day > day else "назад"
                    
                            logger.info(
                                f"📆 Рассылка {broadcast.get('id')}: дата {original_date} ({reason}) "
                                f"автоматически перенесена {direction} на {next_date.strftime('%d.%m.%Y')} "
                                f"(рабочий день в том же месяце)"
                            )

                        broadcast["next_send_time"] = next_date.isoformat()

                    else:
                        # === ИНТЕРВАЛЬНАЯ РАССЫЛКА ===
                        period_seconds = broadcast.get("period_seconds")
                        if period_seconds is None and broadcast.get("period_hours"):
                            period_seconds = broadcast.get("period_hours") * 3600
                        if not period_seconds:
                            period_seconds = 86400  # 24 часа по умолчанию

                        next_time = current_time + timedelta(seconds=period_seconds)
                
                        # Для интервальных рассылок тоже учитываем рабочие дни
                        if not is_working_day(next_time):
                            original_date = next_time.strftime('%d.%m.%Y %H:%M')
                            original_month = next_time.month
                            next_time = get_working_day_in_same_month(next_time)
                        
                            direction = "вперёд" if next_time > datetime.fromisoformat(original_date.replace('.', '-')) else "назад"
                    
                            logger.info(
                                f"📆 Рассылка {broadcast.get('id')}: время {original_date} "
                                f"перенесено {direction} на {next_time.strftime('%d.%m.%Y %H:%M')} "
                                f"(рабочий день в том же месяце)"
                            )
                
                        broadcast["next_send_time"] = next_time.isoformat()

                    broadcast["last_sent"] = current_time.isoformat()

            except Exception as e:
                logger.error(f"Ошибка обработки рассылки {broadcast.get('id')}: {e}", exc_info=True)
                self.spam_logger.error(f"Ошибка рассылки {broadcast.get('id')}: {e}")

        self._save_spam_data(spam_data)

    # ============================================================
    # ВЫПОЛНЕНИЕ ОТПРАВКИ
    # ============================================================

    async def _execute_broadcast(self, broadcast: Dict, spam_data: Dict):
        """Отправка сообщений всем активным пользователям из выбранных групп"""
        broadcast_id = broadcast.get("id", "unknown")
        execution_time = datetime.now()
    
        # Проверка на рабочий день
        if not is_working_day(execution_time):
            holiday_name = get_holiday_name(execution_time)
            day_info = f"праздник: {holiday_name}" if holiday_name else "выходной день"
            self.spam_logger.warning(
                f"⚠️ ВНИМАНИЕ: Рассылка {broadcast_id} выполняется в нерабочий день "
                f"({execution_time.strftime('%d.%m.%Y')} - {day_info})"
            )
    
        self.spam_logger.info(f"🚀 Начало рассылки {broadcast_id} в {execution_time.strftime('%d.%m.%Y %H:%M:%S')}")

        groups = broadcast.get("groups", [])
        if not groups:
            self.spam_logger.warning(f"❌ Рассылка {broadcast_id} не имеет групп")
            return

        target_users = self._get_users_by_groups(groups)
        if not target_users:
            self.spam_logger.warning(f"❌ Нет активных получателей для рассылки {broadcast_id}")
            return

        users_data = self._load_users()
        message_text = broadcast.get("message_text", "")
        link = broadcast.get("link")

        # Формируем текст
        final_text = f"{escape_markdown_v2(message_text)}\n\n🔗 {escape_markdown_v2(link)}" if link else message_text
        final_text += f"\n\n_Рассылка \\#{escape_markdown_v2(broadcast_id)}_"

        successful = 0
        failed = 0
        blocked = 0

        self.spam_logger.info(f"📤 Отправка {len(target_users)} получателям из групп: {', '.join(groups)}")

        for uid in target_users:
            user_info = users_data.get(str(uid))
            if not user_info or not user_info.get("active", False):
                continue

            try:
                await self.bot.send_message(uid, final_text, parse_mode="MarkdownV2", disable_web_page_preview=False)
                successful += 1
                await asyncio.sleep(3)  # Задержка для избежания ограничений Telegram
            
            except TelegramForbiddenError:
                failed += 1
                blocked += 1
                user_name = user_info.get("name", "Неизвестно")
                self.spam_logger.warning(f"🚫 Пользователь {uid} ({user_name}) заблокировал бота")
                await self.user_manager.set_inactive(str(uid))
            
            except TelegramBadRequest as e:
                failed += 1
                self.spam_logger.error(f"❌ Ошибка отправки {uid}: {e}")
            
            except Exception as e:
                failed += 1
                logger.error(f"❌ Неожиданная ошибка при отправке пользователю {uid}: {e}")

        # Обновляем статистику
        broadcast["sent_count"] = broadcast.get("sent_count", 0) + 1
        broadcast["last_execution"] = {
            "timestamp": execution_time.isoformat(),
            "successful": successful,
            "failed": failed,
            "blocked": blocked,
            "groups": groups,
            "total_recipients": len(target_users)
        }

        spam_data["stats"]["total_sent"] = spam_data["stats"].get("total_sent", 0) + successful
        self._save_spam_data(spam_data)

        # Итоговое логирование
        self.spam_logger.info(
            f"✅ Рассылка {broadcast_id} завершена: "
            f"Успешно={successful}, Ошибок={failed}, Заблокировали={blocked}, "
            f"Получателей={len(target_users)}"
        )
    
        # Если много заблокировавших, выводим предупреждение
        if blocked > len(target_users) * 0.1:  # Более 10% заблокировали
            self.spam_logger.warning(
                f"⚠️ Высокий процент блокировок в рассылке {broadcast_id}: "
                f"{blocked}/{len(target_users)} ({blocked*100//len(target_users)}%)"
            )

    async def force_check(self):
        """Принудительная проверка"""
        await self._check_and_execute_broadcasts()
        return "Проверка рассылок выполнена"

    # ============================================================
    # РАСПИСАНИЕ РАССЫЛОК
    # ============================================================

    def get_broadcasts_schedule(self, months: int = 2) -> str:
        """
        Получение расписания рассылок на указанное количество месяцев вперёд
    
        Args:
            months: количество месяцев для прогноза (по умолчанию 2)
    
        Returns:
            Форматированное расписание рассылок
        """
        from calendar import monthrange
    
        spam_data = self._load_spam_data()
        broadcasts = spam_data.get("broadcasts", [])
        current_time = datetime.now()
        end_date = current_time + timedelta(days=30 * months)
    
        schedule = []
    
        # Счётчик для периодических рассылок
        periodic_broadcast_index = 0
    
        for broadcast in broadcasts:
            if broadcast.get("status") in ["deleted"]:
                continue
        
            # Определяем индекс для периодических рассылок
            if broadcast.get("type") == "periodic":
                hour_offset = periodic_broadcast_index
                periodic_broadcast_index += 1
            else:
                hour_offset = 0
            
            broadcast_id = broadcast.get("id", "unknown")
            message_preview = broadcast.get("message_text", "")[:50]
            groups = ", ".join(broadcast.get("groups", []))
        
            if broadcast.get("type") == "once":
                # Одноразовая рассылка
                scheduled_time = datetime.fromisoformat(broadcast.get("scheduled_datetime"))
            
                if broadcast.get("status") == "completed":
                    continue  # Пропускаем уже выполненные
            
                if scheduled_time > end_date:
                    continue  # За пределами периода
            
                # Проверяем, не попадает ли на нерабочий день
                if not is_working_day(scheduled_time):
                    working_day = get_working_day_in_same_month(scheduled_time)
                    holiday_name = get_holiday_name(scheduled_time)
                    reason = f"{holiday_name}" if holiday_name else "выходной"
                
                    direction = "➡️" if working_day > scheduled_time else "⬅️"
                
                    schedule.append({
                        "date": working_day,
                        "id": broadcast_id,
                        "type": "once",
                        "message": message_preview,
                        "groups": groups,
                        "note": f"{direction} Перенос с {scheduled_time.strftime('%d.%m')} ({reason})"
                    })
                else:
                    schedule.append({
                        "date": scheduled_time,
                        "id": broadcast_id,
                        "type": "once",
                        "message": message_preview,
                        "groups": groups,
                        "note": ""
                    })
        
            elif broadcast.get("type") == "periodic":
                # Периодическая рассылка
                period_type = broadcast.get("period_type")
                next_send_str = broadcast.get("next_send_time")
            
                if not next_send_str:
                    continue
            
                next_send_time = datetime.fromisoformat(next_send_str)
            
                if period_type == "monthly":
                    # Ежемесячная рассылка
                    monthly_day = broadcast.get("monthly_day", 1)
                
                    # Генерируем даты на все месяцы периода
                    temp_date = next_send_time if next_send_time >= current_time else current_time
                
                    while temp_date <= end_date:
                        year = temp_date.year
                        month = temp_date.month
                    
                        # Корректируем день месяца
                        max_day = monthrange(year, month)[1]
                        day = min(monthly_day, max_day)
                    
                        # Используем базовый час + смещение для каждой рассылки
                        base_hour = 10 + hour_offset
                        send_date = datetime(year, month, day, base_hour, 0, 0)
                    
                        if send_date >= current_time and send_date <= end_date:
                            # Проверяем рабочий день
                            if not is_working_day(send_date):
                                working_day = get_working_day_in_same_month(send_date)
                                holiday_name = get_holiday_name(send_date)
                                reason = f"{holiday_name}" if holiday_name else "выходной"
                            
                                direction = "➡️" if working_day > send_date else "⬅️"
                            
                                schedule.append({
                                    "date": working_day,
                                    "id": broadcast_id,
                                    "type": "monthly",
                                    "message": message_preview,
                                    "groups": groups,
                                    "note": f"{direction} Перенос с {send_date.strftime('%d.%m')} ({reason})"
                                })
                            else:
                                schedule.append({
                                    "date": send_date,
                                    "id": broadcast_id,
                                    "type": "monthly",
                                    "message": message_preview,
                                    "groups": groups,
                                    "note": ""
                                })
                    
                        # Переходим к следующему месяцу
                        month += 1
                        if month > 12:
                            month = 1
                            year += 1
                        temp_date = datetime(year, month, 1)
            
                else:
                    # Интервальная рассылка
                    period_seconds = broadcast.get("period_seconds")
                    if period_seconds is None and broadcast.get("period_hours"):
                        period_seconds = broadcast.get("period_hours") * 3600
                    if not period_seconds:
                        period_seconds = 86400
                
                    temp_date = next_send_time if next_send_time >= current_time else current_time
                
                    while temp_date <= end_date:
                        if temp_date >= current_time:
                            # Проверяем рабочий день
                            if not is_working_day(temp_date):
                                working_day = get_working_day_in_same_month(temp_date)
                                holiday_name = get_holiday_name(temp_date)
                                reason = f"{holiday_name}" if holiday_name else "выходной"
                            
                                direction = "➡️" if working_day > temp_date else "⬅️"
                            
                                schedule.append({
                                    "date": working_day,
                                    "id": broadcast_id,
                                    "type": f"every {period_seconds//3600}h",
                                    "message": message_preview,
                                    "groups": groups,
                                    "note": f"{direction} Перенос с {temp_date.strftime('%d.%m %H:%M')} ({reason})"
                                })
                            else:
                                schedule.append({
                                    "date": temp_date,
                                    "id": broadcast_id,
                                    "type": f"every {period_seconds//3600}h",
                                    "message": message_preview,
                                    "groups": groups,
                                    "note": ""
                                })
                    
                        temp_date += timedelta(seconds=period_seconds)
    
        # Сортируем по дате
        schedule.sort(key=lambda x: x["date"])
    
        # Форматируем вывод
        if not schedule:
            return "📭 Нет запланированных рассылок на ближайшие 2 месяца"
    
        result = f"📅 **Расписание рассылок на {months} месяца**\n"
        result += f"(с {current_time.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')})\n\n"
    
        current_month = None
    
        for item in schedule:
            # Группировка по месяцам
            month_name = item["date"].strftime("%B %Y")
            if month_name != current_month:
                result += f"\n━━━ {month_name.upper()} ━━━\n\n"
                current_month = month_name
        
            # Формируем строку с информацией о рассылке
            date_str = item["date"].strftime("%d.%m (%a) %H:%M")
            result += f"🕐 **{date_str}** - ID:{item['id']} [{item['type']}]\n"
            result += f"   📝 {item['message']}...\n"
            result += f"   👥 Группы: {item['groups']}\n"
        
            if item["note"]:
                result += f"   ⚠️ {item['note']}\n"
        
            result += "\n"
    
        result += f"\n📊 Всего запланировано: {len(schedule)} рассылок"
    
        return result