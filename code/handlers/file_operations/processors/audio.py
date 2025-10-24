# code/handlers/file_operations/processors/audio.py
"""
Процессор для обработки аудио файлов
"""
import os
import re
import secrets
import logging
from datetime import datetime
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from .base_processor import BaseProcessor

from user_activity_logger import activity_logger

logger = logging.getLogger(__name__)


class AudioProcessor(BaseProcessor):
    """Обработчик аудио файлов"""
    
    # Telegram's file download limit for bots - this is a hard limit
    TELEGRAM_BOT_FILE_LIMIT = 20 * 1024 * 1024  # 20MB
    
    def __init__(self, parent_handler):
        super().__init__(parent_handler)
        self.audio_converter = parent_handler.audio_converter

    def _format_transcript_text(self, text: str) -> str:
        """Форматирует текст транскрипции для лучшей читаемости"""
        # Заменяем множественные пробелы на один
        text = re.sub(r'\s+', ' ', text)
        
        # Разбиваем на предложения
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        formatted_lines = []
        current_paragraph = []
        current_length = 0
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # Добавляем предложение в текущий абзац
            current_paragraph.append(sentence)
            current_length += len(sentence)
            
            # Если абзац становится длинным или заканчивается на восклицание/вопрос
            if (current_length > 500 or 
                sentence.endswith('!') or 
                sentence.endswith('?') or
                len(current_paragraph) >= 3):
                
                # Объединяем предложения в абзац
                paragraph = ' '.join(current_paragraph)
                formatted_lines.append(paragraph)
                formatted_lines.append('')  # Пустая строка между абзацами
                
                current_paragraph = []
                current_length = 0
        
        # Добавляем оставшиеся предложения
        if current_paragraph:
            paragraph = ' '.join(current_paragraph)
            formatted_lines.append(paragraph)
        
        # Убираем лишние пустые строки
        result = '\n'.join(formatted_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)
        
        return result.strip()

    def _format_duration(self, seconds: int) -> str:
        """Форматирует длительность в читаемый вид"""
        if seconds < 60:
            return f"{seconds} сек"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}:{secs:02d}"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            return f"{hours}:{minutes:02d}:{secs:02d}"

    def _get_audio_compression_tips(self, file_size: int, duration: int = None) -> str:
        """Возвращает советы по сжатию аудио файла"""
        size_mb = file_size / (1024 * 1024)
        
        tips = [
            "💡 **Как уменьшить размер аудио файла:**\n"
        ]
        
        # Рассчитываем примерный битрейт если известна длительность
        if duration and duration > 0:
            current_bitrate = (file_size * 8) / duration / 1000  # в kbps
            recommended_bitrate = min(128, (self.TELEGRAM_BOT_FILE_LIMIT * 8) / duration / 1000 * 0.9)
            
            tips.append(f"📊 Текущий битрейт: ~{current_bitrate:.0f} kbps")
            tips.append(f"✅ Рекомендуемый битрейт: {recommended_bitrate:.0f} kbps или ниже\n")
        
        tips.extend([
            "**🎧 Инструкция для Audacity (рекомендуется):**",
            "1. Скачайте [Audacity](https://www.audacityteam.org/) - бесплатный редактор",
            "2. Откройте ваш аудио файл: `File → Open`",
            "3. Экспортируйте с оптимальными настройками: `File → Export → Export Audio`",
            "4. **Настройки экспорта для речи/подкастов:**",
            "   • Format: `Ogg Vorbis Files` (лучшее сжатие)",
            "   • Channels: `Mono` (уменьшает размер вдвое)",
            "   • Sample Rate: `22050 Hz` или `44100 Hz`",
            "   • Quality: `0-2` (для речи достаточно)",
            "5. **Альтернатива - MP3:**",
            "   • Format: `MP3 Files`",
            "   • Bit Rate Mode: `Constant`",
            "   • Quality: `64-96 kbps` (для речи)",
            "   • Channel Mode: `Mono`\n",
            
            "**Онлайн конвертеры (без установки):**",
            "• [Online Audio Converter](https://online-audio-converter.com/ru/) - полностью бесплатный",
            "• [CloudConvert](https://cloudconvert.com/mp3-converter) - 25 конвертаций/день",
            "• [Convertio](https://convertio.co/ru/mp3-converter/) - до 100MB бесплатно\n",
        ])
        
        # Для очень больших файлов - дополнительные советы
        if size_mb > 40:
            tips.extend([
                "**📁 Для очень больших файлов (>40MB):**",
                "• **В Audacity:** разделите на части",
                "  - Выделите первые 20 минут: `Edit → Select → Region`",
                "  - Экспортируйте выделенное: `File → Export → Export Selected Audio`",
                "  - Повторите для остальных частей",
                "• Или используйте [Mp3splt](http://mp3splt.sourceforge.net/) для авто-разделения\n"
            ])
        
        tips.extend([
            "**📱 Мобильные приложения:**",
            "• [MP3 Converter](https://play.google.com/store/apps/details?id=com.AndroidRock.Mp3Converter) (Android)",
            "• [Audio Converter](https://apps.apple.com/app/id1285358109) (iOS)",
            "• [Lexis Audio Editor](https://play.google.com/store/apps/details?id=com.pamsys.lexisaudioeditor) (Android)\n",
            
            f"📌 **Цель:** уменьшить размер до {self.TELEGRAM_BOT_FILE_LIMIT / (1024*1024):.0f} MB",
            f"💡 **Совет:** Для речи используйте Mono + низкий битрейт (64-96 kbps)"
        ])
        
        return "\n".join(tips)

    async def handle_voice(self, message: types.Message, state: FSMContext):
        """Обработка голосовых сообщений Telegram"""
        user_id = str(message.from_user.id)
        
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
        
        # Проверяем наличие активной кодовой базы
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if not user_codebases["active"]:
            await message.reply(
                "❌ Нет активной кодовой базы.\n"
                "Создайте или выберите кодовую базу для загрузки файлов.\n"
                "/create_codebase - создать новую\n"
                "/codebases - список баз"
            )
            return
        
        if not self.audio_converter:
            await message.reply(
                "❌ Распознавание голоса недоступно.\n"
                "Не настроен OpenAI API ключ."
            )
            return
        
        voice = message.voice
        duration = voice.duration
        file_size = voice.file_size
        
        # Проверяем размер файла
        if file_size > self.TELEGRAM_BOT_FILE_LIMIT:
            # Голосовые сообщения обычно не бывают такими большими, но на всякий случай
            await message.reply(
                f"❌ Голосовое сообщение слишком большое.\n"
                f"Максимальный размер: {self.file_manager.format_size(self.TELEGRAM_BOT_FILE_LIMIT)}\n"
                f"Размер вашего файла: {self.file_manager.format_size(file_size)}\n\n"
                f"Попробуйте записать более короткое сообщение."
            )
            return
        
        # Генерируем имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"voice_{timestamp}.ogg"
        text_filename = f"voice_{timestamp}_transcript.txt"
        
        processing_msg = await message.reply(
            f"🎤 Обрабатываю голосовое сообщение...\n"
            f"⏱️ Длительность: {duration} сек\n"
            f"📊 Размер: {self.file_manager.format_size(file_size)}"
        )
        
        try:
            # Загружаем файл
            tg_file = await self.bot.get_file(voice.file_id)
            stream = await self.bot.download_file(tg_file.file_path)
            voice_bytes = stream.getvalue() if hasattr(stream, "getvalue") else stream
            
            # Обновляем сообщение
            await processing_msg.edit_text(
                f"🎤 Распознаю речь...\n"
                f"⏱️ Длительность: {duration} сек\n"
                f"⏳ Это может занять некоторое время..."
            )
            
            # Распознаем
            success, _, raw_text = await self.audio_converter.convert_to_text(
                voice_bytes,
                filename,
                language='ru'
            )
            
            if success and raw_text:
                # Форматируем текст
                text = self._format_transcript_text(raw_text)
                
                # Подсчитываем статистику
                words = len(text.split())
                chars = len(text)
                lines = len(text.split('\n'))
                
                # Показываем превью текста (первые 500 символов)
                preview = text[:500] + "..." if len(text) > 500 else text
                
                await processing_msg.edit_text(
                    f"✅ Голосовое сообщение распознано!\n\n"
                    f"📊 Статистика:\n"
                    f"• Символов: {chars:,}\n"
                    f"• Слов: {words:,}\n"
                    f"• Строк: {lines:,}\n"
                    f"• Длительность: {duration} сек\n\n"
                    f"Текст (превью):\n{preview}"
                )
    
                # Добавить лог
                activity_logger.log(user_id, "VOICE_TRANSCRIPT", f"duration={duration}s,words={words},chars={len(text)}" )
                
                # Отправляем файл с транскрипцией
                await message.reply_document(
                    types.BufferedInputFile(
                        text.encode('utf-8'),
                        text_filename
                    ),
                    caption=f"📝 Транскрипция голосового сообщения\n📊 {words:,} слов, {lines:,} строк"
                )
                
                # Предлагаем сохранить транскрипцию в кодовую базу
                await self._offer_audio_save(
                    message, text_filename, text.encode('utf-8'), 
                    user_id, user_codebases["active"]
                )
                
            else:
                await processing_msg.edit_text(
                    "❌ Не удалось распознать голосовое сообщение.\n"
                    "Попробуйте записать еще раз с лучшим качеством."
                )
                
        except Exception as e:
            logger.error(f"Ошибка обработки голосового сообщения: {e}")
            await processing_msg.edit_text(f"❌ Ошибка обработки: {str(e)}")

    async def handle_audio(self, message: types.Message, state: FSMContext):
        """Обработка аудио файлов (не голосовых сообщений)"""
        user_id = str(message.from_user.id)
        
        # Проверяем доступ
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту.")
            return
        
        # Проверяем наличие активной кодовой базы
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if not user_codebases["active"]:
            await message.reply(
                "❌ Нет активной кодовой базы.\n"
                "Создайте или выберите кодовую базу для загрузки файлов.\n"
                "/create_codebase - создать новую\n"
                "/codebases - список баз"
            )
            return
        
        # Проверяем наличие аудио конвертера
        if not self.audio_converter:
            await message.reply(
                "❌ Распознавание аудио недоступно.\n"
                "Не настроен OpenAI API ключ."
            )
            return
        
        audio = message.audio
        if not audio:
            return
        
        # Получаем информацию о файле
        duration = audio.duration
        file_size = audio.file_size
        filename = audio.file_name or f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        performer = audio.performer or "Unknown"
        title = audio.title or "Untitled"
        
        # Проверяем размер файла - это критически важно!
        if file_size > self.TELEGRAM_BOT_FILE_LIMIT:
            # Генерируем подробную инструкцию по сжатию
            compression_tips = self._get_audio_compression_tips(file_size, duration)
            
            await message.reply(
                f"❌ **Файл слишком большой для обработки через Telegram Bot API**\n\n"
                f"📄 Файл: {title} - {performer}\n"
                f"📊 Размер: {self.file_manager.format_size(file_size)}\n"
                f"⏱️ Длительность: {self._format_duration(duration)}\n"
                f"🚫 Максимум для ботов: {self.file_manager.format_size(self.TELEGRAM_BOT_FILE_LIMIT)}\n\n"
                f"{compression_tips}",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            
            # Логируем для статистики
            logger.info(f"User {user_id} tried to upload large audio: {file_size} bytes, {duration}s")
            return
        
        # Информационное сообщение
        processing_msg = await message.reply(
            f"🎵 Обрабатываю аудио файл...\n"
            f"📝 Название: {title}\n"
            f"🎤 Исполнитель: {performer}\n"
            f"⏱️ Длительность: {self._format_duration(duration)}\n"
            f"📊 Размер: {self.file_manager.format_size(file_size)}\n"
            f"📄 Файл: {filename}"
        )
        
        try:
            # Загружаем файл
            tg_file = await self.bot.get_file(audio.file_id)
            stream = await self.bot.download_file(tg_file.file_path)
            audio_bytes = stream.getvalue() if hasattr(stream, "getvalue") else stream
            
            # Проверяем формат
            if not self.audio_converter.supports(filename):
                ext = os.path.splitext(filename.lower())[1]
                await processing_msg.edit_text(
                    f"❌ Формат {ext} не поддерживается для распознавания.\n\n"
                    f"Поддерживаемые форматы:\n"
                    f"{', '.join(sorted(self.audio_converter.SUPPORTED_FORMATS))}\n\n"
                    f"Файл будет сохранен без распознавания."
                )
                
                # Сохраняем только оригинальный файл
                await self._save_audio_original_only(
                    message, processing_msg, filename, audio_bytes, 
                    user_id, user_codebases["active"]
                )
                return
            
            # Обновляем сообщение
            await processing_msg.edit_text(
                f"🎤 Распознаю аудио...\n"
                f"📝 {title} - {performer}\n"
                f"⏱️ Длительность: {self._format_duration(duration)}\n"
                f"⏳ Это может занять несколько минут..."
            )
            
            async def update_progress(text: str):
                try:
                    await processing_msg.edit_text(
                        f"🎵 {title} - {performer}\n"
                        f"⏱️ {self._format_duration(duration)}\n\n"
                        f"{text}"
                    )
                except Exception as e:
                    logger.warning(f"Не удалось обновить прогресс: {e}")
            
            # Распознаем аудио
            success, text_filename, text = await self.audio_converter.convert_to_text(
                audio_bytes,
                filename,
                progress_callback=update_progress
            )
            
            if success and text:
                # Форматируем текст
                text = self._format_transcript_text(text)
                
                # Добавляем метаданные в начало транскрипции
                metadata = (
                    f"# Транскрипция аудио файла\n\n"
                    f"Файл: {filename}\n"
                    f"Название: {title}\n"
                    f"Исполнитель: {performer}\n"
                    f"Длительность: {self._format_duration(duration)}\n"
                    f"Дата распознавания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"---\n\n"
                )
                
                full_text = metadata + text
                
                # Подсчитываем статистику
                words = len(text.split())
                lines = len(text.split('\n'))
                
                # Показываем превью текста
                preview = text[:800] + "..." if len(text) > 800 else text
                
                await processing_msg.edit_text(
                    f"✅ Аудио успешно распознано!\n\n"
                    f"🎵 {title} - {performer}\n"
                    f"⏱️ Длительность: {self._format_duration(duration)}\n\n"
                    f"📊 Статистика транскрипции:\n"
                    f"• Символов: {len(text):,}\n"
                    f"• Слов: {words:,}\n"
                    f"• Строк: {lines:,}\n\n"
                    f"Распознанный текст (превью):\n"
                    f"```\n{preview}\n```"
                )
                
                # Отправляем файл с полной транскрипцией
                base, _ = os.path.splitext(filename)
                text_filename = f"{base}_transcript.txt"
                
                await message.reply_document(
                    types.BufferedInputFile(
                        full_text.encode('utf-8'),
                        text_filename
                    ),
                    caption=(
                        f"📝 Полная транскрипция аудио\n"
                        f"🎵 {title} - {performer}\n"
                        f"📊 {words:,} слов, {lines:,} строк"
                    )
                )

                # Добавить лог
                activity_logger.log(user_id, "AUDIO_TRANSCRIPT", f"duration={duration}s,words={words},chars={len(text)}" )

                # Сохраняем для макро-команд
                if hasattr(self.handler, 'agent_handler') and self.handler.agent_handler:
                    self.handler.agent_handler.save_md_file_for_macros(
                        user_id, text_filename, full_text, filename
                    )
                
                # Предлагаем сохранить в кодовую базу
                await self._offer_audio_save(
                    message, text_filename, 
                    full_text.encode('utf-8'), 
                    user_id, user_codebases["active"]
                )
                
            else:
                # Распознавание не удалось
                await processing_msg.edit_text(
                    f"⚠️ Не удалось распознать речь в аудио файле.\n\n"
                    f"Возможные причины:\n"
                    f"• Файл не содержит речи (только музыка)\n"
                    f"• Плохое качество записи\n"
                    f"• Неподдерживаемый язык\n\n"
                    f"Сохраняю только оригинальный файл..."
                )
                
                # Сохраняем только оригинал
                await self._save_audio_original_only(
                    message, processing_msg, filename, audio_bytes,
                    user_id, user_codebases["active"]
                )
                
        except Exception as e:
            logger.error(f"Ошибка обработки аудио файла: {e}", exc_info=True)
            
            # Проверяем, связана ли ошибка с размером файла
            error_msg = str(e).lower()
            if "file is too big" in error_msg or "file_too_big" in error_msg:
                # Это не должно происходить, так как мы проверяем размер заранее,
                # но на всякий случай обрабатываем
                compression_tips = self._get_audio_compression_tips(file_size, duration)
                
                await processing_msg.edit_text(
                    f"❌ **Ошибка загрузки файла**\n\n"
                    f"Telegram API не позволяет ботам загружать файлы больше 20 MB.\n\n"
                    f"{compression_tips}",
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            else:
                await processing_msg.edit_text(
                    f"❌ Ошибка обработки аудио: {str(e)}\n\n"
                    f"Попробуйте еще раз или обратитесь к администратору."
                )

    async def process_audio_file(self, message, processing_msg, orig_name, file_bytes, 
                                user_id, codebase_id, state):
        """Обработка аудио файлов из документов"""
        file_size = len(file_bytes)
        
        await processing_msg.edit_text(
            f"🎵 Обнаружен аудио файл: {orig_name}\n"
            f"📊 Размер: {self.file_manager.format_size(file_size)}\n"
            f"⏳ Начинаю распознавание речи..."
        )
        
        async def update_progress(text: str):
            try:
                await processing_msg.edit_text(text)
            except Exception as e:
                logger.warning(f"Не удалось обновить прогресс: {e}")
        
        # Распознаем аудио
        success, text_filename, text = await self.audio_converter.convert_to_text(
            file_bytes,
            orig_name,
            progress_callback=update_progress
        )
        
        if success and text:
            # НЕ Сохраняем! оригинальный аудио файл
            #await self.file_manager.save_file(
            #    user_id, codebase_id, orig_name, file_bytes,
            #    skip_conversion=True
            #)
            
            # Сохраняем транскрипцию
            save_success, save_msg, _ = await self.file_manager.save_file(
                user_id, codebase_id, text_filename,
                text.encode('utf-8'), encoding='utf-8'
            )
            
            if save_success:
                config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
                
                # Показываем превью текста
                preview = text[:800] + "..." if len(text) > 800 else text
                
                await processing_msg.edit_text(
                    f"✅ Аудио успешно распознано!\n\n"
                    f"🎵 Оригинал: {orig_name}\n"
                    f"📝 Транскрипция: {text_filename}\n"
                    f"📚 Кодовая база: {config['name']}\n"
                    f"📊 Символов: {len(text)}\n\n"
                    f"Распознанный текст:\n{preview}"
                )
                
                # Отправляем файл с транскрипцией пользователю
                await message.reply_document(
                    types.BufferedInputFile(
                        text.encode('utf-8'),
                        text_filename
                    ),
                    caption=f"📝 Транскрипция аудио файла"
                )
            else:
                await processing_msg.edit_text(f"❌ Ошибка сохранения транскрипции: {save_msg}")
        else:
            await processing_msg.edit_text(
                f"❌ Не удалось распознать аудио файл.\n"
                f"Файл: {orig_name}\n\n"
                f"Убедитесь, что файл содержит речь и не поврежден."
            )

    async def _offer_audio_save(self, message, text_filename, text_bytes, user_id, codebase_id):
        """Предлагает сохранить транскрипцию в кодовую базу"""
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        
        # Проверяем существование файла
        text_exists = await self.file_manager.file_exists(user_id, codebase_id, text_filename)
        
        # Сохраняем данные для последующего сохранения
        token = secrets.token_urlsafe(8)
        if user_id not in self.handler.pending_files:
            self.handler.pending_files[user_id] = []
        
        self.handler.pending_files[user_id].append({
            "kind": "audio_save",
            "token": token,
            "text_filename": text_filename,
            "text_data": text_bytes,
            "codebase_id": codebase_id
        })
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💾 Сохранить транскрипцию", 
                callback_data=f"save_audio:{token}:save"
            )],
            [InlineKeyboardButton(
                text="❌ Не сохранять", 
                callback_data=f"save_audio:{token}:skip"
            )]
        ])
        
        msg = f"💡 Сохранить транскрипцию в кодовую базу {config['name']}?"
        if text_exists:
            msg += f"\n⚠️ Файл '{text_filename}' уже существует и будет перезаписан"
        
        await message.reply(msg, reply_markup=keyboard)

    async def _save_audio_original_only(self, message, processing_msg, 
                                       filename, audio_bytes, user_id, codebase_id):
        """Сохраняет только оригинальный аудио файл"""
        success, msg, _ = await self.file_manager.save_file(
            user_id, codebase_id, filename, audio_bytes,
            skip_conversion=True
        )
        
        if success:
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            await processing_msg.edit_text(
                f"✅ Аудио файл сохранен!\n"
                f"📚 Кодовая база: {config['name']}\n"
                f"📄 Файл: {filename}\n"
                f"📊 {msg}"
            )
        else:
            await processing_msg.edit_text(f"❌ Ошибка сохранения: {msg}")