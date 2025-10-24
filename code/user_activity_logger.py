import os
import asyncio
import aiofiles
from datetime import datetime
from typing import Optional, Dict, Any
import logging

# Setup standard logger for internal errors
logger = logging.getLogger(__name__)

class UserActivityLogger:
    def __init__(self, log_file: str = "user_activity.log"):
        self.log_file = log_file
        self._queue = asyncio.Queue()
        self._writer_task = None
        
    async def start(self):
        """Запустить фоновую запись логов"""
        self._writer_task = asyncio.create_task(self._writer())
    
    async def stop(self):
        """Остановить логгер"""
        if self._writer_task:
            self._writer_task.cancel()
    
    async def _writer(self):
        """Фоновый процесс записи логов"""
        while True:
            try:
                log_entry = await self._queue.get()
                async with aiofiles.open(self.log_file, 'a', encoding='utf-8') as f:
                    await f.write(log_entry + '\n')
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in log writer: {e}", exc_info=True)
                await asyncio.sleep(1)  # Avoid tight error loop
    
    def log(self, user_id: str, operation: str, details: str = ""):
        """Добавить запись в лог"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{user_id}|{timestamp}|{operation}|{details}"
        asyncio.create_task(self._queue.put(log_entry))
    
    def log_ai_request(self, user_id: str, provider: str, model: str, 
                      input_tokens: int, output_tokens: int, duration: float):
        """Логировать AI запрос"""
        details = f"provider={provider},model={model},in_tokens={input_tokens},out_tokens={output_tokens},duration={duration:.2f}s"
        self.log(user_id, "AI_REQUEST", details)

# Глобальный экземпляр логгера
activity_logger = UserActivityLogger()