# code/converters/encoding_converter.py
"""
Модуль для работы с кодировками файлов
"""
import logging
import chardet
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class EncodingConverter:
    """Конвертер кодировок текстовых файлов"""
    
    # Приоритетные кодировки для определения (приоритет кириллице)
    COMMON_ENCODINGS = [
        'utf-8', 'cp1251', 'cp866', 'koi8-r', 'iso-8859-5',
        'latin-1', 'ascii', 'utf-16', 'utf-32'
    ]
    
    # Маппинг названий кодировок
    ENCODING_MAP = {
        'windows-1251': 'cp1251',
        'IBM866': 'cp866',
        'ISO-8859-5': 'iso-8859-5',
        'KOI8-R': 'koi8-r'
    }
    
    async def detect_encoding(self, file_data: bytes) -> Tuple[str, float]:
        """
        Определяет кодировку файла
        Returns: (encoding, confidence)
        """
        try:
            result = chardet.detect(file_data)
            encoding = result.get('encoding', 'utf-8')
            confidence = result.get('confidence', 0.0)
            
            if encoding:
                encoding = self.ENCODING_MAP.get(encoding, encoding)
            
            return encoding or 'utf-8', confidence
            
        except Exception as e:
            logger.error(f"Ошибка определения кодировки: {e}")
            return 'utf-8', 0.0
    
    async def convert_to_utf8(self, file_data: bytes, source_encoding: str) -> str:
        """Конвертирует данные файла в UTF-8"""
        try:
            text = file_data.decode(source_encoding, errors='replace')
            text = self._normalize_text(text)
            return text
        except Exception as e:
            logger.error(f"Ошибка конвертации из {source_encoding}: {e}")
            try:
                text = file_data.decode(source_encoding, errors='ignore')
                return self._normalize_text(text)
            except:
                return file_data.decode('latin-1', errors='replace')
    
    def _normalize_text(self, text: str) -> str:
        """Нормализация текста"""
        # Убираем BOM если есть
        if text and text[0] == "\ufeff":
            text = text[1:]
        # Нормализуем переносы строк
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text
    
    def needs_conversion(self, encoding: str, confidence: float) -> bool:
        """Проверяет, нужна ли конвертация"""
        return encoding.lower() != "utf-8" or confidence < 0.9