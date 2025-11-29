import os
import json
import asyncio
import random

from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import concurrent.futures

from PIL import Image, ImageDraw, ImageFont
import tempfile
import traceback

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest
from telegram.error import TimedOut, NetworkError, RetryAfter

from google import genai
from google.genai import types

# ========== Настройки ==========

TELEGRAM_TOKEN = "7...0"
GEMINI_API_KEY = "A...g"

USERS_FILE = "sputnkik_bot_users/users.json"
IMAGES_BASE_DIR = "nano_user_images"
USAGE_FILE = "nano_user_usage.json"
DAILY_LIMIT = 20

TELEGRAM_CONNECT_TIMEOUT = 60.0
TELEGRAM_READ_TIMEOUT = 120.0
TELEGRAM_WRITE_TIMEOUT = 120.0
TELEGRAM_POOL_TIMEOUT = 60.0
GEMINI_GENERATION_TIMEOUT = 600

SEED_MIN = 1
SEED_MAX = 2147483647
# ===============================================

def log_console(tag: str, message: str, data: Optional[dict] = None):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{timestamp}] ===== {tag} =====")
    print(message)
    if data:
        for k, v in data.items():
            print(f"  {k}: {v}")
    print("=" * 50 + "\n")

DEFAULT_SETTINGS = {
    "temperature": 1.0,
    "aspect_ratio": "16:9",
    "image_size": "1K",
    "seed": -1
}

