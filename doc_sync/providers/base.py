# doc_sync/providers/base.py
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple
from datetime import datetime
import hashlib

class DocumentProvider(ABC):
    """Базовый класс для всех провайдеров документов"""
    
    def __init__(self, auth_config: Dict):
        self.auth_config = auth_config
        self.setup_auth()
    
    @abstractmethod
    def setup_auth(self):
        """Настройка авторизации для провайдера"""
        pass
    
    @abstractmethod
    def fetch_content(self, url: str) -> Tuple[str, Dict]:
        """
        Получить содержимое документа
        Returns: (content_html, metadata)
        """
        pass
    
    @abstractmethod
    def check_for_updates(self, url: str, last_modified: Optional[datetime]) -> bool:
        """Проверить, был ли документ обновлен"""
        pass
    
    def generate_file_id(self, url: str) -> str:
        """Генерация уникального ID для файла"""
        return hashlib.md5(url.encode()).hexdigest()[:16]