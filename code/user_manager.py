# code/user_manager.py
import json
import os
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from config import Config

class UserManager:
    """Управление пользователями бота"""
    
    def __init__(self):
        self.users_dir = Config.USERS_DIR
        self.users_file = os.path.join(self.users_dir, "users.json")
        self._lock = asyncio.Lock()
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        """Создает необходимые директории"""
        os.makedirs(self.users_dir, exist_ok=True)
        if not os.path.exists(self.users_file):
            with open(self.users_file, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
    
    async def load_users(self) -> Dict[str, Any]:
        """Загружает данные пользователей"""
        async with self._lock:
            try:
                with open(self.users_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return {}
    
    async def save_users(self, users: Dict[str, Any]):
        """Сохраняет данные пользователей"""
        async with self._lock:
            with open(self.users_file, "w", encoding="utf-8") as f:
                json.dump(users, f, ensure_ascii=False, indent=2)
    
    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Получает данные пользователя"""
        users = await self.load_users()
        return users.get(user_id)
    
    async def user_exists(self, user_id: str) -> bool:
        """Проверяет существование пользователя"""
        users = await self.load_users()
        return user_id in users
    
    async def is_active(self, user_id: str) -> bool:
        """Проверяет активен ли пользователь"""
        user = await self.get_user(user_id)
        return user.get("active", False) if user else False
    
    async def is_admin(self, user_id: str) -> bool:
        """Проверяет является ли пользователь админом"""
        user = await self.get_user(user_id)
        return user.get("admin", False) if user else False
    
    async def create_user(self, user_id: str, data: Dict[str, Any]) -> bool:
        """Создает нового пользователя"""
        users = await self.load_users()
    
        if user_id in users:
            return False
    
        users[user_id] = {
            "id": user_id,
            "name": data.get("name", ""),
            "surname": data.get("surname", ""),
            "company": data.get("company", ""),  # Новое поле
            "position": data.get("position", ""),
            "department": data.get("department", ""),
            "email": data.get("email", ""),
            "email_verified": False,
            "telegram_username": data.get("telegram_username", "Не указан"),
            "active": False,
            "admin": False,
            "created_at": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat()
        }
    
        await self.save_users(users)

        if True:  # Если пользователь успешно создан
            # Импортируем здесь чтобы избежать циклических зависимостей
            from codebase_manager import CodebaseManager
            cb_manager = CodebaseManager(self)
            await cb_manager.ensure_devnull(user_id)

        return True

    async def verify_email(self, user_id: str) -> bool:
        """Помечает email как верифицированный"""
        users = await self.load_users()
        if user_id in users:
            users[user_id]["email_verified"] = True
            users[user_id]["email_verified_at"] = datetime.now().isoformat()
            await self.save_users(users)
            return True
        return False

    async def is_email_verified(self, user_id: str) -> bool:
        """Проверяет верифицирован ли email"""
        user = await self.get_user(user_id)
        return user.get("email_verified", False) if user else False

    async def update_email_verification_compatibility(self):
        """Обновляет существующих пользователей для совместимости"""
        users = await self.load_users()
        updated = False
    
        for user_id, user_data in users.items():
            if "email_verified" not in user_data:
                user_data["email_verified"] = False
                updated = True
    
        if updated:
            await self.save_users(users)
    
    async def update_company_compatibility(self):
        """Обновляет существующих пользователей, добавляя поле company"""
        users = await self.load_users()
        updated = False
    
        for user_id, user_data in users.items():
            if "company" not in user_data:
                user_data["company"] = ""
                updated = True
    
        if updated:
            await self.save_users(users)
            return True
        return False
    
    async def update_activity(self, user_id: str):
        """Обновляет время последней активности"""
        users = await self.load_users()
        if user_id in users:
            users[user_id]["last_activity"] = datetime.now().isoformat()
            await self.save_users(users)
    
    def ensure_user_dir(self, user_id: str) -> str:
        """Создает и возвращает путь к папке пользователя"""
        user_dir = os.path.join(self.users_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)
        return user_dir
    
    async def get_user_context(self, user_id: str) -> Dict[str, Any]:
        """Получает контекст пользователя для ИИ"""
        user = await self.get_user(user_id)
        if not user:
            return {}
        
        return {
            "name": f"{user.get('name', '')} {user.get('surname', '')}".strip(),
            "company": user.get("company", ""),  # Добавляем компанию в контекст
            "position": user.get("position", ""),
            "department": user.get("department", ""),
            "is_admin": user.get("admin", False)
        }