class AIRequestLogger:
    LOG_FILE = "nano_ai_requests_log.jsonl"

    @staticmethod
    def log(data: Dict):
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(AIRequestLogger.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as e:
            print("Failed to write AIRequestLogger:", e)

class UserManager:
    def __init__(self, users_file: str):
        self.users_file = users_file
        self.users = self._load_users_once()

    def _load_users_once(self) -> Dict:
        try:
            with open(self.users_file, 'r', encoding='utf-8') as f:
                users_data = json.load(f)
                log_console(
                    "USERS_LOADED", 
                    f"Loaded {len(users_data)} users from {self.users_file}",
                    {"users": list(users_data.keys())}
                )
                return users_data
        except FileNotFoundError:
            log_console("USERS_FILE_NOT_FOUND", f"File {self.users_file} not found")
            return {}
        except Exception as e:
            log_console("USERS_LOAD_ERROR", f"Error loading users file", {"error": str(e)})
            return {}

    def is_authorized(self, telegram_id: int) -> bool:
        return str(telegram_id) in self.users

    def get_user(self, telegram_id: int) -> Optional[Dict]:
        return self.users.get(str(telegram_id))

class UsageTracker:
    def __init__(self, usage_file: str, daily_limit: int):
        self.usage_file = usage_file
        self.daily_limit = daily_limit
        self.usage_data = self.load_usage()

    def load_usage(self) -> Dict:
        try:
            with open(self.usage_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_usage(self):
        with open(self.usage_file, 'w', encoding='utf-8') as f:
            json.dump(self.usage_data, f, indent=2, ensure_ascii=False)

    def get_today_date(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def get_usage_count(self, telegram_id: int) -> int:
        user_id = str(telegram_id)
        today = self.get_today_date()
        if user_id not in self.usage_data:
            return 0
        user_usage = self.usage_data[user_id]
        if user_usage.get('date') != today:
            return 0
        return user_usage.get('count', 0)

    def can_generate(self, telegram_id: int) -> bool:
        return self.get_usage_count(telegram_id) < self.daily_limit

    def get_remaining(self, telegram_id: int) -> int:
        return max(0, self.daily_limit - self.get_usage_count(telegram_id))

    def increment_usage(self, telegram_id: int):
        user_id = str(telegram_id)
        today = self.get_today_date()
        if user_id not in self.usage_data:
            self.usage_data[user_id] = {'date': today, 'count': 0}
        user_usage = self.usage_data[user_id]
        if user_usage.get('date') != today:
            user_usage['date'] = today
            user_usage['count'] = 0
        user_usage['count'] += 1
        self.save_usage()

    def reset_usage(self, telegram_id: int):
        user_id = str(telegram_id)
        if user_id in self.usage_data:
            del self.usage_data[user_id]
            self.save_usage()

class ImageStorage:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

    def get_user_dir(self, telegram_id: int) -> Path:
        user_dir = self.base_dir / str(telegram_id)
        user_dir.mkdir(exist_ok=True)
        return user_dir

    def save_image(self, telegram_id: int, image_data: bytes, prefix: str = "generated") -> Path:
        user_dir = self.get_user_dir(telegram_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.png"
        filepath = user_dir / filename
        with open(filepath, 'wb') as f:
            f.write(image_data)
        return filepath

    def get_recent_images(self, telegram_id: int, limit: int = 20) -> List[Path]:
        user_dir = self.get_user_dir(telegram_id)
        images = sorted(user_dir.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True)
        return images[:limit]


class GeminiImageGenerator:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "gemini-3-pro-image-preview"
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    
    def _sync_generate(
        self,
        prompt: str,
        reference_images: List[bytes],
        temperature: float,
        aspect_ratio: str,
        image_size: str,
        seed: int
    ) -> Tuple[Optional[bytes], Optional[str], int]:
        try:
            client = genai.Client(api_key=self.api_key)
            
            parts = []
            for img_data in reference_images:
                parts.append(types.Part.from_bytes(mime_type="image/png", data=img_data))
            parts.append(types.Part.from_text(text=prompt))
            
            contents = [types.Content(role="user", parts=parts)]
            
            config = types.GenerateContentConfig(
                temperature=temperature,
                response_modalities=["IMAGE", "TEXT"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                    image_size=image_size,
                ),
                tools=[types.Tool(google_search=types.GoogleSearch())],
                seed=seed,
            )
            
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
            
            if not response.candidates:
                return None, "NO_CANDIDATES", seed
            
            candidate = response.candidates[0]
            finish_reason = str(getattr(candidate, 'finish_reason', ''))
            
            if "SAFETY" in finish_reason:
                return None, "SAFETY", seed
            if "NO_IMAGE" in finish_reason:
                return None, "NO_IMAGE", seed
            
            if not candidate.content or not candidate.content.parts:
                return None, f"NO_CONTENT: {finish_reason}", seed
            
            for part in candidate.content.parts:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data, None, seed
                if hasattr(part, 'text') and part.text:
                    return None, f"MODEL_RETURNED_TEXT: {part.text[:300]}", seed
            
            return None, "NO_IMAGE_DATA", seed
            
        except ValueError as e:
            if "Chunk too big" in str(e):
                return None, "CHUNK_TOO_BIG", seed
            return None, f"ERROR: {str(e)}", seed
        except Exception as e:
            return None, f"ERROR: {str(e)}", seed
    
    async def generate_image(
        self,
        prompt: str,
        reference_images: List[bytes],
        temperature: float = 1.0,
        aspect_ratio: str = "16:9",
        image_size: str = "1K",
        seed: int = -1
    ) -> Tuple[Optional[bytes], Optional[str], int]:
        if seed <= 0:
            seed = random.randint(SEED_MIN, SEED_MAX)
        
        log_console("GEMINI_REQUEST", "Starting generation", {
            "prompt_preview": prompt[:150],
            "num_refs": len(reference_images),
            "image_size": image_size,
            "seed": seed,
        })
        
        loop = asyncio.get_event_loop()
        
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    self._sync_generate,
                    prompt,
                    reference_images,
                    temperature,
                    aspect_ratio,
                    image_size,
                    seed
                ),
                timeout=GEMINI_GENERATION_TIMEOUT
            )
            
            image_data, error, used_seed = result
            if image_data:
                log_console("GEMINI_SUCCESS", "Image generated", {
                    "size_kb": len(image_data) // 1024,
                    "seed": used_seed
                })
            else:
                log_console("GEMINI_FAILED", "Generation failed", {"error": error, "seed": used_seed})
            
            return result
            
        except asyncio.TimeoutError:
            log_console("GEMINI_TIMEOUT", "Generation timeout", {"seed": seed})
            return None, "TIMEOUT", seed


# Глобальные объекты
user_manager = UserManager(USERS_FILE)
image_storage = ImageStorage(IMAGES_BASE_DIR)
gemini_generator = GeminiImageGenerator(GEMINI_API_KEY)
usage_tracker = UsageTracker(USAGE_FILE, DAILY_LIMIT)

user_settings: Dict[int, Dict] = {}
user_selected_images: Dict[int, List[Path]] = {}


def create_numbered_preview_jpg(img_path: Path, number: int, max_size=(600, 600)) -> str:
    img = Image.open(img_path).convert("RGB")
    img.thumbnail(max_size, Image.LANCZOS)
    draw = ImageDraw.Draw(img)
    w, h = img.size
    radius = int(min(w, h) * 0.08)
    circle_x = radius + 20
    circle_y = radius + 20
    draw.ellipse((circle_x - radius, circle_y - radius, circle_x + radius, circle_y + radius), fill=(0, 0, 0))
    font_size = int(radius * 1.4)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    text = str(number)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((circle_x - tw / 2, circle_y - th / 2), text, fill=(255, 255, 255), font=font)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    img.save(temp_file.name, "JPEG", quality=85)
    return temp_file.name


def get_user_settings(telegram_id: int) -> Dict:
    if telegram_id not in user_settings:
        user_settings[telegram_id] = DEFAULT_SETTINGS.copy()
    return user_settings[telegram_id]


def format_settings_text(settings: Dict, used_seed: Optional[int] = None) -> str:
    temp_emoji = "🔥" if settings['temperature'] > 0.7 else "❄️" if settings['temperature'] < 0.4 else "🌡"
    
    if used_seed is not None:
        seed_text = str(used_seed)
    else:
        seed_value = settings.get('seed', -1)
        seed_text = "авто" if seed_value <= 0 else str(seed_value)
    
    return (
        f"⚙️ Параметры:\n"
        f"  {temp_emoji} Температура: {settings['temperature']}\n"
        f"  📐 Соотношение: {settings['aspect_ratio']}\n"
        f"  📏 Размер: {settings['image_size']}\n"
        f"  🎲 Seed: {seed_text}"
    )


async def safe_send_text(bot, chat_id: int, text: str, retries: int = 5):
    for attempt in range(retries):
        try:
            return await bot.send_message(chat_id=chat_id, text=text)
        except TimedOut:
            wait_time = min(2 ** attempt, 30)
            await asyncio.sleep(wait_time)
        except NetworkError:
            wait_time = min(2 ** attempt, 30)
            await asyncio.sleep(wait_time)
        except RetryAfter as e:
            wait = e.retry_after if hasattr(e, "retry_after") else 5
            await asyncio.sleep(wait)
        except Exception as e:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2)
    raise RuntimeError(f"Failed to send text after {retries} retries")


async def safe_send_photo(bot, chat_id: int, photo_path: Path, caption: Optional[str] = None, retries: int = 5):
    for attempt in range(retries):
        try:
            with open(photo_path, "rb") as f:
                return await bot.send_photo(chat_id=chat_id, photo=f, caption=caption)
        except TimedOut:
            wait_time = min(2 ** attempt, 30)
            await asyncio.sleep(wait_time)
        except NetworkError:
            wait_time = min(2 ** attempt, 30)
            await asyncio.sleep(wait_time)
        except RetryAfter as e:
            wait = e.retry_after if hasattr(e, "retry_after") else 5
            await asyncio.sleep(wait)
        except Exception as e:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2)
    raise RuntimeError(f"Failed to send photo after {retries} retries")


