# code/converters/base_converter.py
"""
Базовые классы и интерфейсы для конвертеров файлов
"""
import logging
from typing import Tuple, Optional, Protocol
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class FileConverter(ABC):
    """Базовый класс для конвертеров файлов"""
    
    @abstractmethod
    async def convert(self, file_bytes: bytes, filename: str, **kwargs) -> Tuple[bool, str, str]:
        """
        Конвертирует файл
        Returns: (success, new_filename, converted_content)
        """
        pass
    
    @abstractmethod
    def supports(self, filename: str) -> bool:
        """Проверяет, поддерживает ли конвертер данный файл"""
        pass


class ProgressCallback(Protocol):
    """Протокол для callback функции прогресса"""
    async def __call__(self, text: str) -> None: ...


class CancelCheck(Protocol):
    """Протокол для функции проверки отмены"""
    async def __call__(self) -> bool: ...