import os
import json
import asyncio
import random
import uuid
import re

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
GEMINI_API_KEY = "A...M" 

USERS_FILE = "sputnkik_bot_users/users.json"
IMAGES_BASE_DIR = "nano_user_images"
USAGE_FILE = "nano_user_usage.json"
DAILY_LIMIT = 20

DAILY_LIMIT_PREMIUM = 50
PREMIUM_USERS = ['123456789','1234567890','12345678901']

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
    def __init__(self, usage_file: str, daily_limit: int, premium_limit: int, premium_users: List[str]):
        self.usage_file = usage_file
        self.daily_limit = daily_limit
        self.premium_limit = premium_limit
        self.premium_users = premium_users
        self.usage_data = self.load_usage()

    def get_user_limit(self, telegram_id: int) -> int:
        return self.premium_limit if str(telegram_id) in self.premium_users else self.daily_limit    

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
        user_limit = self.get_user_limit(telegram_id)
        return self.get_usage_count(telegram_id) < user_limit

    def get_remaining(self, telegram_id: int) -> int:
        user_limit = self.get_user_limit(telegram_id)
        return max(0, user_limit - self.get_usage_count(telegram_id))

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
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
    
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
            "prompt_preview": prompt[:3500],
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
usage_tracker = UsageTracker(USAGE_FILE, DAILY_LIMIT, DAILY_LIMIT_PREMIUM, PREMIUM_USERS)

user_settings: Dict[int, Dict] = {}
user_sessions: Dict[int, Dict] = {}

def get_user_settings(telegram_id: int) -> Dict:
    if telegram_id not in user_settings:
        user_settings[telegram_id] = DEFAULT_SETTINGS.copy()
    return user_settings[telegram_id]

def get_user_session(telegram_id: int) -> Dict:
    """Получает или создает сессию пользователя с промптом и референсами"""
    if telegram_id not in user_sessions:
        user_sessions[telegram_id] = {
            "prompt": "",
            "refs": [],
            "awaiting": None
        }
    return user_sessions[telegram_id]

def generate_config_id() -> str:
    """Генерирует уникальный ID для конфигурации"""
    return str(uuid.uuid4()).replace('-', '_')[:16]

def save_generation_config(telegram_id: int, config_id: str, prompt: str, settings: Dict, refs: List[Path]):
    """Сохраняет конфигурацию генерации в JSON файл пользователя"""
    user_dir = image_storage.get_user_dir(telegram_id)
    config_path = user_dir / f"set_{config_id}.json"
    
    rel_refs = []
    for ref in refs:
        try:
            rel_path = str(ref.relative_to(user_dir))
            rel_refs.append(rel_path)
        except ValueError:
            rel_refs.append(str(ref))
    
    config_data = {
        "id": config_id,
        "timestamp": datetime.now().isoformat(),
        "prompt": prompt,
        "settings": settings.copy(),
        "references": rel_refs
    }
    
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)
    
    log_console("CONFIG_SAVED", f"Saved config {config_id}", {"path": str(config_path)})