async def safe_send_document(bot, chat_id: int, document_path: Path, caption: Optional[str] = None, retries: int = 5):
    for attempt in range(retries):
        try:
            with open(document_path, "rb") as f:
                return await bot.send_document(
                    chat_id=chat_id, 
                    document=f, 
                    caption=caption,
                    filename=document_path.name
                )
        except TimedOut:
            wait_time = min(2 ** attempt, 30)
            await asyncio.sleep(wait_time)
        except NetworkError:
            wait_time = min(2 ** attempt, 30)
            await asyncio.sleep(wait_time)
        except RetryAfter as e:
            wait = e.retry_after if hasattr(e, "retry_after") else 5
            await asyncio.sleep(wait)
        except Exception as e:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2)
    raise RuntimeError(f"Failed to send document after {retries} retries")


async def safe_send_media_group(bot, chat_id: int, media_group: List, retries: int = 5):
    for attempt in range(retries):
        try:
            return await bot.send_media_group(chat_id=chat_id, media=media_group)
        except TimedOut:
            wait_time = min(2 ** attempt, 30)
            await asyncio.sleep(wait_time)
        except NetworkError:
            wait_time = min(2 ** attempt, 30)
            await asyncio.sleep(wait_time)
        except RetryAfter as e:
            wait = e.retry_after if hasattr(e, "retry_after") else 5
            await asyncio.sleep(wait)
        except Exception as e:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2)
    raise RuntimeError(f"Failed to send media group after {retries} retries")


