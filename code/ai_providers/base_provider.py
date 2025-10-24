# code/ai_providers/base_provider.py
"""
Базовый класс для AI провайдеров
"""

import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from abc import ABC, abstractmethod

from user_activity_logger import activity_logger


logger = logging.getLogger(__name__)


class BaseAIProvider(ABC):
    """Базовый класс для всех AI провайдеров"""
    
    def __init__(self, api_key: str, models_config: Dict[str, Any], providers_config: Dict[str, Any], ai_logger=None):
        self.api_key = api_key
        self.models_config = models_config
        self.providers_config = providers_config
        self.ai_logger = ai_logger
    
    @abstractmethod
    async def send_request(
        self,
        user_id: str,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        **kwargs
    ) -> Optional[str]:
        """Отправка запроса к API провайдера"""
        pass
    
    @abstractmethod
    def get_default_model(self) -> str:
        """Получение модели по умолчанию"""
        pass
    
    def log_ai_request(
        self,
        user_id: str,
        provider: str,
        model: str,
        request_data: Dict[str, Any],
        response_data: Any,
        response_time: float,
        status_code: int = 200,
        error: str = None
    ):
        """Логирование полного запроса и ответа ИИ"""
        if not self.ai_logger:
            return
        
        try:
            input_tokens = 0
            output_tokens = 0
            
            # Обработка различных форматов ответов
            if response_data and isinstance(response_data, dict):
                usage = response_data.get('usage', {})
                
                if provider == "openai":
                    # Проверяем разные форматы токенов для OpenAI
                    if 'input_tokens' in usage and 'output_tokens' in usage:
                        # Новый формат (GPT-5-Codex)
                        input_tokens = usage.get('input_tokens', 0)
                        output_tokens = usage.get('output_tokens', 0)
                    elif 'prompt_tokens' in usage and 'completion_tokens' in usage:
                        # Старый формат (GPT-4, GPT-3.5)
                        input_tokens = usage.get('prompt_tokens', 0)
                        output_tokens = usage.get('completion_tokens', 0)
                    elif 'total_tokens' in usage:
                        # Fallback: если есть только total_tokens
                        total = usage.get('total_tokens', 0)
                        # Примерная оценка: 30% input, 70% output
                        input_tokens = int(total * 0.3)
                        output_tokens = int(total * 0.7)
                    
                elif provider == "anthropic":
                    input_tokens = usage.get('input_tokens', 0)
                    output_tokens = usage.get('output_tokens', 0)
            
            # Логируем активность пользователя
            if input_tokens > 0 or output_tokens > 0:
                activity_logger.log_ai_request(
                    user_id=user_id,
                    provider=provider,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration=response_time
                )
            else:
                logger.warning(f"Не удалось извлечь данные о токенах для {provider}/{model}")

            return

            # Старый код логирования (отключен)
            log_entry = "="*80 + "\n"
            log_entry += f"ЗАПРОС К ИИ\n"
            log_entry += f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}\n"
            log_entry += f"Провайдер: {provider.upper()}\n"
            log_entry += f"Модель: {model}\n"
            log_entry += f"Время ответа: {response_time:.3f} сек\n"
            log_entry += f"Статус: {'SUCCESS' if status_code == 200 else f'ERROR {status_code}'}\n"
            
            if error:
                log_entry += f"Ошибка: {error}\n"
            
            log_entry += "\n" + "-"*40 + " ЗАПРОС " + "-"*40 + "\n"
            log_entry += json.dumps(request_data, ensure_ascii=False, indent=2)
            
            log_entry += "\n\n" + "-"*40 + " ОТВЕТ " + "-"*40 + "\n"
            
            if response_data:
                if isinstance(response_data, (dict, list)):
                    log_entry += json.dumps(response_data, ensure_ascii=False, indent=2)
                else:
                    log_entry += str(response_data)
            else:
                log_entry += "[Пустой ответ]"
            
            log_entry += "\n" + "="*80 + "\n\n"
            
            self.ai_logger.info(log_entry)
            
        except Exception as e:
            logger.error(f"Ошибка логирования AI запроса: {e}", exc_info=True)
    
    @staticmethod
    def strip_disabled_keys(d: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Возвращает копию без ключей, начинающихся с '_'."""
        if not d:
            return {}
        return {k: v for k, v in d.items() if not (isinstance(k, str) and k.startswith("_"))}
    
    def active_model_params(
        self,
        provider: str,
        model: str,
        allowed_keys: List[str],
        overrides: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Сливает параметры в порядке приоритета:
        1) overrides (kwargs при вызове)
        2) НЕподчёркнутые поля конкретной модели из ai_providers
        3) НЕподчёркнутые поля провайдера из ai_models
        """
        model_cfg = self.strip_disabled_keys(self.get_model_config(provider, model))
        provider_defaults = self.strip_disabled_keys(self.models_config.get(provider, {}))
        
        out: Dict[str, Any] = {}
        for key in allowed_keys:
            if key in overrides and overrides[key] is not None and overrides[key] != -1:
                out[key] = overrides[key]
                continue
            if key in model_cfg and model_cfg[key] is not None and model_cfg[key] != -1:
                out[key] = model_cfg[key]
                continue
            if key in provider_defaults and provider_defaults[key] is not None and provider_defaults[key] != -1:
                out[key] = provider_defaults[key]
        return out
    
    def get_model_config(self, provider: str, model: str) -> Dict[str, Any]:
        """Получение конфигурации модели"""
        provider_config = self.providers_config.get(provider, {})
        models_config = provider_config.get("models", {})
        return models_config.get(model, {})
    
    def detect_image_mime_type(self, image_bytes: bytes) -> str:
        """Определяет MIME-тип изображения по сигнатуре"""
        if image_bytes[:4] == b'\x89PNG':
            return "image/png"
        elif image_bytes[:2] == b'\xff\xd8':
            return "image/jpeg"
        elif image_bytes[:4] == b'GIF8':
            return "image/gif"
        elif image_bytes[:2] == b'BM':
            return "image/bmp"
        elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
            return "image/webp"
        elif image_bytes[:4] in (b'II\x2a\x00', b'MM\x00\x2a'):
            return "image/tiff"
        else:
            return "image/png"