def load_generation_config(telegram_id: int, config_id: str) -> Optional[Dict]:
    """Загружает конфигурацию по ID"""
    user_dir = image_storage.get_user_dir(telegram_id)
    config_path = user_dir / f"set_{config_id}.json"
    
    if not config_path.exists():
        return None
    
    with open(config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    valid_refs = []
    for ref_path in data.get("references", []):
        full_path = user_dir / ref_path
        if full_path.exists():
            valid_refs.append(full_path)
    
    data["references"] = valid_refs
    return data

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

def get_main_menu_keyboard():
    """Возвращает клавиатуру главного меню с кликабельными командами"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Промпт", callback_data="cmd_prompt"),
            InlineKeyboardButton("🖼 Референсы", callback_data="cmd_refs")
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data="cmd_settings"),
            InlineKeyboardButton("📊 Статус", callback_data="cmd_status")
        ],
        [
            InlineKeyboardButton("▶️ Сгенерировать", callback_data="cmd_generate")
        ]
    ])

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

# -------- Утилиты отправки сообщений --------

async def safe_send_text(bot, chat_id: int, text: str, retries: int = 5, parse_mode: str = 'Markdown', reply_markup=None):
    for attempt in range(retries):
        try:
            return await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup)
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
                return await bot.send_photo(chat_id=chat_id, photo=f, caption=caption, parse_mode='Markdown')
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
    user_limit = usage_tracker.get_user_limit(telegram_id)
    premium_badge = "⭐" if str(telegram_id) in PREMIUM_USERS else ""
    
    welcome_text = (
        f"👋 Привет, {user.get('name', 'пользователь')}! {premium_badge}\n\n"
        f"📊 Доступно генераций сегодня: `{remaining}/{user_limit}`\n\n"
        f"*Быстрые команды:*\n"
        f"📝 /prompt — задать описание\n"
        f"🖼 /refs — выбрать референсы\n"
        f"⚙️ /settings — настроить параметры\n"
        f"📊 /status — проверить конфигурацию\n"
        f"▶️ /gen — сгенерировать изображение\n"
        f"💾 `/set_<id>` — повторить сохраненную генерацию\n\n"
        f"ℹ️ /help — подробная помощь"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🔧 *Как использовать бота:*\n\n"
        "1️⃣ *Загрузка изображений:*\n"
        "Просто отправьте фото в чат, они сохранятся для использования как референсы.\n\n"
        "2️⃣ *Установка промпта:*\n"
        "Нажмите кнопку ниже или используйте /prompt ваше описание\n\n"
        "3️⃣ *Выбор референсов:*\n"
        "Нажмите 🖼 *Референсы* или используйте /refs\n\n"
        "4️⃣ *Параметры генерации:*\n"
        "Нажмите ⚙️ *Параметры* или используйте /settings\n"
        "— Температура, соотношение сторон, размер, seed\n\n"
        "5️⃣ *Проверка конфигурации:*\n"
        "Нажмите 📊 *Статус* или используйте /status\n\n"
        "6️⃣ *Генерация:*\n"
        "Нажмите ▶️ *Сгенерировать* или используйте /gen\n\n"
        "💾 *Сохранение конфигураций:*\n"
        "После каждой генерации бот выдает ID конфигурации.\n"
        "Нажмите на `/set_<id>` в сообщении для быстрой загрузки всех настроек.\n\n"
        "⚡ *Быстрый старт:*\n"
        "/prompt → /refs → /gen"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Задать промпт", callback_data="cmd_prompt")],
        [InlineKeyboardButton("🖼 Выбрать референсы", callback_data="cmd_refs")],
        [InlineKeyboardButton("⚙️ Открыть настройки", callback_data="cmd_settings")],
        [InlineKeyboardButton("📊 Проверить статус", callback_data="cmd_status")]
    ])
    
    await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=keyboard)

async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return
    used = usage_tracker.get_usage_count(telegram_id)
    user_limit = usage_tracker.get_user_limit(telegram_id)
    remaining = usage_tracker.get_remaining(telegram_id)
    premium_badge = "⭐ Premium" if str(telegram_id) in PREMIUM_USERS else ""
    
    bar_length = 10
    filled = int((used / user_limit) * bar_length) if user_limit else 0
    bar = "█" * filled + "░" * (bar_length - filled)
    
    await update.message.reply_text(
        f"📊 Использовано: `{used}/{user_limit}` {premium_badge}\n"
        f"Осталось: `{remaining}`\n"
        f"`[{bar}]`",
        parse_mode='Markdown'
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
        [InlineKeyboardButton("📊 Проверить статус", callback_data="cmd_status")]
    ]
    await update.message.reply_text(
        f"⚙️ *Текущие настройки:*\n\n"
        f"🌡 Температура: `{settings['temperature']}`\n"
        f"📐 Соотношение: `{settings['aspect_ratio']}`\n"
        f"📏 Размер: `{settings['image_size']}`\n"
        f"🎲 Seed: `{seed_text}`\n\n"
        f"💡 *Совет:* Seed из результата можно скопировать и установить здесь для повтора.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    data = query.data
    
    # Обработка навигационных команд из кнопок
    if data == "cmd_prompt":
        await query.edit_message_text("📝 Введите промпт:", parse_mode='Markdown')
        session = get_user_session(telegram_id)
        session["awaiting"] = "prompt"
        return
    elif data == "cmd_refs":
        await select_refs_command(update, context)
        return
    elif data == "cmd_settings":
        # Симулируем вызов settings_menu
        settings = get_user_settings(telegram_id)
        seed_value = settings.get('seed', -1)
        seed_text = "авто (случайный)" if seed_value <= 0 else str(seed_value)
        
        keyboard = [
            [InlineKeyboardButton("🌡 Температура", callback_data="set_temperature")],
            [InlineKeyboardButton("📐 Соотношение сторон", callback_data="set_aspect_ratio")],
            [InlineKeyboardButton("📏 Размер", callback_data="set_image_size")],
            [InlineKeyboardButton("🎲 Seed", callback_data="set_seed")],
            [InlineKeyboardButton("📊 Проверить статус", callback_data="cmd_status")]
        ]
        
        try:
            await query.edit_message_text(
                f"⚙️ *Текущие настройки:*\n\n"
                f"🌡 Температура: `{settings['temperature']}`\n"
                f"📐 Соотношение: `{settings['aspect_ratio']}`\n"
                f"📏 Размер: `{settings['image_size']}`\n"
                f"🎲 Seed: `{seed_text}`\n\n"
                f"💡 *Совет:* Seed из результата можно скопировать и установить здесь для повтора.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception:
            await query.edit_message_text("⚙️ Меню настроек открыто. Используйте /settings")
        return
    elif data == "cmd_status":
        await status_command(update, context)
        return
    elif data == "cmd_generate":
        await generate_command(update, context)
        return
    
    # Обработка настроек генерации
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
            [InlineKeyboardButton("🔙 Назад", callback_data="cmd_settings")]
        ]
        await query.edit_message_text("Выберите температуру:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("temp_"):
        temp = float(data.split("_")[1])
        user_settings[telegram_id]["temperature"] = temp
        await query.edit_message_text(f"✅ Температура: `{temp}`\n\nИспользуйте /settings чтобы изменить другие параметры или /status для проверки.", parse_mode='Markdown')
    
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
            [InlineKeyboardButton("🔙 Назад", callback_data="cmd_settings")]
        ]
        await query.edit_message_text("Выберите соотношение:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("ratio_"):
        ratio = data.split("_", 1)[1]
        user_settings[telegram_id]["aspect_ratio"] = ratio
        await query.edit_message_text(f"✅ Соотношение: `{ratio}`\n\nИспользуйте /settings чтобы изменить другие параметры или /status для проверки.", parse_mode='Markdown')
    
    elif data == "set_image_size":
        keyboard = [
            [InlineKeyboardButton("1K", callback_data="size_1K"),
             InlineKeyboardButton("2K", callback_data="size_2K"),
             InlineKeyboardButton("4K", callback_data="size_4K")],
            [InlineKeyboardButton("🔙 Назад", callback_data="cmd_settings")]
        ]
        await query.edit_message_text("Выберите размер:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("size_"):
        size = data.split("_", 1)[1]
        user_settings[telegram_id]["image_size"] = size
        await query.edit_message_text(f"✅ Размер: `{size}`\n\nИспользуйте /settings чтобы изменить другие параметры или /status для проверки.", parse_mode='Markdown')
    
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
            [InlineKeyboardButton("🔙 Назад", callback_data="cmd_settings")]
        ]
        current_text = "авто" if current_seed <= 0 else str(current_seed)
        await query.edit_message_text(
            "🎲 Выберите seed:\n\n"
            "• Случайный (-1) — каждый раз разный результат\n"
            "• Фиксированный — воспроизводимый результат\n\n"
            f"Текущий: `{current_text}`",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("seed_"):
        seed_str = data.split("_", 1)[1]
        if seed_str == "custom":
            context.user_data['awaiting_seed'] = True
            await query.edit_message_text(
                "✏️ Введите seed (целое число):\n\n"
                "• Положительное число — фиксированный seed\n"
                "• `-1` — случайный seed\n\n"
                "Отправьте числом в чат."
            )
        else:
            seed = int(seed_str)
            if seed == 1:
                seed = -1            
            user_settings[telegram_id]["seed"] = seed
            seed_text = "случайный" if seed <= 0 else str(seed)
            await query.edit_message_text(f"✅ Seed: `{seed_text}`\n\nИспользуйте /settings чтобы изменить другие параметры или /status для проверки.", parse_mode='Markdown')

# -------- Новые команды --------

async def set_prompt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка промпта через /prompt <текст>"""
    telegram_id = update.effective_user.id
    
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return
    
    text = update.message.text
    if text.startswith('/prompt'):
        text = text[7:].strip()
    
    if text:
        session = get_user_session(telegram_id)
        session["prompt"] = text
        keyboard = InlineKeyboardMarkup([
			[InlineKeyboardButton("▶️ Сгенерировать", callback_data="cmd_generate")],
            [InlineKeyboardButton("📝 Изменить промпт", callback_data="cmd_prompt")],
            [InlineKeyboardButton("🖼 Выбрать референсы", callback_data="cmd_refs")],
            [InlineKeyboardButton("⚙️ Параметры", callback_data="cmd_settings")],
            [InlineKeyboardButton("📊 Проверить статус", callback_data="cmd_status")]
        ])
        await update.message.reply_text(
            f"✅ *Промпт установлен:*\n`{text[:300]}{'...' if len(text) > 300 else ''}`\n\n"
            f"Выберите следующее действие:",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    else:
        session = get_user_session(telegram_id)
        session["awaiting"] = "prompt"
        await update.message.reply_text(
            "📝 *Введите текстовый промпт:*\n\n"
            "💡 Чем детальнее описание, тем лучше результат.",
            parse_mode='Markdown'
        )

async def select_refs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор референсных изображений через /refs"""
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return
    
    # Поддержка вызова из callback
    if update.callback_query:
        message = update.callback_query.message
        await update.callback_query.answer()
    else:
        message = update.message
    
    recent_images = image_storage.get_recent_images(telegram_id, limit=20)
    
    if not recent_images:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Задать промпт", callback_data="cmd_prompt")],
            [InlineKeyboardButton("📊 Статус", callback_data="cmd_status")]
        ])
        await message.reply_text(
            "📂 *У вас нет сохранённых изображений.*\n\n"
            "Загрузите изображения через чат, а затем используйте /refs",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    display_images = recent_images[:10]
    
    media_group = []
    preview_files = []
    
    for idx, img in enumerate(display_images):
        preview_path = create_numbered_preview_jpg(img, idx + 1)
        preview_files.append(preview_path)
        f = open(preview_path, "rb")
        media_group.append(InputMediaPhoto(media=f))
    
    try:
        await safe_send_media_group(context.bot, chat_id, media_group)
    except Exception as e:
        log_console("REFS_MEDIA_ERROR", "Failed to send media group", {"error": str(e)})
    finally:
        for media in media_group:
            try:
                media.media.close()
            except:
                pass
        for path in preview_files:
            try:
                os.unlink(path)
            except:
                pass
    
    keyboard = []
    row = []
    session = get_user_session(telegram_id)
    current_refs = session.get("refs", [])
    
    for idx, img in enumerate(display_images):
        is_selected = img in current_refs
        btn_text = f"✅ {idx+1}" if is_selected else f"📷 {idx+1}"
        row.append(InlineKeyboardButton(btn_text, callback_data=f"ref_sel_{idx}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("💾 Сохранить выбор", callback_data="refs_done")])
    keyboard.append([
        InlineKeyboardButton("❌ Очистить все", callback_data="refs_clear"),
        InlineKeyboardButton("▶️ Генерировать", callback_data="cmd_generate")
    ])
    
    selected_count = len(current_refs)
    await message.reply_text(
        f"📸 *Выбор референсных изображений*\n"
        f"Выбрано: `{selected_count}`\n\n"
        f"Нажмите на номер для выбора/отмены:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    context.user_data['ref_selection_images'] = display_images

async def refs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора референсов"""
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    data = query.data
    
    session = get_user_session(telegram_id)
    images = context.user_data.get('ref_selection_images', [])
    
    if data.startswith("ref_sel_"):
        idx = int(data.split("_")[2])
        if idx < len(images):
            img_path = images[idx]
            if img_path in session["refs"]:
                session["refs"].remove(img_path)
                await query.answer("❌ Убрано")
            else:
                session["refs"].append(img_path)
                await query.answer("✅ Добавлено")
        
        keyboard = []
        row = []
        for i, img in enumerate(images):
            is_sel = img in session["refs"]
            txt = f"✅ {i+1}" if is_sel else f"📷 {i+1}"
            row.append(InlineKeyboardButton(txt, callback_data=f"ref_sel_{i}"))
            if len(row) == 5:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("💾 Сохранить выбор", callback_data="refs_done")])
        keyboard.append([
            InlineKeyboardButton("❌ Очистить все", callback_data="refs_clear"),
            InlineKeyboardButton("▶️ Генерировать", callback_data="cmd_generate")
        ])
        
        selected = len(session["refs"])
        try:
            await query.edit_message_text(
                f"📸 *Выбор референсных изображений*\n"
                f"Выбрано: `{selected}`\n\n"
                f"Нажмите на номер для выбора/отмены:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception:
            pass
            
    elif data == "refs_clear":
        session["refs"] = []
        await query.edit_message_text(
            "❌ Референсы очищены.\n\n"
            "Используйте /refs чтобы выбрать снова или /gen для генерации без референсов, /status — проверить конфигурацию, /help — подробная помощь.",
            parse_mode='Markdown'
        )
        context.user_data.pop('ref_selection_images', None)
        
    elif data == "refs_done":
        count = len(session["refs"])
        keyboard = InlineKeyboardMarkup([
			[InlineKeyboardButton("▶️ Сгенерировать", callback_data="cmd_generate")],
            [InlineKeyboardButton("📝 Изменить промпт", callback_data="cmd_prompt")],
            [InlineKeyboardButton("🖼 Выбрать референсы", callback_data="cmd_refs")],
            [InlineKeyboardButton("⚙️ Параметры", callback_data="cmd_settings")],
            [InlineKeyboardButton("📊 Проверить статус", callback_data="cmd_status")]
        ])
        await query.edit_message_text(
            f"💾 *Сохранено референсов: {count}*\n\n"
            f"Выберите действие:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        context.user_data.pop('ref_selection_images', None)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущие настройки, промпт и референсы с кнопкой настроек"""
    telegram_id = update.effective_user.id
    
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return
    
    # Поддержка вызова из callback
    if update.callback_query:
        message = update.callback_query.message
        await update.callback_query.answer()
    else:
        message = update.message
    
    settings = get_user_settings(telegram_id)
    session = get_user_session(telegram_id)
    
    seed_val = settings.get('seed', -1)
    seed_text = "🎲 авто" if seed_val <= 0 else f"🎲 `{seed_val}`"
    
    refs_count = len(session.get("refs", []))
    prompt = session.get("prompt", "")
    prompt_text = f"`{prompt[:3500]}{'...' if len(prompt) > 3500 else ''}`" if prompt else "⚠️ *не задан*"
    
    # Отправляем превью референсов если есть (до 10 штук)
    refs = session.get("refs", [])
    if refs:
        media_group = []
        try:
            for idx, ref_path in enumerate(refs[:10]):
                with open(ref_path, "rb") as f:
                    photo_bytes = f.read()
                    caption = f"📷 Референс {idx+1}" if len(refs) > 1 else "📷 Референс"
                    media_group.append(InputMediaPhoto(media=photo_bytes, caption=caption))
            
            if media_group:
                await message.reply_media_group(media_group)
        except Exception as e:
            log_console("STATUS_PREVIEW_ERROR", "Failed to send refs preview", {"error": str(e)})
    
    text = (
        f"📊 *Текущая конфигурация генерации*\n\n"
        f"📝 *Промпт:*\n{prompt_text}\n\n"
        f"🖼 *Референсы:* `{refs_count} шт.`\n"
        f"🌡 Температура: `{settings['temperature']}`\n"
        f"📐 Соотношение: `{settings['aspect_ratio']}`\n"
        f"📏 Размер: `{settings['image_size']}`\n"
        f"{seed_text}\n\n"
    )
    
    if prompt:
        text += "✅ *Готова к генерации!*"
        keyboard_buttons = [
            [InlineKeyboardButton("▶️ Сгенерировать", callback_data="cmd_generate")],
            [InlineKeyboardButton("⚙️ Изменить настройки", callback_data="cmd_settings")],
            [InlineKeyboardButton("📝 Изменить промпт", callback_data="cmd_prompt")]
        ]
    else:
        text += "⚠️ *Задайте промпт перед генерацией*"
        keyboard_buttons = [
            [InlineKeyboardButton("📝 Задать промпт", callback_data="cmd_prompt")],
            [InlineKeyboardButton("⚙️ Параметры", callback_data="cmd_settings")]
        ]
    
    # Добавляем кнопку управления референсами 
    keyboard_buttons.insert(1, [InlineKeyboardButton("🖼 Изменить референсы", callback_data="cmd_refs")])
    
    keyboard = InlineKeyboardMarkup(keyboard_buttons)
    
    await message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)

async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск генерации с текущими настройками по команде /gen"""
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Поддержка вызова из callback
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message
    
    if not user_manager.is_authorized(telegram_id):
        await message.reply_text("❌ Доступ запрещен.")
        return
    
    if not usage_tracker.can_generate(telegram_id):
        await message.reply_text("❌ Дневной лимит генераций исчерпан!")
        return
    
    session = get_user_session(telegram_id)
    settings = get_user_settings(telegram_id)
    
    prompt = session.get("prompt", "")
    if not prompt:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Задать промпт", callback_data="cmd_prompt")]
        ])
        await message.reply_text(
            "⚠️ *Промпт не задан!*\n\n"
            "Нажмите кнопку ниже или используйте /prompt ваше описание",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    refs = session.get("refs", [])
    
    # Отправляем сообщение о старте
    start_msg = await message.reply_text("🔄 *Запуск генерации...*", parse_mode='Markdown')
    
    # Запускаем генерацию в фоне
    asyncio.create_task(
        _run_generation(
            context.bot, chat_id, telegram_id, 
            prompt, refs, settings, start_msg.message_id
        )
    )

async def _run_generation(bot, chat_id, telegram_id, prompt, refs_paths, settings, status_message_id=None):
    """Фоновая генерация с сохранением конфигурации"""
    start_time = datetime.now()
    config_id = generate_config_id()
    
    try:
        # Формируем финальный промпт с улучшенными инструкциями
        final_prompt = f"""You are a professional image generator. Your task is to ALWAYS create an image based on the user's request below.

CRITICAL INSTRUCTIONS:
- You MUST generate exactly ONE image, no matter what
- Do NOT refuse or explain why you cannot create something
- If the request seems unclear, interpret it creatively and generate anyway
- Focus on visual interpretation and artistic expression
- Avoid text responses - only generate the image
- Be creative and flexible in your interpretation

User's request:
{prompt}

Remember: Your only job is to CREATE THE IMAGE. Generate it now."""
        
        # Обновляем сообщение о статусе
        settings_text = format_settings_text(settings)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=f"🔄 *Генерация изображения...*\n\n"
                     f"📝 Промпт: `{prompt[:3500]}{'...' if len(prompt) > 3500 else ''}`\n"
                     f"🖼 Референсов: {len(refs_paths)}\n"
                     f"{settings_text}\n\n"
                     f"⏱ Это может занять 1-5 минут",
                parse_mode='Markdown'
            )
        except Exception:
            pass
        
        # Загружаем референсы
        ref_data = []
        for p in refs_paths:
            try:
                with open(p, "rb") as f:
                    ref_data.append(f.read())
            except Exception as e:
                log_console("REF_LOAD_ERROR", str(e))
        
        seed_setting = settings.get("seed", -1)
        
        AIRequestLogger.log({
            "event": "generation_start",
            "user_id": telegram_id,
            "prompt": prompt,
            "num_refs": len(ref_data),
            "settings": settings,
            "config_id": config_id
        })
        
        # Первая попытка генерации
        img_bytes, error, used_seed = await gemini_generator.generate_image(
            prompt=final_prompt,
            reference_images=ref_data,
            temperature=settings.get("temperature", 1.0),
            aspect_ratio=settings.get("aspect_ratio", "16:9"),
            image_size=settings.get("image_size", "1K"),
            seed=seed_setting,
        )
        
        # Если первая попытка не удалась - пробуем ещё раз с упрощенным промптом
        if error or not img_bytes:
            log_console("GENERATION_RETRY", f"First attempt failed: {error}, trying simplified prompt")
            
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message_id,
                    text=f"🔄 *Повторная попытка*\n\n"
                         f"⚠️ Первая попытка не удалась: `{error}`\n"
                         f"🔄 Пробуем упрощенный подход",
                    parse_mode='Markdown'
                )
            except Exception:
                pass
            
            # Упрощенный промпт для второй попытки
            simplified_prompt = f"""Create a safe, artistic, and creative image based on this concept: {prompt[:500]}

Important: Focus on visual beauty, artistic interpretation, and creative expression. Generate the image now."""
            
            # Вторая попытка: С референсами, более консервативная температура
            img_bytes, error, used_seed = await gemini_generator.generate_image(
                prompt=simplified_prompt,
                reference_images=ref_data,  # ОСТАВЛЯЕМ референсы
                temperature=0.7,  # Более консервативная температура
                aspect_ratio=settings.get("aspect_ratio", "16:9"),
                image_size=settings.get("image_size", "1K"),
                seed=seed_setting,
            )
        
        duration = (datetime.now() - start_time).total_seconds()
        
        if error or not img_bytes:
            error_msg = f"❌ Ошибка генерации: `{error or 'Unknown'}`"
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message_id,
                    text=error_msg,
                    parse_mode='Markdown'
                )
            except Exception:
                await safe_send_text(bot, chat_id, error_msg)
            return
        
        # Сохраняем изображение
        saved_path = image_storage.save_image(telegram_id, img_bytes, prefix="generated")
        
        # Увеличиваем счетчик использования
        usage_tracker.increment_usage(telegram_id)
        remaining = usage_tracker.get_remaining(telegram_id)
        user_limit = usage_tracker.get_user_limit(telegram_id)
        
        # Сохраняем конфигурацию для повторного использования
        save_generation_config(telegram_id, config_id, prompt, settings, refs_paths)
        
        # Удаляем статусное сообщение
        try:
            await bot.delete_message(chat_id, status_message_id)
        except Exception:
            pass
                
        # 1. Отправляем фото с минимальной подписью
        await safe_send_photo(bot, chat_id, saved_path, caption=f"✅ Готово! ⏱{int(duration)}с")
               
        # 2. Мета-информация (без markdown внутри переменных для безопасности)
        meta_text = (
            f"🎲 Seed: {used_seed}\n"
            f"🖼 Референсов: {len(ref_data)}\n"
            f"⏱ Время: {int(duration)}с\n"
            f"📊 Осталось: {remaining}/{user_limit}\n\n"
            f"💾 /set_{config_id}"
        )
        await safe_send_text(bot, chat_id, meta_text, parse_mode=None)
        
        # 3. Оригинал файлом
        await safe_send_document(bot, chat_id, saved_path, caption=f"📎 {len(img_bytes)//1024} KB")
        
        # 4. Клавиатура действий
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Повторить", callback_data="cmd_generate")],
            [InlineKeyboardButton("📝 Изменить промпт", callback_data="cmd_prompt")],
            [InlineKeyboardButton("🖼 Выбрать референсы", callback_data="cmd_refs")],
            [InlineKeyboardButton("⚙️ Параметры", callback_data="cmd_settings")],
            [InlineKeyboardButton("📊 Проверить статус", callback_data="cmd_status")]
        ])
        await safe_send_text(bot, chat_id, "Выберите действие:", reply_markup=keyboard)
        
        AIRequestLogger.log({
            "event": "generation_success",
            "user_id": telegram_id,
            "config_id": config_id,
            "seed": used_seed,
            "duration": duration
        })
        
    except Exception as e:
        log_console("GENERATION_ERROR", str(e), {"trace": traceback.format_exc()})
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text="❌ Произошла критическая ошибка при генерации."
            )
        except Exception:
            await safe_send_text(bot, chat_id, "❌ Произошла критическая ошибка при генерации.")

async def load_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Загрузка сохраненной конфигурации по /set_<id> или кнопке"""
    telegram_id = update.effective_user.id
    
    # Обработка callback от кнопки
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        if data.startswith("load_config_"):
            config_id = data.replace("load_config_", "")
            message = query.message
        else:
            return
    else:
        text = update.message.text.strip()
        match = re.match(r'^/set_([a-zA-Z0-9_]+)$', text)
        if not match:
            await update.message.reply_text("❌ Неверный формат. Используйте: `/set_<id>`", parse_mode='Markdown')
            return
        config_id = match.group(1)
        message = update.message
    
    if not user_manager.is_authorized(telegram_id):
        await message.reply_text("❌ Доступ запрещен.")
        return
    
    config = load_generation_config(telegram_id, config_id)
    
    if not config:
        await message.reply_text(f"❌ Конфигурация `{config_id}` не найдена.", parse_mode='Markdown')
        return
    
    # Устанавливаем настройки в сессию
    session = get_user_session(telegram_id)
    session["prompt"] = config["prompt"]
    session["refs"] = config["references"]
    
    # Обновляем settings
    loaded_settings = config.get("settings", {})
    if telegram_id not in user_settings:
        user_settings[telegram_id] = DEFAULT_SETTINGS.copy()
    for key in ["temperature", "aspect_ratio", "image_size", "seed"]:
        if key in loaded_settings:
            user_settings[telegram_id][key] = loaded_settings[key]
    
    # Формируем отчет
    refs_count = len(config["references"])
    total_refs_saved = len(config.get("references", []))
    
    seed_val = loaded_settings.get('seed', -1)
    seed_text = "авто" if seed_val <= 0 else str(seed_val)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Сгенерировать", callback_data="cmd_generate")],
        [InlineKeyboardButton("📝 Изменить промпт", callback_data="cmd_prompt")],
        [InlineKeyboardButton("🖼 Выбрать референсы", callback_data="cmd_refs")],
        [InlineKeyboardButton("⚙️ Параметры", callback_data="cmd_settings")],
        [InlineKeyboardButton("📊 Проверить статус", callback_data="cmd_status")]
    ])
    
    await message.reply_text(
        f"✅ *Конфигурация загружена!*\n\n"
        f"📝 Промпт:\n`{config['prompt'][:3500]}{'...' if len(config['prompt']) > 3500 else ''}`\n\n"
        f"🖼 Референсов доступно: `{refs_count}/{total_refs_saved}` шт.\n"
        f"🌡 Температура: `{loaded_settings.get('temperature')}`\n"
        f"📐 Соотношение: `{loaded_settings.get('aspect_ratio')}`\n"
        f"📏 Размер: `{loaded_settings.get('image_size')}`\n"
        f"🎲 Seed: `{seed_text}`\n\n"
        f"Теперь можно запускать генерацию:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    telegram_id = update.effective_user.id
    session = get_user_session(telegram_id)
    session["awaiting"] = None
    await update.message.reply_text("❌ Действие отменено.", reply_markup=get_main_menu_keyboard())

# -------- Обработка фото и текста --------

async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение загруженных фото для дальнейшего использования как референсов"""
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
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼 Выбрать референсы", callback_data="cmd_refs")],
            [InlineKeyboardButton("📊 Статус", callback_data="cmd_status")]
        ])
        
        await update.message.reply_text(
            f"✅ *Изображение сохранено:* `{saved_path.name}`\n\n"
            f"Теперь вы можете выбрать его как референс:",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    except Exception as e:
        log_console("PHOTO_ERROR", "Error saving photo", {"error": str(e)})
        await update.message.reply_text("❌ Ошибка при сохранении изображения.")

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений (для интерактивного ввода промпта или seed)"""
    telegram_id = update.effective_user.id
    session = get_user_session(telegram_id)
    
    # Обработка отмены через callback
    if update.callback_query and update.callback_query.data == "cancel_input":
        await update.callback_query.answer()
        session["awaiting"] = None
        await update.callback_query.edit_message_text("❌ Ввод отменен.")
        return
    
    # Проверяем, ожидаем ли ввод seed
    if context.user_data.get('awaiting_seed', False):
        try:
            seed = int(update.message.text.strip())
            if telegram_id not in user_settings:
                user_settings[telegram_id] = DEFAULT_SETTINGS.copy()
            user_settings[telegram_id]["seed"] = seed
            seed_text = "авто (случайный)" if seed <= 0 else str(seed)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Параметры", callback_data="cmd_settings")],
                [InlineKeyboardButton("📊 Статус", callback_data="cmd_status")]
            ])
            await update.message.reply_text(
                f"✅ Seed установлен: `{seed_text}`",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        except ValueError:
            await update.message.reply_text("❌ Введите целое число (например: `1234567890` или `-1` для авто)", parse_mode='Markdown')
        context.user_data['awaiting_seed'] = False
        return
    
    # Проверяем, ожидаем ли ввод промпта
    if session.get("awaiting") == "prompt":
        prompt = update.message.text
        if prompt.startswith('/'):
            await update.message.reply_text("❌ Промпт не может начинаться с `/`. Введите обычный текст или используйте /cancel")
            return
        
        session["prompt"] = prompt
        session["awaiting"] = None
        
        keyboard = InlineKeyboardMarkup([
			[InlineKeyboardButton("▶️ Сгенерировать", callback_data="cmd_generate")],
            [InlineKeyboardButton("📝 Изменить промпт", callback_data="cmd_prompt")],
            [InlineKeyboardButton("🖼 Выбрать референсы", callback_data="cmd_refs")],
            [InlineKeyboardButton("⚙️ Параметры", callback_data="cmd_settings")],
            [InlineKeyboardButton("📊 Проверить статус", callback_data="cmd_status")]
        ])
        
        await update.message.reply_text(
            f"✅ *Промпт установлен:*\n`{prompt[:3500]}{'...' if len(prompt) > 3500 else ''}`\n\n"
            f"Выберите следующее действие:",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        return
    
    # Если не ожидаем ввод, показываем меню
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Задать промпт", callback_data="cmd_prompt")],
        [InlineKeyboardButton("🖼 Выбрать референсы", callback_data="cmd_refs")],
        [InlineKeyboardButton("⚙️ Параметры", callback_data="cmd_settings")],
        [InlineKeyboardButton("📊 Статус", callback_data="cmd_status")]
    ])
    await update.message.reply_text(
        "ℹ️ Выберите команду из меню ниже:",
        reply_markup=keyboard
    )