# -------- Handlers --------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен. Вы не авторизованы для использования этого бота.")
        return
    user = user_manager.get_user(telegram_id)
    remaining = usage_tracker.get_remaining(telegram_id)
    await update.message.reply_text(
        f"👋 Привет, {user.get('name', 'пользователь')}!\n\n"
        f"📊 Доступно генераций сегодня: {remaining}/{DAILY_LIMIT}\n\n"
        f"/generate - начать генерацию\n"
        f"/settings - настройки\n"
        f"/usage - лимиты\n"
        f"/help - помощь"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔧 Как использовать:\n"
        "Этот бот позволяет генерировать изображения с помощью модели Gemini 3 Pro Image (Nano Banana Pro)\n\n"
        "⏱ Генерация может занять до 5 минут - это нормально для сложных изображений!\n\n"
        "Загрузи свои изображения для использования в качестве референсов, а затем используй команду /generate для создания новых изображений на основе текстового промпта и выбранных референсов.\n\n"
        "1. /generate - начать\n"
        "2. Выберите референсы или пропустите\n"
        "3. Введите промпт\n"
        "4. Подождите (до 5 мин)\n"
        "5. Получите результат\n\n"
        "🎲 Seed: используйте /settings чтобы задать фиксированный seed для воспроизводимых результатов.\n"
        "Используйте /settings для настройки параметров генерации.\n"
        "Используйте /usage для проверки оставшихся лимитов.\n"
        "Удачи и творческих успехов! 🎨"
    )


