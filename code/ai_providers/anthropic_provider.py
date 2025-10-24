# code/ai_providers/anthropic_provider.py
"""
Провайдер для работы с Anthropic API через официальный SDK
"""

import asyncio
import json
import base64
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam, ContentBlock
from .base_provider import BaseAIProvider

logger = logging.getLogger(__name__)

class AnthropicProvider(BaseAIProvider):
    """Провайдер для работы с Anthropic API через официальный SDK"""
    
    # Разрешённые опциональные ключи для Anthropic
    OPTIONAL_KEYS = [
        "temperature", "top_p", "top_k", "stop_sequences", "service_tier", "metadata"
    ]
    
    # Anthropic Messages API требует max_tokens
    DEFAULT_MAX_TOKENS = 20000
    
    # Таймаут по умолчанию (5 минут)
    DEFAULT_TIMEOUT = 300
    
    def __init__(self, api_key: str, models_config: Dict[str, Any], providers_config: Dict[str, Any], ai_logger=None):
        """
        Инициализация провайдера
        
        Args:
            api_key: API ключ
            models_config: конфигурация моделей
            providers_config: конфигурация провайдеров
            ai_logger: логгер для AI запросов
        """
        super().__init__(api_key, models_config, providers_config, ai_logger)
        
        # Инициализируем клиента напрямую без httpx
        if api_key:
            self.client = AsyncAnthropic(
                api_key=api_key,
                max_retries=2,  # Умеренное количество повторов
                timeout=float(self.DEFAULT_TIMEOUT)  # Базовый таймаут
            )
        else:
            self.client = None
    
    def get_default_model(self) -> str:
        """Получение модели по умолчанию"""
        return self.models_config.get("anthropic", {}).get(
            "default_model", "claude-3-5-sonnet-20241022"
        )
    
    async def send_request(
        self,
        user_id: str,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        **kwargs
    ) -> Optional[str]:
        """Отправляет запрос к Anthropic Messages API через официальный SDK"""
        if not self.client:
            raise ValueError("Anthropic API ключ не установлен")
        
        model = model or self.get_default_model()
        
        # Преобразуем формат сообщений
        anthropic_messages, system_message = self._convert_messages(messages)
        
        # Обязательный параметр max_tokens
        max_tokens = kwargs.get("max_tokens")
        if max_tokens is None:
            model_cfg_active = self.strip_disabled_keys(
                self.get_model_config("anthropic", model)
            )
            max_tokens = model_cfg_active.get("max_tokens", self.DEFAULT_MAX_TOKENS)
        
        # Подхватываем опциональные параметры
        extra = self.active_model_params(
            provider="anthropic",
            model=model,
            allowed_keys=self.OPTIONAL_KEYS,
            overrides=kwargs,
        )
        
        # Подготавливаем данные для логирования
        request_data = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": int(max_tokens),
        }
        if system_message:
            request_data["system"] = system_message
        if extra:
            request_data.update(extra)
        
        # Определяем таймаут
        request_timeout = float(timeout) if timeout else float(self.DEFAULT_TIMEOUT)
        
        start_time = datetime.now()
        error_msg = None
        
        logger.info(f"Отправка запроса к Anthropic API: модель={model}, таймаут={request_timeout}с")
        logger.debug(f"Сообщения: {anthropic_messages}")
        if system_message:
            logger.debug(f"Системное сообщение: {system_message[:100]}...")
        
        try:
            # Подготавливаем параметры для SDK
            create_params = {
                "model": model,
                "messages": anthropic_messages,
                "max_tokens": int(max_tokens),
                "timeout": request_timeout,
            }
            if system_message:
                create_params["system"] = system_message
            if extra:
                create_params.update(extra)
            
            logger.debug(f"Параметры запроса: {list(create_params.keys())}")
            
            # Используем asyncio.wait_for для дополнительного контроля таймаута
            response: Message = await asyncio.wait_for(
                self.client.messages.create(**create_params),
                timeout=request_timeout + 10  # Дополнительная защита
            )
            
            logger.debug(f"Получен ответ: {response}")
            
            # Проверяем наличие контента
            if not response.content:
                logger.error(f"Пустой ответ от Anthropic: нет content. Response: {response}")
                return None
            
            # Извлекаем текст из ответа
            result_content = self._extract_text_from_response_sdk(response)
            
            # Проверяем что контент не пустой
            if not result_content:
                logger.warning(f"Anthropic вернул пустой контент. Response content blocks: {response.content}")
                # Пытаемся извлечь любой контент
                for i, block in enumerate(response.content):
                    logger.debug(f"Block {i}: type={getattr(block, 'type', 'unknown')}")
                    if hasattr(block, 'text'):
                        logger.debug(f"Block {i} text: {block.text[:100] if block.text else 'None'}...")
            
            logger.info(f"Успешно получен ответ длиной {len(result_content) if result_content else 0} символов")
            
            # Конвертируем response в dict для логирования
            response_dict = {
                "id": response.id,
                "model": response.model,
                "role": response.role,
                "content": [
                    self._content_block_to_dict(block) 
                    for block in response.content
                ],
                "stop_reason": response.stop_reason,
                "stop_sequence": response.stop_sequence,
                "usage": {
                    "input_tokens": response.usage.input_tokens if response.usage else None,
                    "output_tokens": response.usage.output_tokens if response.usage else None,
                }
            }
            
            # Логируем успешный запрос
            response_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"Успешный ответ от Anthropic за {response_time:.2f}с")
            
            self.log_ai_request(
                user_id = user_id,
                provider="anthropic",
                model=model,
                request_data=request_data,
                response_data=response_dict,
                response_time=response_time,
                status_code=200
            )
            
            return result_content
                        
        except asyncio.TimeoutError:
            elapsed_time = (datetime.now() - start_time).total_seconds()
            error_msg = f"Таймаут при запросе к Anthropic API (модель: {model}, прошло: {elapsed_time:.2f}с из {request_timeout}с)"
            logger.error(error_msg)
            
            # Логируем таймаут
            self.log_ai_request(
                user_id = user_id,
                provider="anthropic",
                model=model,
                request_data=request_data,
                response_data=None,
                response_time=elapsed_time,
                status_code=0,
                error=error_msg
            )
            
            return None
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Ошибка при запросе к Anthropic: {e}", exc_info=True)
            
            response_time = (datetime.now() - start_time).total_seconds()
            self.log_ai_request(
                user_id = user_id,
                provider="anthropic",
                model=model,
                request_data=request_data,
                response_data=None,
                response_time=response_time,
                status_code=0,
                error=error_msg
            )
            
            return None
    
    def _convert_messages(self, messages: List[Dict[str, Any]]) -> tuple:
        """Преобразует сообщения в формат Anthropic SDK"""
        anthropic_messages = []
        system_message = ""
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "system":
                # Системное сообщение всегда текстовое
                if isinstance(content, str):
                    system_message = content
                elif isinstance(content, list):
                    # Извлекаем текст из списка
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            system_message = item.get("text", "")
                            break
            else:
                # Для пользовательских и ассистентских сообщений
                # SDK принимает сообщения как есть
                anthropic_messages.append({
                    "role": role,
                    "content": content
                })
        
        return anthropic_messages, system_message
    
    def _extract_text_from_response_sdk(self, response: Message) -> Optional[str]:
        """Извлекает текст из ответа Anthropic SDK"""
        text_parts = []
        for content_block in response.content:
            # Проверяем тип блока контента
            if hasattr(content_block, 'type') and content_block.type == "text":
                if hasattr(content_block, 'text'):
                    text_parts.append(content_block.text)
            # Альтернативный способ для старых версий SDK
            elif hasattr(content_block, 'text'):
                text_parts.append(content_block.text)
        
        return "\n".join(text_parts) if text_parts else None
    
    def _content_block_to_dict(self, block: ContentBlock) -> Dict[str, Any]:
        """Конвертирует ContentBlock в словарь для логирования"""
        if hasattr(block, 'type'):
            if block.type == "text":
                return {
                    "type": "text",
                    "text": block.text if hasattr(block, 'text') else ""
                }
        # Альтернативный способ
        elif hasattr(block, 'text'):
            return {
                "type": "text",
                "text": block.text
            }
        return {"type": "unknown", "data": str(block)}
    
    def prepare_image_message(self, prompt: str, image_base64: str, mime_type: str) -> List[Dict[str, Any]]:
        """Подготовка сообщения с изображением для Anthropic"""
        return [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": image_base64
                    }
                }
            ]
        }]