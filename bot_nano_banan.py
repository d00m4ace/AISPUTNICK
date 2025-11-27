import os
import json
import asyncio
import base64
import mimetypes
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

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

# Gemini / genai client
from google import genai
from google.genai import types

# ========== Настройки (подставь свои) ==========

TELEGRAM_TOKEN = "82...nU"
GEMINI_API_KEY = "AI...wg"
USERS_FILE = "sputnkik_bot_users/users.json"
IMAGES_BASE_DIR = "nano_user_images"
USAGE_FILE = "nano_user_usage.json"
DAILY_LIMIT = 20
# ===============================================

def log_console(tag: str, message: str, data: Optional[dict] = None):
    print(f"\n===== {tag} =====")
    print(message)
    if data:
        for k, v in data.items():
            print(f"  {k}: {v}")
    print("=" * 30 + "\n")

# defaults
DEFAULT_SETTINGS = {
    "temperature": 1.0,
    "aspect_ratio": "16:9",
    "image_size": "1K"
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
        # ✅ ИСПРАВЛЕНИЕ: читаем файл только ОДИН раз при инициализации
        self.users = self._load_users_once()

    def _load_users_once(self) -> Dict:
        """Загружает users.json ОДИН раз при старте бота"""
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
            log_console("USERS_FILE_NOT_FOUND", f"File {self.users_file} not found, starting with empty users")
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
    """Асинхронный генератор изображений через Gemini API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.model = "gemini-3-pro-image-preview"
    
    async def generate_image(
        self,
        prompt: str,
        reference_images: List[bytes],
        temperature: float = 0.85,
        aspect_ratio: str = "16:9",
        image_size: str = "1K"
    ) -> Optional[bytes]:
        """
        Нативная асинхронная генерация изображения
        """
        try:
            client = genai.Client(api_key=self.api_key)
        
            parts = []
            for img_data in reference_images:
                parts.append(
                    types.Part.from_bytes(
                        mime_type="image/png", 
                        data=img_data
                    )
                )
            parts.append(types.Part.from_text(text=prompt))
        
            contents = [types.Content(role="user", parts=parts)]
        
            generate_content_config = types.GenerateContentConfig(
                temperature=temperature,
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                ),
            )
        
            response_stream = await client.aio.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
            )
        
            async for chunk in response_stream:
                if (chunk.candidates and
                    chunk.candidates[0].content and
                    chunk.candidates[0].content.parts):
                
                    part = chunk.candidates[0].content.parts[0]
                
                    if part.inline_data and part.inline_data.data:
                        return part.inline_data.data
        
            return None
        
        except Exception as e:
            log_console(
                "GEMINI_ASYNC_ERROR", 
                "Error in native async generation", 
                {"error": str(e), "trace": traceback.format_exc()}
            )
            return None

# ✅ ИСПРАВЛЕНИЕ: Глобальные объекты инициализируются ОДИН раз
user_manager = UserManager(USERS_FILE)
image_storage = ImageStorage(IMAGES_BASE_DIR)
gemini_generator = GeminiImageGenerator(GEMINI_API_KEY)
usage_tracker = UsageTracker(USAGE_FILE, DAILY_LIMIT)

# В памяти
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

# ✅ НОВАЯ ФУНКЦИЯ: форматирование настроек для вывода
def format_settings_text(settings: Dict) -> str:
    """Форматирует настройки в читаемый текст"""
    return (
        f"⚙️ Параметры генерации:\n"
        f"  🌡 Температура: {settings['temperature']}\n"
        f"  📐 Соотношение: {settings['aspect_ratio']}\n"
        f"  📏 Размер: {settings['image_size']}"
    )

# ------ utility: safe send with retries ------
async def safe_send_text(bot, chat_id: int, text: str, retries: int = 3):
    for attempt in range(retries):
        try:
            return await bot.send_message(chat_id=chat_id, text=text)
        except (TimedOut, NetworkError) as e:
            log_console("SEND_MESSAGE_RETRY", f"Timed out sending message, attempt {attempt+1}", {"error": str(e)})
            await asyncio.sleep(1 + attempt)
        except RetryAfter as e:
            wait = e.retry_after if hasattr(e, "retry_after") else 1
            await asyncio.sleep(wait)
        except Exception as e:
            log_console("SEND_MESSAGE_ERROR", "Unexpected error sending message", {"error": str(e)})
            break
    raise RuntimeError("Failed to send message after retries")

async def safe_send_photo(bot, chat_id: int, photo_path: Path, caption: Optional[str] = None, retries: int = 3):
    for attempt in range(retries):
        try:
            with open(photo_path, "rb") as f:
                return await bot.send_photo(chat_id=chat_id, photo=f, caption=caption)
        except (TimedOut, NetworkError) as e:
            log_console("SEND_PHOTO_RETRY", f"Timed out sending photo, attempt {attempt+1}", {"error": str(e)})
            await asyncio.sleep(1 + attempt)
        except RetryAfter as e:
            wait = e.retry_after if hasattr(e, "retry_after") else 1
            await asyncio.sleep(wait)
        except Exception as e:
            log_console("SEND_PHOTO_ERROR", "Unexpected error sending photo", {"error": str(e)})
            break
    raise RuntimeError("Failed to send photo after retries")

async def safe_send_document(bot, chat_id: int, document_path: Path, caption: Optional[str] = None, retries: int = 3):
    """Отправка документа с повторными попытками"""
    for attempt in range(retries):
        try:
            with open(document_path, "rb") as f:
                return await bot.send_document(
                    chat_id=chat_id, 
                    document=f, 
                    caption=caption,
                    filename=document_path.name
                )
        except (TimedOut, NetworkError) as e:
            log_console("SEND_DOCUMENT_RETRY", f"Timed out sending document, attempt {attempt+1}", {"error": str(e)})
            await asyncio.sleep(1 + attempt)
        except RetryAfter as e:
            wait = e.retry_after if hasattr(e, "retry_after") else 1
            await asyncio.sleep(wait)
        except Exception as e:
            log_console("SEND_DOCUMENT_ERROR", "Unexpected error sending document", {"error": str(e)})
            break
    raise RuntimeError("Failed to send document after retries")

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
        "Загрузи свои изображения для использования в качестве референсов, а затем используй команду /generate для создания новых изображений на основе текстового промпта и выбранных референсов.\n\n"
        "1. /generate - начать\n"
        "2. Выберите референсы или пропустите\n"
        "3. Введите промпт\n"
        "4. Получите сгенерированное изображение\n\n"
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
        f"📊 Использовано: {used}/{DAILY_LIMIT}\nОсталось: {remaining}\n[{bar}]"
    )

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return
    settings = get_user_settings(telegram_id)
    keyboard = [
        [InlineKeyboardButton("🌡 Температура", callback_data="set_temperature")],
        [InlineKeyboardButton("📐 Соотношение сторон", callback_data="set_aspect_ratio")],
        [InlineKeyboardButton("📏 Размер", callback_data="set_image_size")],
    ]
    await update.message.reply_text(
        f"Температура: {settings['temperature']}\n"
        f"Соотношение: {settings['aspect_ratio']}\n"
        f"Размер: {settings['image_size']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    data = query.data
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

async def generate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return

    if not usage_tracker.can_generate(telegram_id):
        await update.message.reply_text("❌ Вы достигли дневного лимита генераций!")
        return

    remaining = usage_tracker.get_remaining(telegram_id)
    await update.message.reply_text(f"🎨 Начинаем генерацию. Осталось: {remaining}/{DAILY_LIMIT}\nВыберите референсы или пропустите.")

    recent_images = image_storage.get_recent_images(telegram_id, limit=20)
    user_selected_images[telegram_id] = []

    if not recent_images:
        await update.message.reply_text("У вас нет сохранённых изображений. Введите текстовый промпт:")
        context.user_data['awaiting_prompt'] = True
        return

    batch = recent_images[:min(10, len(recent_images))]
    media_group = []
    preview_paths = []
    for idx, img in enumerate(batch):
        preview_path = create_numbered_preview_jpg(img, idx + 1)
        preview_paths.append(preview_path)
        media_group.append(InputMediaPhoto(open(preview_path, "rb")))
    try:
        await update.message.reply_media_group(media_group)
    except Exception:
        pass
    
    keyboard = []
    row = []
    for idx, img in enumerate(recent_images[:10]):
        row.append(InlineKeyboardButton(f"📷 {idx+1}", callback_data=f"select_img_{idx}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="images_done")])
    keyboard.append([InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_images")])
    
    await update.message.reply_text("Выберите референсные изображения:", reply_markup=InlineKeyboardMarkup(keyboard))
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
        
        keyboard = []
        row = []
        for idx, img in enumerate(recent_images[:10]):
            is_selected = "✓" if (idx < len(recent_images) and recent_images[idx] in user_selected_images.get(telegram_id, [])) else ""
            button_text = f"{is_selected}📷 {idx+1}" if is_selected else f"📷 {idx+1}"
            row.append(InlineKeyboardButton(button_text, callback_data=f"select_img_{idx}"))
            if len(row) == 5:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="images_done")])
        keyboard.append([InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_images")])
        
        try:
            await query.edit_message_text(f"Выбрано: {selected_count}", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            pass

    elif query.data in ("images_done", "skip_images"):
        selected_count = len(user_selected_images.get(telegram_id, []))
        await query.edit_message_text(f"Выбрано изображений: {selected_count}\nВведите текстовый промпт:")
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
        elif update.message.document and update.message.document.mime_type.startswith("image/"):
            file = await update.message.document.get_file()
        else:
            await update.message.reply_text("Это не изображение.")
            return
        photo_bytes = await file.download_as_bytearray()
        saved_path = image_storage.save_image(telegram_id, bytes(photo_bytes), prefix="uploaded")
        log_console("PHOTO SAVED", f"Saved for {telegram_id}", {"path": str(saved_path)})
        await update.message.reply_text(f"✅ Изображение сохранено: {saved_path.name}")
    except Exception as e:
        log_console("PHOTO_ERROR", "Error saving uploaded photo", {"error": str(e), "trace": traceback.format_exc()})
        await update.message.reply_text("❌ Ошибка при сохранении изображения.")

async def _background_generate_and_send(bot, chat_id: int, telegram_id: int, prompt: str, reference_images_paths: List[Path], settings: Dict):
    """Фоновая задача: вызывает Gemini, сохраняет и шлёт изображение"""
    try:
        # ✅ ДОБАВЛЕНО: вывод параметров ПЕРЕД генерацией
        settings_text = format_settings_text(settings)
        await safe_send_text(bot, chat_id, f"🔄 Начинаю генерацию...\n\n{settings_text}")
        
        # Подготовка референс-байтов
        reference_images_data = []
        for p in reference_images_paths:
            try:
                with open(p, "rb") as f:
                    reference_images_data.append(f.read())
            except Exception as e:
                log_console("REF_READ_ERROR", f"Failed to read {p}", {"error": str(e)})

        AIRequestLogger.log({
            "event": "request_start",
            "user_id": telegram_id,
            "prompt": prompt,
            "num_reference_images": len(reference_images_data),
            "reference_image_paths": [str(p) for p in reference_images_paths],
            "settings": settings,
        })

        # Генерация
        generated_bytes = await gemini_generator.generate_image(
            prompt=prompt,
            reference_images=reference_images_data,
            temperature=settings.get("temperature", 1.0),
            aspect_ratio=settings.get("aspect_ratio", "16:9"),
            image_size=settings.get("image_size", "1K"),
        )

        success = generated_bytes is not None
        error_text = None
        if not success:
            error_text = "No image returned from generator."

        AIRequestLogger.log({
            "event": "request_end",
            "user_id": telegram_id,
            "prompt": prompt,
            "success": success,
            "error": error_text,
            "settings": settings,
            "num_reference_images": len(reference_images_data),
        })

        if not success:
            try:
                await safe_send_text(bot, chat_id, "❌ Ошибка при генерации изображения. Попробуйте ещё раз.")
            except Exception:
                pass
            return

        # Сохранить изображение
        saved_path = image_storage.save_image(telegram_id, generated_bytes, prefix="generated")
        usage_tracker.increment_usage(telegram_id)
        remaining = usage_tracker.get_remaining(telegram_id)

        # ✅ ДОБАВЛЕНО: вывод параметров ПОСЛЕ генерации в caption
        caption = (
            f"✅ Изображение сгенерировано!\n\n"
            f"📝 Промпт: {prompt}\n"
            f"🖼 Референсов: {len(reference_images_data)}\n"
            f"📊 Осталось: {remaining}/{DAILY_LIMIT}\n\n"
            f"{settings_text}"
        )

        # Отправляем превью (сжатое фото)
        try:
            await safe_send_photo(bot, chat_id, saved_path, caption=caption)
        except Exception as e:
            log_console("SEND_PHOTO_ERROR", "Failed to send preview photo", {"error": str(e)})
        
        # Отправляем оригинал без сжатия как документ
        try:
            await safe_send_document(bot, chat_id, saved_path, caption="📎 Оригинал без сжатия")
        except Exception as e:
            log_console("SEND_DOCUMENT_ERROR", "Failed to send original document", {"error": str(e)})
            try:
                await safe_send_text(bot, chat_id, "⚠️ Не удалось отправить оригинал без сжатия.")
            except Exception:
                pass

    except Exception as e:
        log_console("BG_GENERATE_ERROR", "Unexpected error in background generation", {"error": str(e), "trace": traceback.format_exc()})
        try:
            await safe_send_text(bot, chat_id, "❌ Внутренняя ошибка при генерации. Попробуйте позже.")
        except Exception:
            pass

async def process_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not context.user_data.get('awaiting_prompt', False):
        return

    prompt = update.message.text
    if not user_manager.is_authorized(telegram_id):
        await update.message.reply_text("❌ Доступ запрещен.")
        return

    if not usage_tracker.can_generate(telegram_id):
        await update.message.reply_text("❌ Вы достигли дневного лимита генераций!")
        context.user_data['awaiting_prompt'] = False
        if telegram_id in user_selected_images:
            del user_selected_images[telegram_id]
        return

    await update.message.reply_text("⏳ Принял промпт — запускаю генерацию. Я пришлю результат сюда, как только он будет готов.")
    log_console("PROMPT_RECEIVED", f"User {telegram_id} prompt", {"prompt": prompt})

    selected_images = user_selected_images.get(telegram_id, [])
    reference_images_paths = [p for p in selected_images]

    settings = get_user_settings(telegram_id)

    AIRequestLogger.log({
        "event": "request_queued",
        "user_id": telegram_id,
        "prompt": prompt,
        "num_reference_images": len(reference_images_paths),
        "settings": settings,
    })

    asyncio.create_task(
        _background_generate_and_send(context.bot, chat_id, telegram_id, prompt, reference_images_paths, settings)
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
        await update.message.reply_text("❌ У вас нет прав.")
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Использование: /reset_usage <telegram_id>")
        return
    try:
        target_user_id = int(context.args[0])
        usage_tracker.reset_usage(target_user_id)
        await update.message.reply_text(f"✅ Лимиты пользователя {target_user_id} сброшены.")
    except ValueError:
        await update.message.reply_text("Неверный ID.")

async def global_error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
    log_console("GLOBAL_ERROR", "Exception in handler", {"error": str(context.error), "trace": traceback.format_exc()})
    try:
        if update and update.effective_chat:
            await safe_send_text(context.bot, update.effective_chat.id, "⚠️ Произошла ошибка. Администратор уведомлён.")
    except Exception:
        pass

def main():
    """
    Точка входа - создаёт и запускает бота
    """
    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=20.0,
        write_timeout=20.0,
        pool_timeout=20.0,
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
        CallbackQueryHandler(
            settings_callback, 
            pattern="^(set_|temp_|ratio_|size_)"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            image_selection_callback, 
            pattern="^(select_img_|images_done|skip_images)"
        )
    )

    application.add_handler(MessageHandler(filters.PHOTO, process_photo))
    application.add_handler(MessageHandler(filters.Document.IMAGE, process_photo))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            process_text_message
        )
    )

    application.add_error_handler(global_error_handler)

    print("=" * 50)
    print("🤖 Бот запущен и готов к работе!")
    print(f"📊 Дневной лимит генераций: {DAILY_LIMIT}")
    print(f"👥 Авторизованных пользователей: {len(user_manager.users)}")
    print("=" * 50)

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()