async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return
    used = usage_tracker.get_usage_count(telegram_id)
    remaining = usage_tracker.get_remaining(telegram_id)
    bar_length = 10
    filled = int((used / DAILY_LIMIT) * bar_length) if DAILY_LIMIT else 0
    bar = "█" * filled + "░" * (bar_length - filled)
    await update.message.reply_text(
        f"📊 Использовано: {used}/{DAILY_LIMIT}\n"
        f"Осталось: {remaining}\n"
        f"[{bar}]"
    )


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return
    settings = get_user_settings(telegram_id)
    seed_value = settings.get('seed', -1)
    seed_text = "авто (случайный)" if seed_value <= 0 else str(seed_value)
    
    keyboard = [
        [InlineKeyboardButton("🌡 Температура", callback_data="set_temperature")],
        [InlineKeyboardButton("📐 Соотношение сторон", callback_data="set_aspect_ratio")],
        [InlineKeyboardButton("📏 Размер", callback_data="set_image_size")],
        [InlineKeyboardButton("🎲 Seed", callback_data="set_seed")],
    ]
    await update.message.reply_text(
        f"⚙️ Текущие настройки:\n\n"
        f"🌡 Температура: {settings['temperature']}\n"
        f"📐 Соотношение: {settings['aspect_ratio']}\n"
        f"📏 Размер: {settings['image_size']}\n"
        f"🎲 Seed: {seed_text}\n\n"
        f"💡 Seed из результата можно скопировать и установить здесь для повтора.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    data = query.data
    
    if telegram_id not in user_settings:
        user_settings[telegram_id] = DEFAULT_SETTINGS.copy()
    
    if data == "set_temperature":
        keyboard = [
            [InlineKeyboardButton("0.0", callback_data="temp_0.0"),
             InlineKeyboardButton("0.3", callback_data="temp_0.3"),
             InlineKeyboardButton("0.5", callback_data="temp_0.5")],
            [InlineKeyboardButton("0.7", callback_data="temp_0.7"),
             InlineKeyboardButton("0.85", callback_data="temp_0.85"),
             InlineKeyboardButton("1.0", callback_data="temp_1.0")],
        ]
        await query.edit_message_text("Выберите температуру:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("temp_"):
        temp = float(data.split("_")[1])
        user_settings[telegram_id]["temperature"] = temp
        await query.edit_message_text(f"✅ Температура: {temp}")
    
    elif data == "set_aspect_ratio":
        keyboard = [
            [InlineKeyboardButton("1:1", callback_data="ratio_1:1"),
             InlineKeyboardButton("3:2", callback_data="ratio_3:2"),
             InlineKeyboardButton("2:3", callback_data="ratio_2:3")],
            [InlineKeyboardButton("4:3", callback_data="ratio_4:3"),
             InlineKeyboardButton("3:4", callback_data="ratio_3:4")],
            [InlineKeyboardButton("5:4", callback_data="ratio_5:4"),
             InlineKeyboardButton("4:5", callback_data="ratio_4:5")],
            [InlineKeyboardButton("16:9", callback_data="ratio_16:9"),
             InlineKeyboardButton("9:16", callback_data="ratio_9:16")],
            [InlineKeyboardButton("21:9", callback_data="ratio_21:9")],
        ]
        await query.edit_message_text("Выберите соотношение:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("ratio_"):
        ratio = data.split("_", 1)[1]
        user_settings[telegram_id]["aspect_ratio"] = ratio
        await query.edit_message_text(f"✅ Соотношение: {ratio}")
    
    elif data == "set_image_size":
        keyboard = [
            [InlineKeyboardButton("1K", callback_data="size_1K"),
             InlineKeyboardButton("2K", callback_data="size_2K"),
             InlineKeyboardButton("4K", callback_data="size_4K")],
        ]
        await query.edit_message_text("Выберите размер:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("size_"):
        size = data.split("_", 1)[1]
        user_settings[telegram_id]["image_size"] = size
        await query.edit_message_text(f"✅ Размер: {size}")
    
    elif data == "set_seed":
        current_seed = user_settings[telegram_id].get("seed", -1)
        keyboard = [
            [InlineKeyboardButton("🎲 Случайный (-1)", callback_data="seed_1")],
            [InlineKeyboardButton("42", callback_data="seed_42"),
             InlineKeyboardButton("128", callback_data="seed_128"),
             InlineKeyboardButton("777", callback_data="seed_777")],
            [InlineKeyboardButton("1024", callback_data="seed_1024"),
             InlineKeyboardButton("2048", callback_data="seed_2048"),
             InlineKeyboardButton("12345", callback_data="seed_12345")],
            [InlineKeyboardButton("✏️ Ввести вручную", callback_data="seed_custom")],
        ]
        current_text = "авто" if current_seed <= 0 else str(current_seed)
        await query.edit_message_text(
            "🎲 Выберите seed:\n\n"
            "• Случайный (-1) - каждый раз разный результат\n"
            "• Фиксированный - воспроизводимый результат\n\n"
            f"💡 Скопируйте seed из результата генерации.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("seed_"):
        seed_str = data.split("_", 1)[1]
        if seed_str == "custom":
            context.user_data['awaiting_seed'] = True
            await query.edit_message_text(
                "✏️ Введите seed (целое число):\n\n"
                "• Положительное число - фиксированный seed\n"
                "Или введите -1 для случайного seed"
            )
        else:
            seed = int(seed_str)
            if seed == 1:
                seed = -1  # случайный            
            user_settings[telegram_id]["seed"] = seed
            seed_text = "случайный" if seed <= 0 else str(seed)
            await query.edit_message_text(f"✅ Seed: {seed_text}")


async def generate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return

    if not usage_tracker.can_generate(telegram_id):
        await update.message.reply_text("❌ Вы достигли дневного лимита!")
        return

    remaining = usage_tracker.get_remaining(telegram_id)
    settings = get_user_settings(telegram_id)
    
    await update.message.reply_text(
        f"🎨 Генерация. Осталось: {remaining}/{DAILY_LIMIT}\n\n"
        f"{format_settings_text(settings)}"
    )

    recent_images = image_storage.get_recent_images(telegram_id, limit=20)
    user_selected_images[telegram_id] = []

    if not recent_images:
        await update.message.reply_text(
            "У вас нет сохранённых изображений.\n"
            "Введите текстовый промпт:"
        )
        context.user_data['awaiting_prompt'] = True
        return

    # Отправляем превью изображений
    batch = recent_images[:min(10, len(recent_images))]
    media_group = []
    preview_files = []
    
    for idx, img in enumerate(batch):
        preview_path = create_numbered_preview_jpg(img, idx + 1)
        preview_files.append(preview_path)
        f = open(preview_path, "rb")
        media_group.append(InputMediaPhoto(media=f))
    
    try:
        await safe_send_media_group(context.bot, chat_id, media_group)
    except Exception as e:
        log_console("MEDIA_GROUP_ERROR", "Failed to send media group", {"error": str(e)})
        await update.message.reply_text("⚠️ Не удалось отправить превью изображений")
    finally:
        # Закрываем файлы
        for media in media_group:
            try:
                media.media.close()
            except:
                pass
        # Удаляем временные файлы
        for path in preview_files:
            try:
                os.unlink(path)
            except:
                pass
    
    # Кнопки выбора
    keyboard = []
    row = []
    for idx in range(len(batch)):
        row.append(InlineKeyboardButton(f"📷 {idx+1}", callback_data=f"select_img_{idx}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="images_done")])
    keyboard.append([InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_images")])
    
    await update.message.reply_text(
        "Выберите референсные изображения (нажмите на номер):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    context.user_data['recent_images'] = recent_images
    context.user_data['awaiting_prompt'] = False


async def image_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id

    if query.data.startswith("select_img_"):
        img_idx = int(query.data.split("_")[2])
        recent_images = context.user_data.get('recent_images', [])
        
        if img_idx < len(recent_images):
            selected_img = recent_images[img_idx]
            if telegram_id not in user_selected_images:
                user_selected_images[telegram_id] = []
            
            if selected_img in user_selected_images[telegram_id]:
                user_selected_images[telegram_id].remove(selected_img)
                await query.answer("❌ Убрано")
            else:
                user_selected_images[telegram_id].append(selected_img)
                await query.answer("✅ Добавлено")

        selected_count = len(user_selected_images.get(telegram_id, []))
        
        # Обновляем кнопки
        keyboard = []
        row = []
        for idx, img in enumerate(recent_images[:10]):
            is_selected = img in user_selected_images.get(telegram_id, [])
            button_text = f"✓ {idx+1}" if is_selected else f"📷 {idx+1}"
            row.append(InlineKeyboardButton(button_text, callback_data=f"select_img_{idx}"))
            if len(row) == 5:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="images_done")])
        keyboard.append([InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_images")])
        
        try:
            await query.edit_message_text(
                f"Выбрано: {selected_count}\nНажмите на номер чтобы выбрать/убрать:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception:
            pass

    elif query.data in ("images_done", "skip_images"):
        selected_count = len(user_selected_images.get(telegram_id, []))
        await query.edit_message_text(
            f"Выбрано изображений: {selected_count}\n\n"
            f"Введите текстовый промпт:"
        )
        context.user_data['awaiting_prompt'] = True


async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return
    try:
        file = None
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
        elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith("image/"):
            file = await update.message.document.get_file()
        else:
            await update.message.reply_text("Это не изображение.")
            return
        
        photo_bytes = await file.download_as_bytearray()
        saved_path = image_storage.save_image(telegram_id, bytes(photo_bytes), prefix="uploaded")
        log_console("PHOTO_SAVED", f"Saved for user {telegram_id}", {
            "path": str(saved_path), 
            "size_kb": len(photo_bytes)//1024
        })
        await update.message.reply_text(f"✅ Изображение сохранено: {saved_path.name}")
    except Exception as e:
        log_console("PHOTO_ERROR", "Error saving photo", {"error": str(e)})
        await update.message.reply_text("❌ Ошибка при сохранении.")


async def _background_generate_and_send(
    bot, 
    chat_id: int, 
    telegram_id: int, 
    prompt: str, 
    reference_images_paths: List[Path], 
    settings: Dict
):
    generation_start_time = datetime.now()
    
    try:
        settings_text = format_settings_text(settings)
        
        try:
            await safe_send_text(
                bot, 
                chat_id, 
                f"🔄 Генерирую изображение...\n\n"
                f"{settings_text}\n\n"
                f"⏱ Это может занять 1-5 минут"
            )
        except Exception as e:
            log_console("START_MSG_ERROR", "Failed to send start message", {"error": str(e)})
        
        # Загружаем референсы
        reference_images_data = []
        for p in reference_images_paths:
            try:
                with open(p, "rb") as f:
                    img_data = f.read()
                    reference_images_data.append(img_data)
            except Exception as e:
                log_console("REF_READ_ERROR", f"Failed to read {p}", {"error": str(e)})

        seed_setting = settings.get("seed", -1)
        
        AIRequestLogger.log({
            "event": "request_start",
            "user_id": telegram_id,
            "prompt": prompt,
            "num_reference_images": len(reference_images_data),
            "settings": settings,
        })

        # Генерация
        generated_bytes, error_reason, used_seed = await gemini_generator.generate_image(
            prompt=prompt,
            reference_images=reference_images_data,
            temperature=settings.get("temperature", 1.0),
            aspect_ratio=settings.get("aspect_ratio", "16:9"),
            image_size=settings.get("image_size", "1K"),
            seed=seed_setting,
        )

        generation_duration = (datetime.now() - generation_start_time).total_seconds()
        
        AIRequestLogger.log({
            "event": "request_end",
            "user_id": telegram_id,
            "prompt": prompt,
            "success": generated_bytes is not None,
            "error": error_reason,
            "used_seed": used_seed,
            "duration_seconds": generation_duration,
        })

        # Обработка ошибок
        if error_reason or not generated_bytes:
            log_console("GENERATION_FAILED", "Failed", {
                "error": error_reason,
                "seed": used_seed,
                "duration": round(generation_duration, 1),
            })
            
            error_messages = {
                "NO_IMAGE": (
                    f"❌ Модель не смогла создать изображение.\n\n"
                    f"💡 Советы:\n"
                    f"• Опишите конкретное изображение\n"
                    f"• Используйте английский язык\n"
                    f"• Добавьте детали: стиль, цвета\n\n"
                    f"🎲 Seed: {used_seed}\n"
                    f"⏱ Время: {int(generation_duration)}s"
                ),
                "SAFETY": (
                    f"❌ Промпт заблокирован фильтрами.\n\n"
                    f"🎲 Seed: {used_seed}"
                ),
                "TIMEOUT": (
                    f"❌ Превышено время ожидания.\n\n"
                    f"💡 Упростите промпт или уменьшите размер.\n\n"
                    f"🎲 Seed: {used_seed}"
                ),
                "NO_CANDIDATES": f"❌ API не вернул результатов.\n\n🎲 Seed: {used_seed}",
                "NO_IMAGE_DATA": f"❌ Ответ без изображения.\n\n🎲 Seed: {used_seed}",
                "CHUNK_TOO_BIG": f"❌ Изображение слишком большое. Уменьшите размер в /settings\n\n🎲 Seed: {used_seed}",
            }
            
            if error_reason and error_reason.startswith("MODEL_RETURNED_TEXT:"):
                model_text = error_reason.replace("MODEL_RETURNED_TEXT:", "").strip()
                error_msg = (
                    f"❌ Модель ответила текстом:\n\n"
                    f"{model_text[:400]}{'...' if len(model_text) > 400 else ''}\n\n"
                    f"🎲 Seed: {used_seed}"
                )
            elif error_reason and error_reason.startswith("ERROR:"):
                error_detail = error_reason.replace("ERROR:", "").strip()
                error_msg = f"❌ Ошибка: {error_detail[:200]}\n\n🎲 Seed: {used_seed}"
            else:
                error_msg = error_messages.get(error_reason, f"❌ Ошибка: {error_reason}\n\n🎲 Seed: {used_seed}")
            
            try:
                await safe_send_text(bot, chat_id, error_msg)
            except Exception:
                pass
            
            return

        # Успех
        log_console("GENERATION_SUCCESS", "Success", {
            "seed": used_seed,
            "size_kb": len(generated_bytes) // 1024,
            "duration": round(generation_duration, 1),
        })

        saved_path = image_storage.save_image(telegram_id, generated_bytes, prefix="generated")
        
        usage_tracker.increment_usage(telegram_id)
        remaining = usage_tracker.get_remaining(telegram_id)

        caption = (
            f"✅ Готово!\n\n"
            f"📝 Промпт: {prompt[:100]}{'...' if len(prompt) > 100 else ''}\n"
            f"🖼 Референсов: {len(reference_images_data)}\n"
            f"⏱ Время: {int(generation_duration)}s\n"
            f"📊 Осталось: {remaining}/{DAILY_LIMIT}\n\n"
            f"{format_settings_text(settings, used_seed=used_seed)}\n\n"
            f"💡 Для повтора установите seed {used_seed} в /settings"
        )

        try:
            await safe_send_photo(bot, chat_id, saved_path, caption=caption)
        except Exception as e:
            log_console("SEND_PHOTO_FAILED", "Failed", {"error": str(e)})
            try:
                await safe_send_text(bot, chat_id, f"✅ Готово!\n\n🎲 Seed: {used_seed}\n\nОтправляю файл...")
            except:
                pass
        
        try:
            await safe_send_document(
                bot, 
                chat_id, 
                saved_path, 
                caption=f"📎 Оригинал ({len(generated_bytes) // 1024} KB) | Seed: {used_seed}"
            )
        except Exception as e:
            log_console("SEND_DOC_FAILED", "Failed", {"error": str(e)})

    except Exception as e:
        generation_duration = (datetime.now() - generation_start_time).total_seconds()
        log_console("BG_GENERATE_CRITICAL", "Critical error", {
            "error": str(e), 
            "trace": traceback.format_exc(),
        })
        try:
            await safe_send_text(bot, chat_id, f"❌ Критическая ошибка. Попробуйте позже.")
        except:
            pass


async def process_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Ввод seed
    if context.user_data.get('awaiting_seed', False):
        try:
            seed = int(update.message.text.strip())
            if telegram_id not in user_settings:
                user_settings[telegram_id] = DEFAULT_SETTINGS.copy()
            user_settings[telegram_id]["seed"] = seed
            seed_text = "авто (случайный)" if seed <= 0 else str(seed)
            await update.message.reply_text(f"✅ Seed: {seed_text}")
        except ValueError:
            await update.message.reply_text("❌ Введите целое число (например: 1234567890 или -1 для авто)")
        context.user_data['awaiting_seed'] = False
        return
    
    if not context.user_data.get('awaiting_prompt', False):
        return

    prompt = update.message.text
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return

    if not usage_tracker.can_generate(telegram_id):
        await update.message.reply_text("❌ Лимит исчерпан!")
        context.user_data['awaiting_prompt'] = False
        if telegram_id in user_selected_images:
            del user_selected_images[telegram_id]
        return

    await update.message.reply_text(
        "⏳ Принял промпт, запускаю генерацию.\n"
        "⏱ Может занять до 5 минут."
    )
    
    log_console("PROMPT_RECEIVED", f"User {telegram_id}", {
        "prompt": prompt[:200],
    })

    selected_images = user_selected_images.get(telegram_id, [])
    settings = get_user_settings(telegram_id)

    AIRequestLogger.log({
        "event": "request_queued",
        "user_id": telegram_id,
        "prompt": prompt,
        "num_reference_images": len(selected_images),
        "settings": settings,
    })

    asyncio.create_task(
        _background_generate_and_send(
            context.bot, chat_id, telegram_id, prompt, 
            list(selected_images), settings
        )
    )

    if telegram_id in user_selected_images:
        del user_selected_images[telegram_id]
    context.user_data['awaiting_prompt'] = False
    if 'recent_images' in context.user_data:
        del context.user_data['recent_images']


async def reset_user_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = user_manager.get_user(telegram_id)
    if not user or not user.get('admin', False):
        await update.message.reply_text("❌ Нет прав.")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Использование: /reset_usage <telegram_id>")
        return
    try:
        target_user_id = int(context.args[0])
        usage_tracker.reset_usage(target_user_id)
        await update.message.reply_text(f"✅ Лимиты {target_user_id} сброшены.")
    except ValueError:
        await update.message.reply_text("Неверный ID.")


async def global_error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
    error_msg = str(context.error)
    
    if "terminated by other getUpdates" in error_msg:
        log_console("BOT_CONFLICT", "Запущено несколько копий бота!")
        return
    
    log_console("GLOBAL_ERROR", "Exception", {
        "error": error_msg, 
        "trace": traceback.format_exc()
    })
    
    try:
        if update and update.effective_chat:
            await safe_send_text(context.bot, update.effective_chat.id, "⚠️ Ошибка.")
    except:
        pass


def main():
    request = HTTPXRequest(
        connect_timeout=TELEGRAM_CONNECT_TIMEOUT,
        read_timeout=TELEGRAM_READ_TIMEOUT,
        write_timeout=TELEGRAM_WRITE_TIMEOUT,
        pool_timeout=TELEGRAM_POOL_TIMEOUT,
    )

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .request(request)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_menu))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("reset_usage", reset_user_usage))
    application.add_handler(CommandHandler("generate", generate_start))

    application.add_handler(
        CallbackQueryHandler(settings_callback, pattern="^(set_|temp_|ratio_|size_|seed_)")
    )
    application.add_handler(
        CallbackQueryHandler(image_selection_callback, pattern="^(select_img_|images_done|skip_images)")
    )

    application.add_handler(MessageHandler(filters.PHOTO, process_photo))
    application.add_handler(MessageHandler(filters.Document.IMAGE, process_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text_message))

    application.add_error_handler(global_error_handler)

    print("=" * 60)
    print("🤖 Gemini Image Generator Bot")
    print("=" * 60)
    print(f"📊 Лимит: {DAILY_LIMIT}/день")
    print(f"👥 Пользователей: {len(user_manager.users)}")
    print(f"⏱ Таймаут: {GEMINI_GENERATION_TIMEOUT}s")
    print(f"🎲 Seed: {SEED_MIN} - {SEED_MAX}")
    print("=" * 60)

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()