# code/ai_interface.py
import base64
import logging
from typing import Dict, Any, Optional, List
from config import Config

from ai_providers.openai_provider import OpenAIProvider
from ai_providers.anthropic_provider import AnthropicProvider

logger = logging.getLogger(__name__)

# Создаем отдельный логгер для полных запросов к ИИ
ai_logger = None
if Config.AI_LOG_ENABLED:
    ai_logger = logging.getLogger('ai_requests')
    ai_handler = logging.FileHandler(Config.AI_LOG_FILE, encoding='utf-8')
    ai_handler.setFormatter(logging.Formatter('%(asctime)s\n%(message)s'))
    ai_logger.addHandler(ai_handler)
    ai_logger.setLevel(logging.INFO)
    ai_logger.propagate = False


class AIInterface:
    """
    Единая обёртка над OpenAI и Anthropic с минимальным телом запроса.
    Поддерживает работу с изображениями через vision модели.
    Использует официальные SDK для обоих провайдеров.
    """
    
    def __init__(self):
        self.models_config: Dict[str, Any] = Config.AI_MODELS
        self.providers_config: Dict[str, Any] = getattr(Config, "AI_PROVIDERS", {})
        
        # Инициализируем провайдеров
        self.openai_provider = OpenAIProvider(
            api_key=Config.OPENAI_API_KEY,
            models_config=self.models_config,
            providers_config=self.providers_config,
            ai_logger=ai_logger
        )
        
        self.anthropic_provider = AnthropicProvider(
            api_key=Config.ANTHROPIC_API_KEY,
            models_config=self.models_config,
            providers_config=self.providers_config,
            ai_logger=ai_logger
        )
        
        # Маппинг провайдеров
        self.providers = {
            "openai": self.openai_provider,
            "anthropic": self.anthropic_provider
        }
    
    # ------------------------- Public API -------------------------
    
    async def send_request(
        self,
        user_id: str,
        provider: str,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """
        Унифицированный метод для отправки запросов к ИИ
        
        Args:
            provider: имя провайдера ('openai' или 'anthropic')
            messages: список сообщений в формате OpenAI/Anthropic
            model: модель для использования (опционально)
            **kwargs: дополнительные параметры для API (temperature, max_tokens и т.д.)
            
        Returns:
            Текст ответа или None при ошибке
        """
        if provider not in self.providers:
            raise ValueError(f"Неподдерживаемый провайдер: {provider}")
        
        return await self.providers[provider].send_request(user_id, messages, model, **kwargs)
    
    async def send_simple_request(
        self,
        user_id: str,
        provider: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """
        Упрощённый метод для простых запросов
        
        Args:
            provider: имя провайдера
            prompt: пользовательский промпт
            system_prompt: системный промпт (опционально)
            model: модель для использования (опционально)
            **kwargs: дополнительные параметры API
            
        Returns:
            Текст ответа или None при ошибке
        """
        msgs: List[Dict[str, Any]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": prompt})
        return await self.send_request(user_id, provider, msgs, model, **kwargs)
    
    async def process_image(
        self,
        user_id: str,
        image_bytes: bytes,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None
    ) -> Optional[str]:
        """
        Обрабатывает изображение через vision модели
        
        Args:
            image_bytes: байты изображения
            prompt: промпт для обработки изображения
            model: модель для использования (опционально)
            provider: провайдер для использования (опционально)
            
        Returns:
            Текст ответа или None при ошибке
        """
        # Проверяем что prompt не пустой
        if not prompt or not prompt.strip():
            prompt = "Распознай и верни весь текст с этого изображения. Если текста нет, опиши что изображено."
        
        # Определяем провайдера
        if not provider:
            if self.has_api_key("openai"):
                provider = "openai"
            elif self.has_api_key("anthropic"):
                provider = "anthropic"
            else:
                logger.error("Нет доступных API ключей для обработки изображений")
                return None
        
        #provider = "anthropic"

        # Определяем модель для vision
        if not model:
            if provider == "openai":
                model = "gpt-4o"  # Мультимодальная модель
            elif provider == "anthropic":
                model = "claude-3-5-sonnet-20241022"
        
        # Кодируем изображение в base64
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # Определяем MIME-тип
        provider_obj = self.providers[provider]
        mime_type = provider_obj.detect_image_mime_type(image_bytes)
        
        # Формируем сообщение с изображением
        messages = provider_obj.prepare_image_message(prompt, image_base64, mime_type)
        
        # Отправляем запрос
        try:
            result = await self.send_request(
                user_id=user_id,
                provider=provider,
                messages=messages,
                model=model,
                max_tokens=4096,
                temperature=0.2
            )
            return result
        except Exception as e:
            logger.error(f"Ошибка обработки изображения: {e}")
            return None
    
    # ------------------------- Helpers & Metadata -------------------------
    
    def get_available_models(self, provider: str) -> List[str]:
        """Получает список доступных моделей провайдера"""
        provider_config = self.providers_config.get(provider, {})
        models_list = provider_config.get("models", {})
        return list(models_list.keys())
    
    def get_model_config(self, provider: str, model: str) -> Dict[str, Any]:
        """Получает конфигурацию модели"""
        provider_config = self.providers_config.get(provider, {})
        models_config = provider_config.get("models", {})
        return models_config.get(model, {})
    
    def get_model_info(self, provider: str, model: str) -> Dict[str, Any]:
        """Получает информацию о модели"""
        cfg = self.get_model_config(provider, model)
        if not cfg:
            return {
                "name": model,
                "description": "Модель без описания",
                "max_context": 4000,
                "category": "unknown",
            }
        
        def pick(key: str, default: Any) -> Any:
            if key in cfg:
                return cfg[key]
            if f"_{key}" in cfg:
                return cfg[f"_{key}"]
            return default
        
        return {
            "name": cfg.get("name", model),
            "description": cfg.get("description", "Нет описания"),
            "max_context": cfg.get("max_context", 4000),
            "category": cfg.get("category", "standard"),
            "max_tokens": pick("max_tokens", None),
            "temperature": pick("temperature", None),
        }
    
    def get_models_by_category(self, provider: str, category: Optional[str] = None) -> List[str]:
        """Получает модели по категории"""
        models = self.get_available_models(provider)
        if not category:
            return models
        out: List[str] = []
        for m in models:
            info = self.get_model_info(provider, m)
            if info.get("category") == category:
                out.append(m)
        return out
    
    def validate_provider(self, provider: str) -> bool:
        """Проверяет валидность провайдера"""
        return provider in self.providers_config
    
    def has_api_key(self, provider: str) -> bool:
        """Проверяет наличие API ключа"""
        if provider in self.providers:
            return bool(self.providers[provider].api_key)
        return False
    
    def get_provider_status(self) -> Dict[str, Dict[str, Any]]:
        """Получает статус всех провайдеров"""
        status: Dict[str, Dict[str, Any]] = {}
        for provider in self.providers_config.keys():
            models = self.get_available_models(provider)
            default_model = self.models_config.get(provider, {}).get(
                "default_model", models[0] if models else ""
            )
            status[provider] = {
                "available": self.has_api_key(provider),
                "models_count": len(models),
                "default_model": default_model,
                "categories": self._get_provider_categories(provider),
            }
        return status
    
    def _get_provider_categories(self, provider: str) -> Dict[str, int]:
        """Получает категории моделей провайдера"""
        categories: Dict[str, int] = {}
        for model in self.get_available_models(provider):
            cat = self.get_model_info(provider, model).get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        return categories