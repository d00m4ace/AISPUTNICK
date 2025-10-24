# code/converters/audio_converter.py
"""
Конвертер аудио файлов в текст через OpenAI Whisper API
"""
import os
import logging
import tempfile
from typing import Tuple, Optional, BinaryIO
from pathlib import Path
import aiohttp
import asyncio

logger = logging.getLogger(__name__)


class AudioConverter:
    """Конвертер аудио в текст через Whisper API"""
    
    # Поддерживаемые форматы согласно документации OpenAI
    SUPPORTED_FORMATS = {
        '.mp3', '.mp4', '.mpeg', '.mpga', '.m4a', '.wav', 
        '.webm', '.ogg', '.oga', '.opus', '.flac'
    }
    
    # Максимальный размер файла для Whisper API - 25MB
    MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
    
    # Размер чанка для больших файлов (10 минут аудио ≈ 10MB)
    CHUNK_SIZE = 10 * 1024 * 1024  # 10MB
    
    def __init__(self, openai_api_key: str):
        self.api_key = openai_api_key
        self.api_url = "https://api.openai.com/v1/audio/transcriptions"
    
    def supports(self, filename: str) -> bool:
        """Проверяет, поддерживается ли формат файла"""
        ext = os.path.splitext(filename.lower())[1]
        return ext in self.SUPPORTED_FORMATS
    
    async def convert_to_text(
        self, 
        audio_bytes: bytes, 
        filename: str,
        language: Optional[str] = None,
        progress_callback: Optional[callable] = None
    ) -> Tuple[bool, str, str]:
        """
        Конвертирует аудио в текст
        Returns: (success, new_filename, transcribed_text)
        """
        base, ext = os.path.splitext(filename)
        new_name = f"{base}_transcript.txt"
        
        try:
            # Проверяем размер
            file_size = len(audio_bytes)
            
            if file_size > self.MAX_FILE_SIZE:
                # Для больших файлов используем разбиение
                if progress_callback:
                    await progress_callback(
                        f"📊 Большой файл ({self._format_size(file_size)})\n"
                        "Обработка по частям..."
                    )
                
                text = await self._process_large_audio(
                    audio_bytes, filename, language, progress_callback
                )
            else:
                # Обычная обработка для небольших файлов
                if progress_callback:
                    await progress_callback(
                        f"🎤 Распознаю аудио ({self._format_size(file_size)})..."
                    )
                
                text = await self._transcribe_audio(
                    audio_bytes, filename, language
                )
            
            if text:
                logger.info(f"Аудио успешно распознано: {filename}")
                return True, new_name, text
            else:
                logger.warning(f"Получен пустой результат для {filename}")
                return False, new_name, ""
                
        except Exception as e:
            logger.error(f"Ошибка распознавания аудио: {e}")
            return False, new_name, ""
    
    async def _transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        language: Optional[str] = None
    ) -> str:
        """Отправляет аудио на распознавание в Whisper API"""
        try:
            # Определяем расширение для правильного MIME типа
            ext = os.path.splitext(filename.lower())[1]
            
            # Формируем multipart/form-data
            data = aiohttp.FormData()
            data.add_field(
                'file',
                audio_bytes,
                filename=filename,
                content_type=self._get_mime_type(ext)
            )
            data.add_field('model', 'whisper-1')
            
            # Добавляем язык если указан
            if language:
                data.add_field('language', language)
            
            # Добавляем prompt для улучшения качества
            data.add_field(
                'prompt',
                'Точная транскрипция. Сохраняй пунктуацию и форматирование.'
            )
            
            # Формат ответа
            data.add_field('response_format', 'text')
            
            headers = {
                'Authorization': f'Bearer {self.api_key}'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    headers=headers,
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=300)  # 5 минут таймаут
                ) as response:
                    if response.status == 200:
                        text = await response.text()
                        return text.strip()
                    else:
                        error_text = await response.text()
                        logger.error(f"Whisper API error {response.status}: {error_text}")
                        return ""
                        
        except asyncio.TimeoutError:
            logger.error("Таймаут при распознавании аудио")
            return ""
        except Exception as e:
            logger.error(f"Ошибка при вызове Whisper API: {e}")
            return ""
    
    async def _process_large_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        language: Optional[str],
        progress_callback: Optional[callable]
    ) -> str:
        """
        Обработка больших аудио файлов
        Для корректной работы требуется ffmpeg
        """
        try:
            import subprocess
            import shutil
            
            # Проверяем наличие ffmpeg
            if not shutil.which("ffmpeg"):
                logger.error("ffmpeg не установлен, невозможно обработать большой файл")
                if progress_callback:
                    await progress_callback(
                        "❌ Для обработки больших файлов требуется ffmpeg\n"
                        "Установите: apt-get install ffmpeg"
                    )
                return ""
            
            ext = os.path.splitext(filename.lower())[1]
            transcripts = []
            
            with tempfile.TemporaryDirectory() as temp_dir:
                # Сохраняем исходный файл
                input_path = os.path.join(temp_dir, f"input{ext}")
                with open(input_path, 'wb') as f:
                    f.write(audio_bytes)
                
                # Получаем длительность
                duration = await self._get_audio_duration(input_path)
                if duration <= 0:
                    logger.error("Не удалось определить длительность аудио")
                    return ""
                
                # Разбиваем на части по 10 минут
                chunk_duration = 600  # 10 минут в секундах
                num_chunks = int((duration + chunk_duration - 1) / chunk_duration)
                
                if progress_callback:
                    await progress_callback(
                        f"📊 Длительность: {self._format_duration(duration)}\n"
                        f"🔪 Разбиение на {num_chunks} частей..."
                    )
                
                for i in range(num_chunks):
                    start_time = i * chunk_duration
                    chunk_path = os.path.join(temp_dir, f"chunk_{i}{ext}")
                    
                    # Вырезаем кусок с помощью ffmpeg
                    cmd = [
                        'ffmpeg', '-i', input_path,
                        '-ss', str(start_time),
                        '-t', str(chunk_duration),
                        '-c', 'copy',  # Без перекодирования
                        '-y',  # Перезаписывать
                        chunk_path
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True
                    )
                    
                    if result.returncode != 0:
                        logger.error(f"ffmpeg ошибка: {result.stderr}")
                        continue
                    
                    # Читаем chunk
                    with open(chunk_path, 'rb') as f:
                        chunk_bytes = f.read()
                    
                    if progress_callback:
                        await progress_callback(
                            f"🎤 Распознаю часть {i+1}/{num_chunks}\n"
                            f"⏱️ {self._format_duration(start_time)} - "
                            f"{self._format_duration(min(start_time + chunk_duration, duration))}"
                        )
                    
                    # Распознаем chunk
                    chunk_text = await self._transcribe_audio(
                        chunk_bytes,
                        f"chunk_{i}{ext}",
                        language
                    )
                    
                    if chunk_text:
                        transcripts.append(chunk_text)
                    
                    # Удаляем обработанный chunk для экономии места
                    try:
                        os.unlink(chunk_path)
                    except:
                        pass
                    
                    # Небольшая задержка между запросами
                    if i < num_chunks - 1:
                        await asyncio.sleep(1)
                
                if progress_callback:
                    await progress_callback(
                        f"✅ Распознано частей: {len(transcripts)}/{num_chunks}"
                    )
                
                # Объединяем результаты
                return "\n\n".join(transcripts)
                
        except Exception as e:
            logger.error(f"Ошибка обработки большого аудио: {e}")
            return ""
    
    async def _get_audio_duration(self, file_path: str) -> float:
        """Получает длительность аудио файла в секундах"""
        try:
            import subprocess
            import json
            
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                file_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                duration = float(data.get('format', {}).get('duration', 0))
                return duration
        except Exception as e:
            logger.error(f"Ошибка получения длительности: {e}")
        
        return 0
    
    def _get_mime_type(self, ext: str) -> str:
        """Возвращает MIME тип для расширения"""
        mime_types = {
            '.mp3': 'audio/mpeg',
            '.mp4': 'audio/mp4',
            '.mpeg': 'audio/mpeg',
            '.mpga': 'audio/mpeg',
            '.m4a': 'audio/m4a',
            '.wav': 'audio/wav',
            '.webm': 'audio/webm',
            '.ogg': 'audio/ogg',
            '.oga': 'audio/ogg',
            '.opus': 'audio/opus',
            '.flac': 'audio/flac'
        }
        return mime_types.get(ext, 'audio/mpeg')
    
    def _format_size(self, size: int) -> str:
        """Форматирует размер файла"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                if unit == 'B':
                    return f"{size} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    
    def _format_duration(self, seconds: float) -> str:
        """Форматирует длительность в читаемый вид"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"