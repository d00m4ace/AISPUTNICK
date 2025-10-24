# code/email_service.py
import smtplib
import ssl
import random
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from config import Config

import logging
logger = logging.getLogger(__name__)


class EmailService:
    """Сервис для отправки email"""
    
    def __init__(self):
        self.enabled = Config.EMAIL_ENABLED
        self.smtp_email = Config.SMTP_EMAIL
        self.smtp_password = Config.SMTP_PASSWORD
        self.smtp_server = Config.SMTP_SERVER
        self.smtp_port = Config.SMTP_PORT
        self.smtp_use_ssl = Config.SMTP_USE_SSL
        self.smtp_verify_ssl = Config.SMTP_VERIFY_SSL
        self.from_name = Config.EMAIL_FROM_NAME
        
        # Хранилище кодов верификации {user_id: {"code": "123456", "email": "...", "expires": datetime}}
        self.verification_codes: Dict[str, Dict[str, Any]] = {}
    
    def generate_verification_code(self) -> str:
        """Генерирует 6-значный код верификации"""
        return str(random.randint(100000, 999999))
    
    async def send_email(self, to_email: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
        """Отправляет email"""
        if not self.enabled:
            logger.warning("Email service is disabled")
            return False
        
        try:
            # Создаем сообщение
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"{self.from_name} <{self.smtp_email}>"
            message["To"] = to_email
            
            # Добавляем текстовую часть
            text_part = MIMEText(body, "plain", "utf-8")
            message.attach(text_part)
            
            # Добавляем HTML часть если есть
            if html_body:
                html_part = MIMEText(html_body, "html", "utf-8")
                message.attach(html_part)
            
            # Настраиваем SSL контекст
            if self.smtp_verify_ssl:
                context = ssl.create_default_context()
            else:
                # Отключаем проверку сертификата для самоподписанных сертификатов
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            
            # Отправляем через SMTP
            if self.smtp_use_ssl:
                # Используем SMTP_SSL для порта 465
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context) as server:
                    server.login(self.smtp_email, self.smtp_password)
                    server.send_message(message)
            else:
                # Используем STARTTLS для портов 25, 587
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.starttls(context=context)
                    server.login(self.smtp_email, self.smtp_password)
                    server.send_message(message)
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP Authentication failed: {e}")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending email to {to_email}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False
    
    async def send_verification_code(self, user_id: str, email: str, user_name: str = "") -> Optional[str]:
        """Отправляет код верификации на email"""
        # Генерируем код
        code = self.generate_verification_code()
        
        # Сохраняем код с временем истечения (15 минут)
        self.verification_codes[user_id] = {
            "code": code,
            "email": email,
            "expires": datetime.now() + timedelta(minutes=15),
            "attempts": 0
        }
        
        # Формируем письмо
        subject = f"Код подтверждения email - {Config.BOT_NAME}"
        
        body = f"""
Здравствуйте{f', {user_name}' if user_name else ''}!

Ваш код подтверждения email: {code}

Код действителен в течение 15 минут.
Если вы не запрашивали подтверждение, проигнорируйте это письмо.

С уважением,
{Config.BOT_NAME}
        """.strip()
        
        html_body = f"""
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    <h2>Подтверждение email</h2>
    <p>Здравствуйте{f', {user_name}' if user_name else ''}!</p>
    <p>Ваш код подтверждения email:</p>
    <h1 style="color: #2196F3; font-size: 32px; letter-spacing: 5px;">{code}</h1>
    <p style="color: #666;">Код действителен в течение 15 минут.</p>
    <p style="color: #999; font-size: 12px;">Если вы не запрашивали подтверждение, проигнорируйте это письмо.</p>
    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
    <p style="color: #999; font-size: 12px;">С уважением,<br>{Config.BOT_NAME}</p>
</body>
</html>
        """.strip()
        
        # Отправляем
        success = await self.send_email(email, subject, body, html_body)
        
        if success:
            return code
        else:
            # Удаляем код если не удалось отправить
            del self.verification_codes[user_id]
            return None
    
    def verify_code(self, user_id: str, code: str) -> tuple[bool, str]:
        """Проверяет код верификации"""
        if user_id not in self.verification_codes:
            return False, "Код не найден. Запросите новый код."
        
        verification_data = self.verification_codes[user_id]
        
        # Проверяем срок действия
        if datetime.now() > verification_data["expires"]:
            del self.verification_codes[user_id]
            return False, "Код истек. Запросите новый код."
        
        # Увеличиваем счетчик попыток
        verification_data["attempts"] += 1
        
        # Проверяем количество попыток
        if verification_data["attempts"] > 5:
            del self.verification_codes[user_id]
            return False, "Превышено количество попыток. Запросите новый код."
        
        # Проверяем код
        if verification_data["code"] == code:
            email = verification_data["email"]
            del self.verification_codes[user_id]
            return True, email
        
        return False, f"Неверный код. Осталось попыток: {5 - verification_data['attempts']}"
    
    async def test_connection(self) -> bool:
        """Тестирует подключение к SMTP серверу"""
        try:
            # Настраиваем SSL контекст
            if self.smtp_verify_ssl:
                context = ssl.create_default_context()
            else:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            
            if self.smtp_use_ssl:
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context, timeout=10) as server:
                    server.login(self.smtp_email, self.smtp_password)
                    logger.info("SMTP connection test successful")
                    return True
            else:
                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                    server.starttls(context=context)
                    server.login(self.smtp_email, self.smtp_password)
                    logger.info("SMTP connection test successful")
                    return True
                    
        except Exception as e:
            logger.error(f"SMTP connection test failed: {e}")
            return False
