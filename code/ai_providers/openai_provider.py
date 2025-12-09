# code/ai_providers/openai_provider.py
"""
Провайдер для работы с OpenAI API через официальный SDK с поддержкой GPT-5 и GPT-5-Codex
"""

import asyncio
import json
import base64
import logging
import httpx
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from .base_provider import BaseAIProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseAIProvider):
    """Провайдер для работы с OpenAI API через официальный SDK"""
    
    # Модели GPT-5 которые используют max_completion_tokens
    GPT5_MODELS = [
        "gpt-5.1","gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-chat-latest",
        "o4", "o4-mini", "o4-2025-01-01"
    ]
    
    # Модели которые используют v1/responses endpoint (Codex-подобные)
    RESPONSE_MODELS = [
        "gpt-5-codex", "gpt-5-codex-mini", "gpt-5-codex-turbo",
        "codex", "code-davinci", "code-cushman"
    ]
    
    # Разрешённые опциональные ключи для OpenAI
    OPTIONAL_KEYS = [
        "max_tokens", "max_completion_tokens", "temperature", "top_p", 
        "frequency_penalty", "presence_penalty", "stop", "logprobs", 
        "top_logprobs", "seed", "response_format",
        "reasoning_effort", "verbosity"  # GPT-5 additions
    ]
    
    # Таймауты для разных моделей (в секундах)
    MODEL_TIMEOUTS = {
        # GPT-5 модели - увеличенный таймаут
        "gpt-5.1": 600,  # 10 минут для сложных запросов
        "gpt-5": 600,  # 10 минут для сложных запросов
        "gpt-5-mini": 300,  # 5 минут
        "gpt-5-nano": 180,  # 3 минуты
        "gpt-5-chat-latest": 300,
        "gpt-5-codex": 600,  # 10 минут для кодинга
        "gpt-5-codex-mini": 300,
        "gpt-5-codex-turbo": 450,
        "o4": 900,  # 15 минут для reasoning моделей
        "o4-mini": 600,  # 10 минут
        "o4-2025-01-01": 900,
        # GPT-4 модели
        "gpt-4o": 300,
        "gpt-4o-mini": 180,
        "gpt-4": 300,
        "gpt-4-turbo": 180,
        "gpt-4-turbo-preview": 180,
        # Старые модели
        "gpt-3.5-turbo": 60,
        # По умолчанию
        "default": 120
    }

    GPT5_DEFAULT_MAX_TOKENS = 16384  
    
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
            self.client = AsyncOpenAI(
                api_key=api_key,
                max_retries=2,  # Умеренное количество повторов
                timeout=120.0  # Базовый таймаут (будет переопределяться для каждого запроса)
            )
            # Создаем httpx клиент для прямых запросов к v1/responses
            self.http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )
        else:
            self.client = None
            self.http_client = None
    
    def get_default_model(self) -> str:
        """Получение модели по умолчанию"""
        return self.models_config.get("openai", {}).get("default_model", "gpt-4o")
    
    def _is_gpt5_model(self, model: str) -> bool:
        """Проверяет, является ли модель GPT-5 или схожей"""
        if not model:
            return False
        model_lower = model.lower()
        return any(gpt5 in model_lower for gpt5 in self.GPT5_MODELS)
    
    def _is_response_model(self, model: str) -> bool:
        """Проверяет, использует ли модель v1/responses endpoint"""
        if not model:
            return False
        model_lower = model.lower()
        return any(resp_model in model_lower for resp_model in self.RESPONSE_MODELS)
    
    def get_model_timeout(self, model: str, custom_timeout: Optional[int] = None) -> float:
        """
        Получает таймаут для модели
        
        Args:
            model: название модели
            custom_timeout: пользовательский таймаут (если указан, используется он)
            
        Returns:
            Таймаут в секундах
        """
        if custom_timeout is not None:
            logger.debug(f"Используется пользовательский таймаут: {custom_timeout}с для модели {model}")
            return float(custom_timeout)
            
        # Ищем точное совпадение
        if model in self.MODEL_TIMEOUTS:
            timeout = self.MODEL_TIMEOUTS[model]
        # Ищем по префиксу (например, gpt-5-custom -> gpt-5)
        else:
            timeout = self.MODEL_TIMEOUTS.get("default", 120)
            for model_prefix in self.MODEL_TIMEOUTS:
                if model.startswith(model_prefix):
                    timeout = self.MODEL_TIMEOUTS[model_prefix]
                    break
                    
        logger.debug(f"Таймаут для модели {model}: {timeout}с")
        return float(timeout)
    
    async def _send_response_request(
        self,
        user_id: str,
        messages: List[Dict[str, Any]],
        model: str,
        timeout: float,
        extra: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Отправляет запрос к v1/responses endpoint для Codex-подобных моделей
        
        Args:
            user_id: ID пользователя
            messages: список сообщений в формате chat/completions
            model: модель
            timeout: таймаут запроса
            extra: дополнительные параметры
            
        Returns:
            Ответ API или None при ошибке
        """
        if not self.http_client:
            raise ValueError("HTTP клиент не инициализирован")
        
        # Склеиваем все сообщения в единый промпт
        # Это более надежный способ передачи истории для v1/responses
        prompt_parts = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
            elif role == "user":
                prompt_parts.append(f"User: {content}")
        
        # Добавляем финальный префикс для ответа ассистента
        prompt_parts.append("Assistant:")
        
        # Объединяем все части в единый промпт
        full_prompt = "\n\n".join(prompt_parts)
        
        # Формируем единое сообщение для API
        formatted_input = [{
            "type": "message",
            "role": "user",  # Весь промпт отправляем как user message
            "content": [
                {"type": "input_text", "text": full_prompt}
            ]
        }]
        
        # Подготавливаем параметры для v1/responses
        request_body = {
            "model": model,
            "input": formatted_input,
        }
        
        # Добавляем только поддерживаемые параметры
        # Конвертируем max_completion_tokens в max_tokens
        if "max_completion_tokens" in extra:
            request_body["max_tokens"] = extra["max_completion_tokens"]
        elif "max_tokens" in extra:
            request_body["max_tokens"] = extra["max_tokens"]
        
        # Добавляем другие поддерживаемые параметры если они есть
        supported_params = ["stop", "seed", "response_format", "stream"]
        for param in supported_params:
            if param in extra:
                request_body[param] = extra[param]
        
        logger.info(f"Отправка запроса к v1/responses: модель={model}, история={len(messages)} сообщений, промпт={len(full_prompt)} символов")
        
        # Детальное логирование для отладки
        logger.debug(f"Параметры запроса: {list(request_body.keys())}")
        
        # Логируем состав истории
        roles_count = {"system": 0, "user": 0, "assistant": 0}
        for msg in messages:
            roles_count[msg.get("role", "unknown")] = roles_count.get(msg.get("role", "unknown"), 0) + 1
        logger.debug(f"Состав истории: system={roles_count['system']}, user={roles_count['user']}, assistant={roles_count['assistant']}")
        
        logger.debug(f"Промпт (первые 1000 символов): {full_prompt[:1000]}...")
        if len(full_prompt) > 1000:
            logger.debug(f"...и последние 500 символов: ...{full_prompt[-500:]}")
        
        logger.debug(f"Request body (первые 3000 символов): {json.dumps(request_body, ensure_ascii=False)[:3000]}")
        
        try:
            response = await self.http_client.post(
                "https://api.openai.com/v1/responses",
                json=request_body,
                timeout=timeout
            )
            response.raise_for_status()
            
            response_data = response.json()
            logger.debug(f"Получен ответ от v1/responses: {json.dumps(response_data, ensure_ascii=False)[:500]}")
            
            # Обрабатываем формат ответа v1/responses для GPT-5-Codex
            # Структура: output -> найти элемент с type='message' -> content -> text
            if "output" in response_data:
                content = ""
                
                # Ищем сообщение в output массиве
                for output_item in response_data.get("output", []):
                    if output_item.get("type") == "message":
                        # Извлекаем текст из content
                        for content_item in output_item.get("content", []):
                            if content_item.get("type") == "output_text":
                                content = content_item.get("text", "")
                                break
                        break
                
                if not content:
                    logger.warning("Не удалось извлечь текст из ответа v1/responses")
                
                # Создаем унифицированную структуру для совместимости
                unified_response = {
                    "id": response_data.get("id", ""),
                    "model": response_data.get("model", model),
                    "usage": response_data.get("usage", {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0
                    }),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": content
                            },
                            "finish_reason": "stop"
                        }
                    ]
                }
                
                return unified_response
                
            elif "choices" in response_data and response_data["choices"]:
                # Альтернативный формат (если есть)
                content = response_data["choices"][0].get("text", "")
                
                unified_response = {
                    "id": response_data.get("id", ""),
                    "model": response_data.get("model", model),
                    "usage": response_data.get("usage", {}),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": content.strip()
                            },
                            "finish_reason": response_data["choices"][0].get("finish_reason", "stop")
                        }
                    ]
                }
                
                return unified_response
            else:
                logger.error(f"Неожиданная структура ответа от v1/responses: {json.dumps(response_data, ensure_ascii=False)[:1000]}")
                return None
                
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP ошибка при запросе к v1/responses: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при запросе к v1/responses: {e}", exc_info=True)
            return None
    
    async def send_request(
        self,
        user_id: str,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        timeout: Optional[int] = None,  # Пользовательский таймаут
        **kwargs
    ) -> Optional[str]:
        """
        Отправляет запрос к OpenAI API
        
        Args:
            user_id: ID пользователя для логирования
            messages: список сообщений (включая историю)
            model: модель для использования
            timeout: пользовательский таймаут в секундах (опционально)
            **kwargs: дополнительные параметры API
        """
        if not self.client:
            raise ValueError("OpenAI API ключ не установлен")
        
        model = model or self.get_default_model()
        
        # Получаем таймаут для модели
        request_timeout = self.get_model_timeout(model, timeout)
        
        # Подхватываем опциональные параметры
        extra = self.active_model_params(
            provider="openai",
            model=model,
            allowed_keys=self.OPTIONAL_KEYS,
            overrides=kwargs,
        )
        
        # Для GPT-5 моделей (включая codex) конвертируем max_tokens в max_completion_tokens
        if self._is_gpt5_model(model) or self._is_response_model(model):
            if "max_tokens" in extra and "max_completion_tokens" not in extra:
                extra["max_completion_tokens"] = extra.pop("max_tokens")
                logger.debug(f"Конвертировал max_tokens в max_completion_tokens для модели {model}")
        else:
            # Для старых моделей убираем max_completion_tokens если есть
            if "max_completion_tokens" in extra and "max_tokens" not in extra:
                extra["max_tokens"] = extra.pop("max_completion_tokens")
                logger.debug(f"Конвертировал max_completion_tokens в max_tokens для модели {model}")
        
        # Подготавливаем данные для логирования
        request_data = {
            "model": model,
            "messages": messages,
            **extra
        }
        
        start_time = datetime.now()
        error_msg = None
        
        logger.info(f"Отправка запроса к OpenAI API: модель={model}, таймаут={request_timeout}с, параметры={list(extra.keys())}")
        
        try:
            # Проверяем, нужно ли использовать v1/responses endpoint
            if self._is_response_model(model):
                logger.info(f"Используем v1/responses endpoint для модели {model}")
                
                response_dict = await self._send_response_request(
                    user_id=user_id,
                    messages=messages,
                    model=model,
                    timeout=request_timeout,
                    extra=extra
                )
                
                if not response_dict:
                    logger.error("Не удалось получить ответ от v1/responses")
                    return None
                
                result_content = response_dict["choices"][0]["message"]["content"]
                
            else:
                # Используем стандартный chat completions endpoint
                create_params = {
                    "model": model,
                    "messages": messages,
                    "timeout": request_timeout,
                    **extra
                }
                
                logger.debug(f"Параметры запроса к chat/completions: {list(create_params.keys())}")
                
                # Используем asyncio.wait_for для контроля таймаута
                response: ChatCompletion = await asyncio.wait_for(
                    self.client.chat.completions.create(**create_params),
                    timeout=request_timeout + 10  # Дополнительная защита
                )
                
                logger.debug(f"Получен ответ: {response}")
                
                # Проверяем наличие choices
                if not response.choices:
                    logger.error(f"Пустой ответ от OpenAI: нет choices. Response: {response}")
                    return None
                
                # Извлекаем контент из ответа
                result_content = response.choices[0].message.content
                
                # Проверяем что контент не пустой
                if result_content is None:
                    logger.warning(f"OpenAI вернул None в content. Response: {response.model_dump_json()}")
                    result_content = ""
                
                # Конвертируем response в dict для логирования
                response_dict = {
                    "id": response.id,
                    "model": response.model,
                    "usage": response.usage.model_dump() if response.usage else None,
                    "choices": [
                        {
                            "index": choice.index,
                            "message": {
                                "role": choice.message.role,
                                "content": choice.message.content,
                                "refusal": getattr(choice.message, 'refusal', None)
                            },
                            "finish_reason": choice.finish_reason
                        }
                        for choice in response.choices
                    ],
                    "system_fingerprint": getattr(response, 'system_fingerprint', None)
                }
            
            logger.info(f"Успешно получен ответ длиной {len(result_content)} символов")
            
            # Логируем успешный запрос
            response_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"Успешный ответ от OpenAI за {response_time:.2f}с")
            
            self.log_ai_request(
                user_id=user_id,
                provider="openai",
                model=model,
                request_data=request_data,
                response_data=response_dict,
                response_time=response_time,
                status_code=200
            )
            
            return result_content
                    
        except asyncio.TimeoutError:
            elapsed_time = (datetime.now() - start_time).total_seconds()
            error_msg = f"Таймаут при запросе к OpenAI API (модель: {model}, прошло: {elapsed_time:.2f}с из {request_timeout}с)"
            logger.error(error_msg)
            
            # Логируем таймаут
            self.log_ai_request(
                user_id=user_id,
                provider="openai",
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
            logger.error(f"Ошибка при запросе к OpenAI: {e}", exc_info=True)
            
            # Обработка специфических ошибок
            if "v1/responses" in str(e) and "not in v1/chat/completions" in str(e):
                # Модель требует v1/responses endpoint, но мы пытались использовать chat/completions
                logger.info(f"Модель {model} требует v1/responses endpoint, повторяем запрос")
                
                try:
                    response_dict = await self._send_response_request(
                        user_id=user_id,
                        messages=messages,
                        model=model,
                        timeout=request_timeout,
                        extra=extra
                    )
                    
                    if response_dict:
                        result_content = response_dict["choices"][0]["message"]["content"]
                        
                        response_time = (datetime.now() - start_time).total_seconds()
                        logger.info(f"Успешный повторный запрос через v1/responses за {response_time:.2f}с")
                        
                        self.log_ai_request(
                            user_id=user_id,
                            provider="openai",
                            model=model,
                            request_data=request_data,
                            response_data=response_dict,
                            response_time=response_time,
                            status_code=200
                        )
                        
                        return result_content
                        
                except Exception as retry_error:
                    logger.error(f"Ошибка при повторном запросе через v1/responses: {retry_error}")
                    error_msg = str(retry_error)
            
            elif "max_tokens" in str(e) and "unsupported" in str(e).lower():
                # Обработка ошибки с max_tokens для GPT-5
                logger.info("Повторяем запрос с max_completion_tokens вместо max_tokens")
                if "max_tokens" in extra:
                    extra["max_completion_tokens"] = extra.pop("max_tokens")
                    try:
                        # Повторная попытка с исправленными параметрами
                        create_params_retry = {
                            "model": model,
                            "messages": messages,
                            "timeout": request_timeout,
                            **extra
                        }
                        
                        response = await asyncio.wait_for(
                            self.client.chat.completions.create(**create_params_retry),
                            timeout=request_timeout + 10
                        )
                        
                        if not response.choices:
                            logger.error("Повторный запрос: нет choices")
                            return None
                            
                        result_content = response.choices[0].message.content
                        
                        response_time = (datetime.now() - start_time).total_seconds()
                        logger.info(f"Успешный повторный запрос за {response_time:.2f}с")
                        
                        # Логируем успешный повторный запрос
                        self.log_ai_request(
                            user_id=user_id,
                            provider="openai",
                            model=model,
                            request_data={**request_data, **extra},
                            response_data={"content": result_content, "retry": True},
                            response_time=response_time,
                            status_code=200
                        )
                        
                        return result_content
                    except Exception as retry_error:
                        logger.error(f"Ошибка при повторном запросе: {retry_error}")
                        error_msg = str(retry_error)
            
            response_time = (datetime.now() - start_time).total_seconds()
            self.log_ai_request(
                user_id=user_id,
                provider="openai",
                model=model,
                request_data=request_data,
                response_data=None,
                response_time=response_time,
                status_code=0,
                error=error_msg
            )
            
            return None
    
    def prepare_image_message(self, prompt: str, image_base64: str, mime_type: str) -> List[Dict[str, Any]]:
        """Подготовка сообщения с изображением для OpenAI"""
        return [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_base64}"
                    }
                }
            ]
        }]
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрытие HTTP клиента при выходе"""
        if self.http_client:
            await self.http_client.aclose()