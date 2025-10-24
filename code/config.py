# code/config.py
import json
import os
from typing import Dict, Any, Optional, Set


class Config:
    """Класс для работы с конфигурацией"""
    
    _config: Optional[Dict[str, Any]] = None
    _config_path = "config.json"
    
    # Поддерживаемые текстовые форматы
    TEXT_FILE_EXTENSIONS: Set[str] = {
        # Программирование
        ".py", ".js", ".ts", ".tsx", ".jsx",
        ".java", ".kt", ".go", ".rs", 
        ".c", ".cpp", ".h", ".hpp", ".cc", ".cxx",
        ".cs", ".vb", ".fs",
        ".php", ".rb", ".swift", ".scala",
        ".lua", ".pl", ".r", ".m", ".mm",
        ".dart", ".kotlin", ".groovy", ".clj",
        ".elm", ".erl", ".ex", ".exs", ".hrl",
        ".hs", ".lhs", ".ml", ".mli",
        ".nim", ".v", ".zig",
        
        # Веб-разработка
        ".html", ".htm", ".xhtml", ".xml",
        ".css", ".scss", ".sass", ".less",
        ".vue", ".svelte",
        
        # Разметка и документация
        ".md", ".markdown", ".rst", ".adoc", ".tex",
        
        # Конфигурация
        ".json", ".yml", ".yaml", ".toml", ".ini", 
        ".cfg", ".conf", ".config", ".env",
        ".properties", ".prop",
        
        # Скрипты
        ".sh", ".bash", ".zsh", ".fish",
        ".bat", ".cmd", ".ps1", ".psm1",
        
        # Базы данных
        ".sql", ".psql", ".mysql",
        
        # Данные
        ".csv", ".tsv", ".txt", ".log",
        
        # Другое
        ".dockerfile", ".gitignore", ".editorconfig",
        ".makefile", ".cmake", ".gradle"
    }
    
    @classmethod
    def load_config(cls) -> Dict[str, Any]:
        """Загружает конфигурацию из файла"""
        if cls._config is None:
            with open(cls._config_path, "r", encoding="utf-8") as f:
                cls._config = json.load(f)
        return cls._config
    
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Получает значение из конфига по ключу"""
        config = cls.load_config()
        return config.get(key, default)
    
    @classmethod
    def is_text_file(cls, filename: str) -> bool:
        """
        Проверяет, является ли файл текстовым по его расширению
        
        Args:
            filename: Имя файла для проверки
            
        Returns:
            True если файл текстовый, False если бинарный
        """
        _, ext = os.path.splitext(filename.lower())
        return ext in cls.TEXT_FILE_EXTENSIONS
    
    @classmethod
    def get_text_extensions(cls) -> Set[str]:
        """
        Возвращает множество всех поддерживаемых текстовых расширений
        
        Returns:
            Множество расширений текстовых файлов
        """
        return cls.TEXT_FILE_EXTENSIONS.copy()
    
    @classmethod
    def add_text_extension(cls, extension: str) -> None:
        """
        Добавляет новое расширение в список текстовых файлов
        
        Args:
            extension: Расширение файла (должно начинаться с точки)
        """
        if not extension.startswith('.'):
            extension = '.' + extension
        cls.TEXT_FILE_EXTENSIONS.add(extension.lower())
    
    @classmethod
    def remove_text_extension(cls, extension: str) -> None:
        """
        Удаляет расширение из списка текстовых файлов
        
        Args:
            extension: Расширение файла для удаления
        """
        if not extension.startswith('.'):
            extension = '.' + extension
        cls.TEXT_FILE_EXTENSIONS.discard(extension.lower())
    
    @classmethod
    def format_file_size(cls, size: int) -> str:
        """
        Форматирует размер файла в читаемый вид
        
        Args:
            size: Размер файла в байтах
            
        Returns:
            Отформатированная строка с размером
        """
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                if unit == 'B':
                    return f"{size} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    
    # Основные параметры
    @property
    def BOT_NAME(cls) -> str:
        return cls.get("bot_name", "ИИ Бот")
    
    @property
    def BOT_TOKEN(cls) -> str:
        return cls.get("bot_token", "")
    
    @property
    def OPENAI_API_KEY(cls) -> str:
        return cls.get("openai_api_key", "")
    
    @property
    def ANTHROPIC_API_KEY(cls) -> str:
        return cls.get("anthropic_api_key", "")
    
    @property
    def DATA_DIR(cls) -> str:
        return cls.get("data_dir", "bot_data")
    
    @property
    def USERS_DIR(cls) -> str:
        return cls.get("users_dir", "bot_users")
    
    @property
    def AI_MODELS(cls) -> Dict[str, Any]:
        return cls.get("ai_models", {})
    
    @property
    def AI_PROVIDERS(cls) -> Dict[str, Any]:
        return cls.get("ai_providers", {})
    
    @property
    def LOG_LEVEL(cls) -> str:
        return cls.get("log_level", "INFO") # "DEBUG"
    
    @property
    def LOG_FILE(cls) -> str:
        return cls.get("log_file", "bot.log")

    @property
    def EMAIL_SETTINGS(cls) -> Dict[str, Any]:
        return cls.get("email_settings", {})

    @property
    def EMAIL_ENABLED(cls) -> bool:
        return cls.EMAIL_SETTINGS.get("enabled", False)

    @property
    def SMTP_EMAIL(cls) -> str:
        return cls.EMAIL_SETTINGS.get("email", "")

    @property
    def SMTP_PASSWORD(cls) -> str:
        return cls.EMAIL_SETTINGS.get("password", "")

    @property
    def SMTP_SERVER(cls) -> str:
        return cls.EMAIL_SETTINGS.get("smtp_server", "")

    @property
    def SMTP_PORT(cls) -> int:
        return cls.EMAIL_SETTINGS.get("smtp_port", 465)

    @property
    def SMTP_USE_SSL(cls) -> bool:
        return cls.EMAIL_SETTINGS.get("smtp_use_ssl", True)

    @property
    def SMTP_VERIFY_SSL(cls) -> bool:
        return cls.EMAIL_SETTINGS.get("smtp_verify_ssl", True)

    @property
    def EMAIL_FROM_NAME(cls) -> str:
        return cls.EMAIL_SETTINGS.get("from_name", "AI Bot")
    
    @property
    def AGENT_LOGGING(cls) -> Dict[str, Any]:
        """Настройки логирования для системы агентов"""
        return cls.get("agent_logging", {
            "main_log": True,      # Основное логирование в bot.log
            "rag_log": True,       # Детальный лог в rag_requests.log
            "json_log": True,      # JSON логи в rag_logs/
            "log_request": True,   # Логировать запросы
            "log_context": True,   # Логировать контекст RAG
            "log_response": True,  # Логировать ответы ИИ
            "max_log_length": 500  # Максимальная длина логируемых строк
        })

    @property
    def AI_LOG_FILE(cls) -> str:
        """Файл для полного логирования запросов к ИИ"""
        return cls.get("ai_log_file", "ai_requests_full.log")
    
    @property
    def AI_LOG_ENABLED(cls) -> bool:
        """Включено ли логирование запросов к ИИ"""
        return cls.get("ai_log_enabled", True)

# Инициализация при импорте
Config = Config()