async def reset_user_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = user_manager.get_user(telegram_id)
    if not user or not user.get('admin', False):
        await update.message.reply_text("❌ Нет прав.")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Использование: /reset_usage <telegram_id>", parse_mode='Markdown')
        return
    try:
        target_user_id = int(context.args[0])
        usage_tracker.reset_usage(target_user_id)
        await update.message.reply_text(f"✅ Лимиты пользователя `{target_user_id}` сброшены.", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("Неверный ID пользователя.")

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
            await safe_send_text(context.bot, update.effective_chat.id, "⚠️ Произошла ошибка. Попробуйте позже.")
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

    # Основные команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_menu))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("reset_usage", reset_user_usage))
    
    # Новые команды рабочего процесса
    application.add_handler(CommandHandler("prompt", set_prompt_command))
    application.add_handler(CommandHandler("refs", select_refs_command))
    application.add_handler(CommandHandler("gen", generate_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    
    # Обработка команд загрузки конфига /set_<id> и кнопок load_config_
    application.add_handler(CallbackQueryHandler(load_config_command, pattern=r"^load_config_"))
    application.add_handler(MessageHandler(filters.Regex(r'^/set_[a-zA-Z0-9_]+$'), load_config_command))
    
    # Callbacks для настроек и навигации
    application.add_handler(
        CallbackQueryHandler(settings_callback, pattern="^(set_|temp_|ratio_|size_|seed_|cmd_)")
    )
    
    # Callbacks для выбора референсов
    application.add_handler(
        CallbackQueryHandler(refs_callback, pattern="^(ref_sel_|refs_done|refs_clear|cancel_input)")
    )

    # Фото и документы
    application.add_handler(MessageHandler(filters.PHOTO, process_photo))
    application.add_handler(MessageHandler(filters.Document.IMAGE, process_photo))
    
    # Текстовые сообщения (для интерактивного ввода)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    application.add_error_handler(global_error_handler)

    print("=" * 60)
    print("🤖 Gemini Image Generator Bot (Interactive)")
    print("=" * 60)
    print(f"📊 Лимит: {DAILY_LIMIT}/день (обычный)")
    print(f"⭐ Лимит Premium: {DAILY_LIMIT_PREMIUM}/день")
    print(f"👥 Пользователей: {len(user_manager.users)}")
    print(f"💎 Premium: {len(PREMIUM_USERS)}")
    print(f"⏱ Таймаут: {GEMINI_GENERATION_TIMEOUT}s")
    print(f"🎲 Seed: {SEED_MIN} - {SEED_MAX}")
    print("=" * 60)

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()