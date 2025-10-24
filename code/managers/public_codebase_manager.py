# code/managers/public_codebase_manager.py
"""
Менеджер для работы с публичными кодовыми базами
"""

import os
import json
import logging
from typing import Tuple, List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class PublicCodebaseManager:
    """Управление публичными кодовыми базами"""
    
    def __init__(self, user_manager, lock):
        self.user_manager = user_manager
        self._lock = lock
    
    async def make_public(self, user_id: str, codebase_id: str, config: dict, 
                          config_file: str) -> Optional[str]:
        """Делает кодовую базу публичной и возвращает public_id"""
        # Нельзя сделать публичной devnull или системную базу
        if config.get("is_system") or config.get("folder_name") == "devnull":
            return None
        
        import uuid
        public_id = str(uuid.uuid4())[:8]
        
        config["is_public"] = True
        config["public_id"] = public_id
        config["access"]["type"] = "public"
        config["updated_at"] = datetime.now().isoformat()
        
        async with self._lock:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        
        # Регистрируем в глобальном реестре
        await self._register_public_codebase(user_id, codebase_id, public_id, config["name"])
        
        return public_id
    
    async def _register_public_codebase(self, owner_id: str, codebase_id: str, 
                                        public_id: str, name: str):
        """Регистрирует базу в глобальном реестре"""
        registry_file = os.path.join(self.user_manager.users_dir, "public_codebases.json")
        
        async with self._lock:
            if os.path.exists(registry_file):
                with open(registry_file, "r", encoding="utf-8") as f:
                    registry = json.load(f)
            else:
                registry = {}
            
            registry[public_id] = {
                "owner_id": owner_id,
                "codebase_id": codebase_id,
                "name": name,
                "created_at": datetime.now().isoformat()
            }
            
            with open(registry_file, "w", encoding="utf-8") as f:
                json.dump(registry, f, ensure_ascii=False, indent=2)
    
    async def add_public_codebase(self, user_id: str, public_id: str, 
                                  user_manager) -> Tuple[bool, str]:
        """Добавляет публичную базу в список доступных пользователю"""
        registry_file = os.path.join(user_manager.users_dir, "public_codebases.json")
        
        if not os.path.exists(registry_file):
            return False, "Публичная база не найдена"
        
        with open(registry_file, "r", encoding="utf-8") as f:
            registry = json.load(f)
        
        if public_id not in registry:
            return False, "Публичная база не найдена"
        
        pub_info = registry[public_id]
        owner_id = pub_info["owner_id"]
        
        if owner_id == user_id:
            return False, "Вы не можете добавить свою же базу"
        
        # Добавляем ссылку в список пользователя
        list_file = os.path.join(user_manager.ensure_user_dir(user_id), "codebases.json")
        
        if os.path.exists(list_file):
            with open(list_file, "r", encoding="utf-8") as f:
                user_codebases = json.load(f)
        else:
            user_codebases = {"active": None, "codebases": {}, "counter": 0}
        
        virtual_id = f"pub_{public_id}"
        
        if virtual_id in user_codebases["codebases"]:
            return False, "База уже добавлена"
        
        user_codebases["codebases"][virtual_id] = {
            "name": f"[PUBLIC] {pub_info['name']}",
            "folder_name": None,
            "is_public_ref": True,
            "public_id": public_id,
            "owner_id": owner_id,
            "created_at": datetime.now().isoformat()
        }
        
        async with self._lock:
            with open(list_file, "w", encoding="utf-8") as f:
                json.dump(user_codebases, f, ensure_ascii=False, indent=2)
        
        return True, f"Публичная база '{pub_info['name']}' добавлена"
    
    async def remove_public_codebase(self, user_id: str, virtual_id: str,
                                     user_manager) -> bool:
        """Удаляет публичную базу из списка пользователя"""
        list_file = os.path.join(user_manager.ensure_user_dir(user_id), "codebases.json")
        
        if not os.path.exists(list_file):
            return False
        
        with open(list_file, "r", encoding="utf-8") as f:
            user_codebases = json.load(f)
        
        if virtual_id not in user_codebases.get("codebases", {}):
            return False
        
        del user_codebases["codebases"][virtual_id]
        
        # Если это была активная база, сбрасываем
        if user_codebases.get("active") == virtual_id:
            user_codebases["active"] = None
            if user_codebases["codebases"]:
                user_codebases["active"] = list(user_codebases["codebases"].keys())[0]
        
        with open(list_file, "w", encoding="utf-8") as f:
            json.dump(user_codebases, f, ensure_ascii=False, indent=2)
        
        return True
    
    async def get_public_codebase_users(self, public_id: str, 
                                        users_dir: str) -> List[Dict[str, Any]]:
        """Получает список пользователей с доступом к публичной базе"""
        users_with_access = []
        virtual_id = f"pub_{public_id}"
        
        if os.path.exists(users_dir):
            for item in os.listdir(users_dir):
                user_dir = os.path.join(users_dir, item)
                
                if os.path.isdir(user_dir):
                    codebases_file = os.path.join(user_dir, "codebases.json")
                    
                    if os.path.exists(codebases_file):
                        try:
                            with open(codebases_file, "r", encoding="utf-8") as f:
                                user_codebases = json.load(f)
                                
                                if virtual_id in user_codebases.get("codebases", {}):
                                    cb_info = user_codebases["codebases"][virtual_id]
                                    
                                    if cb_info.get("is_public_ref") and cb_info.get("public_id") == public_id:
                                        users_with_access.append({
                                            "user_id": item,
                                            "added_at": cb_info.get("created_at", "Unknown")
                                        })
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.debug(f"Error reading codebases.json for user {item}: {e}")
                            continue
        
        return users_with_access