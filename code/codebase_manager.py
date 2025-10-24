# code/codebase_manager.py
import json
import os
import asyncio
import shutil
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from config import Config

from managers.public_codebase_manager import PublicCodebaseManager

import logging
logger = logging.getLogger(__name__)

class CodebaseManager:
    """Управление кодовыми базами пользователей"""
    
    def __init__(self, user_manager):
        self.user_manager = user_manager
        self._lock = asyncio.Lock()
        self.public_manager = PublicCodebaseManager(user_manager, self._lock)

    # Изменения в методе ensure_devnull
    # (добавить после создания конфига и сохранения в список)
    async def ensure_devnull(self, user_id: str):
        """Создает специальную кодовую базу devnull если её нет"""
        list_file = self._get_user_codebases_file(user_id)
    
        if os.path.exists(list_file):
            with open(list_file, "r", encoding="utf-8") as f:
                user_codebases = json.load(f)
                # Проверяем есть ли devnull
                for cb_id, cb_info in user_codebases.get("codebases", {}).items():
                    if cb_info.get("folder_name") == "devnull":
                        # Если нет активной базы - делаем devnull активной
                        if not user_codebases.get("active"):
                            user_codebases["active"] = cb_id
                            with open(list_file, "w", encoding="utf-8") as f:
                                json.dump(user_codebases, f, ensure_ascii=False, indent=2)
                        return cb_id
    
        # Создаем devnull (существующий код)
        user_dir = self.user_manager.ensure_user_dir(user_id)
        devnull_dir = os.path.join(user_dir, "codebases", "devnull")
        os.makedirs(devnull_dir, exist_ok=True)
        os.makedirs(os.path.join(devnull_dir, "files"), exist_ok=True)
    
        config = {
            "id": "0",
            "number": 0,
            "folder_name": "devnull",
            "name": "devnull",
            "description": "System null codebase",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "owner_id": user_id,
            "is_system": True,
            "readonly": True,
            "hidden": False,
            "is_public": False,
            "public_id": None,
            "access": {
                "type": "private",
                "shared_with": []
            },
            "ai_settings": {
                "provider": "default",
                "model": "default",
                "custom_params": {}
            },
            "rag_settings": {
                "chunk_size": 4096,
                "overlap_size": 256
            },
            "stats": {
                "files_count": 0,
                "total_size": 0,
                "last_accessed": datetime.now().isoformat()
            }
        }
    
        config_file = os.path.join(devnull_dir, "config.json")
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    
        # Добавляем в список
        if os.path.exists(list_file):
            with open(list_file, "r", encoding="utf-8") as f:
                user_codebases = json.load(f)
        else:
            user_codebases = {"active": None, "codebases": {}, "counter": 0}
    
        user_codebases["codebases"]["0"] = {
            "name": "devnull",
            "folder_name": "devnull",
            "number": 0,
            "created_at": datetime.now().isoformat()
        }
    
        # НОВОЕ: Делаем devnull активной если нет другой активной базы
        if not user_codebases.get("active"):
            user_codebases["active"] = "0"
    
        with open(list_file, "w", encoding="utf-8") as f:
            json.dump(user_codebases, f, ensure_ascii=False, indent=2)
    
        return "0"
    
    def _get_codebase_dir(self, user_id: str, codebase_id: str) -> str:
        # Если это ссылка на публичную базу
        if codebase_id.startswith("pub_"):
            list_file = self._get_user_codebases_file(user_id)
            if os.path.exists(list_file):
                with open(list_file, "r", encoding="utf-8") as f:
                    user_codebases = json.load(f)
                    cb_info = user_codebases.get("codebases", {}).get(codebase_id)
                
                    if cb_info and cb_info.get("is_public_ref"):
                        owner_id = cb_info["owner_id"]
                    
                        # Получаем реальный ID базы через реестр
                        registry_file = os.path.join(self.user_manager.users_dir, "public_codebases.json")
                        if os.path.exists(registry_file):
                            with open(registry_file, "r", encoding="utf-8") as f:
                                registry = json.load(f)
                                pub_info = registry.get(cb_info["public_id"])
                            
                                if pub_info:
                                    # Рекурсивно вызываем для получения пути у владельца
                                    return self._get_codebase_dir(owner_id, pub_info["codebase_id"])
        
            # Если не нашли - возвращаем несуществующий путь
            return os.path.join(self.user_manager.ensure_user_dir(user_id), "codebases", "invalid")
    
        # Обычная логика для своих баз (существующий код)
        list_file = self._get_user_codebases_file(user_id)
        if os.path.exists(list_file):
            with open(list_file, "r", encoding="utf-8") as f:
                user_codebases = json.load(f)
                if codebase_id in user_codebases.get("codebases", {}):
                    folder_name = user_codebases["codebases"][codebase_id].get("folder_name")
                    if folder_name:
                        user_dir = self.user_manager.ensure_user_dir(user_id)
                        return os.path.join(user_dir, "codebases", folder_name)

        config = self._load_codebase_config_sync(user_id, codebase_id)
        if config and "folder_name" in config:
            user_dir = self.user_manager.ensure_user_dir(user_id)
            return os.path.join(user_dir, "codebases", config["folder_name"])

        user_dir = self.user_manager.ensure_user_dir(user_id)
        return os.path.join(user_dir, "codebases", codebase_id)

    
    def _load_codebase_config_sync(self, user_id: str, codebase_id: str) -> Optional[Dict[str, Any]]:
        """Синхронная загрузка конфига для внутреннего использования"""
        list_file = self._get_user_codebases_file(user_id)
        if not os.path.exists(list_file):
            return None
    
        with open(list_file, "r", encoding="utf-8") as f:
            user_codebases = json.load(f)
    
        # Ищем папку по ID в списке
        for cb_id in user_codebases.get("codebases", {}):
            if cb_id == codebase_id:
                # Находим папку и читаем конфиг
                user_dir = self.user_manager.ensure_user_dir(user_id)
                codebases_dir = os.path.join(user_dir, "codebases")
            
                # Перебираем папки чтобы найти нужную
                if os.path.exists(codebases_dir):
                    for folder in os.listdir(codebases_dir):
                        config_file = os.path.join(codebases_dir, folder, "config.json")
                        if os.path.exists(config_file):
                            with open(config_file, "r", encoding="utf-8") as f:
                                config = json.load(f)
                                if config.get("id") == codebase_id:
                                    return config
        return None

    def _get_codebase_config_file(self, user_id: str, codebase_id: str) -> str:
        # Если это ссылка на публичную базу
        if codebase_id.startswith("pub_"):
            list_file = self._get_user_codebases_file(user_id)
            if os.path.exists(list_file):
                with open(list_file, "r", encoding="utf-8") as f:
                    user_codebases = json.load(f)
                    cb_info = user_codebases.get("codebases", {}).get(codebase_id)
                
                    if cb_info and cb_info.get("is_public_ref"):
                        owner_id = cb_info["owner_id"]
                    
                        registry_file = os.path.join(self.user_manager.users_dir, "public_codebases.json")
                        if os.path.exists(registry_file):
                            with open(registry_file, "r", encoding="utf-8") as f:
                                registry = json.load(f)
                                pub_info = registry.get(cb_info["public_id"])
                            
                                if pub_info:
                                    # Получаем путь к конфигу у владельца
                                    return self._get_codebase_config_file(owner_id, pub_info["codebase_id"])
        
            # Возвращаем несуществующий путь
            return os.path.join(self.user_manager.ensure_user_dir(user_id), "invalid_config.json")
    
        # Существующая логика
        list_file = self._get_user_codebases_file(user_id)
        if os.path.exists(list_file):
            with open(list_file, "r", encoding="utf-8") as f:
                user_codebases = json.load(f)
                if codebase_id in user_codebases.get("codebases", {}):
                    folder_name = user_codebases["codebases"][codebase_id].get("folder_name")
                    if folder_name:
                        user_dir = self.user_manager.ensure_user_dir(user_id)
                        return os.path.join(user_dir, "codebases", folder_name, "config.json")

        codebase_dir = self._get_codebase_dir(user_id, codebase_id)
        return os.path.join(codebase_dir, "config.json")
    
    def _get_user_codebases_file(self, user_id: str) -> str:
        """Получает путь к файлу со списком кодовых баз пользователя"""
        user_dir = self.user_manager.ensure_user_dir(user_id)
        return os.path.join(user_dir, "codebases.json")

    def codebase_folder_exists(self, user_id: str, folder_name: str) -> bool:
        """Проверяет существование папки кодовой базы"""
        user_dir = self.user_manager.ensure_user_dir(user_id)
        codebase_path = os.path.join(user_dir, "codebases", folder_name)
        return os.path.exists(codebase_path)

    def _generate_folder_name(self, name: str) -> str:
        """Генерирует имя папки из названия"""
        # Заменяем пробелы на подчеркивания и приводим к нижнему регистру
        folder_name = name.replace(" ", "_").lower()
        # Оставляем только разрешенные символы (включая русские буквы)
        import re
        folder_name = re.sub(r'[^a-z0-9_\-а-яё]', '', folder_name)
        return folder_name
    

    # Добавить новый метод для скрытия/показа:
    async def toggle_hidden(self, user_id: str, codebase_id: str, hidden: bool = True) -> bool:
        """Скрывает или показывает кодовую базу"""
        config = await self.get_codebase_config(user_id, codebase_id)
        if not config:
            return False
    
        # Нельзя скрыть devnull
        if config.get("folder_name") == "devnull" or config.get("is_system"):
            return False
    
        config["hidden"] = hidden
        config["updated_at"] = datetime.now().isoformat()
    
        config_file = self._get_codebase_config_file(user_id, codebase_id)
        async with self._lock:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
    
        return True

    # Добавить метод для публикации:
    async def make_public(self, user_id: str, codebase_id: str) -> Optional[str]:
        """Делает кодовую базу публичной и возвращает public_id"""
        config = await self.get_codebase_config(user_id, codebase_id)
        if not config:
            return None
    
        config_file = self._get_codebase_config_file(user_id, codebase_id)
        return await self.public_manager.make_public(user_id, codebase_id, config, config_file)

    async def add_public_codebase(self, user_id: str, public_id: str) -> Tuple[bool, str]:
        """Добавляет публичную базу в список доступных пользователю"""
        return await self.public_manager.add_public_codebase(user_id, public_id, self.user_manager)

    async def create_codebase(self, user_id: str, name: str, description: str = "") -> Optional[str]:
        """Создает новую кодовую базу"""
        async with self._lock:
            try:
                # Генерируем имя папки
                folder_name = self._generate_folder_name(name)
            
                # Проверяем существование
                if self.codebase_folder_exists(user_id, folder_name):
                    return None  # Папка уже существует
            
                # Получаем и инкрементируем счетчик
                # Используем синхронную версию чтобы избежать deadlock
                list_file = self._get_user_codebases_file(user_id)
                if os.path.exists(list_file):
                    with open(list_file, "r", encoding="utf-8") as f:
                        user_codebases = json.load(f)
                else:
                    user_codebases = {"active": None, "codebases": {}, "counter": 0}
            
                if "counter" not in user_codebases:
                    user_codebases["counter"] = 0
                
                counter = user_codebases["counter"] + 1

                # Проверяем что не создаем базу с зарезервированными именами
                if folder_name == "devnull" or name.lower() == "devnull":
                    return None
            
                # ID теперь - это номер из счетчика
                codebase_id = str(counter)
            
                # Создаем директорию с именем папки
                user_dir = self.user_manager.ensure_user_dir(user_id)
                codebase_dir = os.path.join(user_dir, "codebases", folder_name)
                os.makedirs(codebase_dir, exist_ok=False)
                os.makedirs(os.path.join(codebase_dir, "files"), exist_ok=True)
            
                # Конфигурация кодовой базы
                config = {
                    "id": codebase_id,
                    "number": counter,
                    "folder_name": folder_name,
                    "name": name,
                    "description": description,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "owner_id": user_id,
                    "hidden": False,
                    "is_public": False,
                    "public_id": None,
                    "is_system": False,
                    "access": {
                        "type": "private",
                        "shared_with": []
                    },
                    "ai_settings": {
                        "provider": "default",
                        "model": "default",
                        "custom_params": {}
                    },
                    "rag_settings": {  # НОВОЕ
                        "chunk_size": 4096,
                        "overlap_size": 256
                    },
                    "stats": {
                        "files_count": 0,
                        "total_size": 0,
                        "last_accessed": datetime.now().isoformat()
                    }
                }
            
                # Сохраняем конфигурацию в папку
                config_file = os.path.join(codebase_dir, "config.json")
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            
                # Обновляем список кодовых баз пользователя с новым счетчиком
                await self._add_to_user_list_with_counter(user_id, codebase_id, name, folder_name, counter)
            
                # НОВОЕ: Если это первая реальная база (не devnull), делаем её активной
                user_codebases = await self.get_user_codebases(user_id)
                non_devnull_count = sum(1 for cb_id, cb_info in user_codebases["codebases"].items() 
                                      if cb_info.get("folder_name") != "devnull")
            
                if non_devnull_count == 1:  # Только что создали первую не-devnull базу
                    await self.set_active_codebase(user_id, codebase_id)
            
                return codebase_id
            
            except FileExistsError:
                return None
            except Exception as e:
                import logging
                logging.error(f"Ошибка создания кодовой базы: {e}", exc_info=True)
                return None
    
    async def _add_to_user_list_with_counter(self, user_id: str, codebase_id: str, name: str, folder_name: str, counter: int):
        """Добавляет кодовую базу в список пользователя с обновлением счетчика"""
        list_file = self._get_user_codebases_file(user_id)
    
        if os.path.exists(list_file):
            with open(list_file, "r", encoding="utf-8") as f:
                user_codebases = json.load(f)
        else:
            user_codebases = {"active": None, "codebases": {}, "counter": 0}
    
        # Обновляем счетчик
        user_codebases["counter"] = counter
    
        # Добавляем кодовую базу
        user_codebases["codebases"][codebase_id] = {
            "name": name,
            "folder_name": folder_name,
            "number": counter,
            "created_at": datetime.now().isoformat()
        }
    
        # Если это первая кодовая база, делаем её активной
        if not user_codebases["active"]:
            user_codebases["active"] = codebase_id
    
        with open(list_file, "w", encoding="utf-8") as f:
            json.dump(user_codebases, f, ensure_ascii=False, indent=2)
   
    # Изменения в методе get_user_codebases
    async def get_user_codebases(self, user_id: str, include_hidden: bool = False) -> Dict[str, Any]:
        """Получает список кодовых баз пользователя"""
        list_file = self._get_user_codebases_file(user_id)

        if not os.path.exists(list_file):
            # Создаем devnull для нового пользователя
            devnull_id = await self.ensure_devnull(user_id)
            # НОВОЕ: Возвращаем с активной devnull
            return {"active": devnull_id, "codebases": {"0": {"name": "devnull", "folder_name": "devnull"}}, "counter": 0}
    
        with open(list_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
            # НОВОЕ: Если нет активной базы, но есть devnull - делаем её активной
            if not data.get("active"):
                for cb_id, cb_info in data.get("codebases", {}).items():
                    if cb_info.get("folder_name") == "devnull":
                        data["active"] = cb_id
                        # Сохраняем изменение
                        with open(list_file, "w", encoding="utf-8") as fw:
                            json.dump(data, fw, ensure_ascii=False, indent=2)
                        break
        
            if not include_hidden:
                # Фильтруем hidden базы
                filtered_codebases = {}
                for cb_id, cb_info in data.get("codebases", {}).items():
                    # Для публичных ссылок проверяем оригинальную базу
                    if cb_info.get("is_public_ref"):
                        filtered_codebases[cb_id] = cb_info
                    else:
                        config = await self.get_codebase_config(user_id, cb_id)
                        if config and not config.get("hidden", False):
                            filtered_codebases[cb_id] = cb_info
        
                data["codebases"] = filtered_codebases

            if "counter" not in data:
                data["counter"] = 0
            return data
    
    async def get_codebase_config(self, user_id: str, codebase_id: str) -> Optional[Dict[str, Any]]:
        # Если это ссылка на публичную базу
        if codebase_id.startswith("pub_"):
            list_file = self._get_user_codebases_file(user_id)
            if os.path.exists(list_file):
                with open(list_file, "r", encoding="utf-8") as f:
                    user_codebases = json.load(f)
                    cb_info = user_codebases.get("codebases", {}).get(codebase_id)
                    if cb_info and cb_info.get("is_public_ref"):
                        # Получаем конфиг из базы владельца
                        owner_id = cb_info["owner_id"]
                        # Находим реальный ID базы через реестр
                        registry_file = os.path.join(self.user_manager.users_dir, "public_codebases.json")
                        if os.path.exists(registry_file):
                            with open(registry_file, "r", encoding="utf-8") as f:
                                registry = json.load(f)
                                pub_info = registry.get(cb_info["public_id"])
                                if pub_info:
                                    real_config = await self.get_codebase_config(owner_id, pub_info["codebase_id"])
                                    if real_config:
                                        # Добавляем флаг что это не наша база
                                        real_config["is_readonly_for_user"] = True
                                        real_config["actual_owner_id"] = owner_id
                                        return real_config
            return None        
        
        """Получает конфигурацию кодовой базы"""
        config_file = self._get_codebase_config_file(user_id, codebase_id)
        
        if not os.path.exists(config_file):
            return None
        
        async with self._lock:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
    
    async def update_codebase_config(self, user_id: str, codebase_id: str, updates: Dict[str, Any]) -> bool:
        config = await self.get_codebase_config(user_id, codebase_id)
        if not config:
            return False

        # Проверяем и добавляем rag_settings если отсутствует
        if "rag_settings" not in config:
            config["rag_settings"] = {
                "chunk_size": 4096,
                "overlap_size": 256
            }

        # Обрабатываем обновления
        for key, value in updates.items():
            if key in ["name", "description"]:
                config[key] = value
            elif key == "access_type":
                config["access"]["type"] = value
            elif key == "shared_with":
                config["access"]["shared_with"] = value
            elif key == "ai_provider":
                config["ai_settings"]["provider"] = value
            elif key == "ai_model":
                config["ai_settings"]["model"] = value
            elif key == "ai_params":
                config["ai_settings"]["custom_params"] = value
            elif key == "rag_settings":
                # Обновляем настройки RAG
                if "rag_settings" not in config:
                    config["rag_settings"] = {}
                config["rag_settings"].update(value)
            elif key == "chunk_size":
                # Поддержка прямого обновления chunk_size
                if "rag_settings" not in config:
                    config["rag_settings"] = {"chunk_size": 4096, "overlap_size": 256}
                config["rag_settings"]["chunk_size"] = value
            elif key == "overlap_size":
                # Поддержка прямого обновления overlap_size
                if "rag_settings" not in config:
                    config["rag_settings"] = {"chunk_size": 4096, "overlap_size": 256}
                config["rag_settings"]["overlap_size"] = value
            elif key == "stats":
                # Обновление статистики
                config["stats"] = value

        config["updated_at"] = datetime.now().isoformat()

        config_file = self._get_codebase_config_file(user_id, codebase_id)
        async with self._lock:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

        # Обновляем имя в списке пользовательских баз если оно изменилось
        if "name" in updates:
            user_codebases = await self.get_user_codebases(user_id)
            if codebase_id in user_codebases["codebases"]:
                user_codebases["codebases"][codebase_id]["name"] = updates["name"]
                list_file = self._get_user_codebases_file(user_id)
                with open(list_file, "w", encoding="utf-8") as f:
                    json.dump(user_codebases, f, ensure_ascii=False, indent=2)

        return True

    async def update_codebase_config(self, user_id: str, codebase_id: str, updates: Dict[str, Any]) -> bool:
        """Обновляет конфигурацию кодовой базы"""
        config = await self.get_codebase_config(user_id, codebase_id)
        if not config:
            return False
        
        # Обновляем поля
        for key, value in updates.items():
            if key in ["name", "description"]:
                config[key] = value
            elif key == "access_type":
                config["access"]["type"] = value
            elif key == "shared_with":
                config["access"]["shared_with"] = value
            elif key == "ai_provider":
                config["ai_settings"]["provider"] = value
            elif key == "ai_model":
                config["ai_settings"]["model"] = value
            elif key == "ai_params":
                config["ai_settings"]["custom_params"] = value
        
        config["updated_at"] = datetime.now().isoformat()
        
        # Сохраняем
        config_file = self._get_codebase_config_file(user_id, codebase_id)
        async with self._lock:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        
        # Обновляем имя в списке если изменилось
        if "name" in updates:
            user_codebases = await self.get_user_codebases(user_id)
            if codebase_id in user_codebases["codebases"]:
                user_codebases["codebases"][codebase_id]["name"] = updates["name"]
                list_file = self._get_user_codebases_file(user_id)
                with open(list_file, "w", encoding="utf-8") as f:
                    json.dump(user_codebases, f, ensure_ascii=False, indent=2)
        
        return True
    
    async def set_active_codebase(self, user_id: str, codebase_id: str) -> bool:
        """Устанавливает активную кодовую базу"""
        user_codebases = await self.get_user_codebases(user_id)
        
        if codebase_id not in user_codebases["codebases"]:
            return False
        
        user_codebases["active"] = codebase_id
        
        list_file = self._get_user_codebases_file(user_id)
        async with self._lock:
            with open(list_file, "w", encoding="utf-8") as f:
                json.dump(user_codebases, f, ensure_ascii=False, indent=2)
        
        return True
    
    async def delete_codebase(self, user_id: str, codebase_id: str) -> bool:
        """Удаляет кодовую базу"""
        try:
            # Удаляем директорию
            codebase_dir = self._get_codebase_dir(user_id, codebase_id)
            if os.path.exists(codebase_dir):
                shutil.rmtree(codebase_dir)
            
            # Удаляем из списка
            user_codebases = await self.get_user_codebases(user_id)
            if codebase_id in user_codebases["codebases"]:
                del user_codebases["codebases"][codebase_id]
                
                # Если удаляем активную, сбрасываем
                if user_codebases["active"] == codebase_id:
                    user_codebases["active"] = None
                    # Делаем активной первую из оставшихся
                    if user_codebases["codebases"]:
                        user_codebases["active"] = list(user_codebases["codebases"].keys())[0]
                
                list_file = self._get_user_codebases_file(user_id)
                async with self._lock:
                    with open(list_file, "w", encoding="utf-8") as f:
                        json.dump(user_codebases, f, ensure_ascii=False, indent=2)
            
            return True
            
        except Exception as e:
            print(f"Ошибка удаления кодовой базы: {e}")
            return False
    
    async def remove_public_codebase(self, user_id: str, virtual_id: str) -> bool:
        """Удаляет публичную базу из списка пользователя"""
        return await self.public_manager.remove_public_codebase(user_id, virtual_id, self.user_manager)


    async def get_public_codebase_users(self, public_id: str) -> List[Dict[str, Any]]:
        """Получает список пользователей с доступом к публичной базе"""
        return await self.public_manager.get_public_codebase_users(public_id, self.user_manager.users_dir)


    async def get_live_stats(self, user_id: str, codebase_id: str) -> tuple[int, int]:
        """Возвращает (files_count, total_size) по факту, а не из кэша config['stats']"""
    
        # Определяем реальные параметры для получения статистики
        real_user_id = user_id
        real_codebase_id = codebase_id
    
        # Проверяем, не является ли это публичной ссылкой
        if codebase_id.startswith("pub_"):
            # Для публичных баз получаем статистику у владельца
            list_file = self._get_user_codebases_file(user_id)
            if os.path.exists(list_file):
                with open(list_file, "r", encoding="utf-8") as f:
                    user_codebases = json.load(f)
                    cb_info = user_codebases.get("codebases", {}).get(codebase_id)
                
                    if cb_info and cb_info.get("is_public_ref"):
                        owner_id = cb_info["owner_id"]
                    
                        # Получаем реальный ID базы через реестр
                        registry_file = os.path.join(self.user_manager.users_dir, "public_codebases.json")
                        if os.path.exists(registry_file):
                            with open(registry_file, "r", encoding="utf-8") as f:
                                registry = json.load(f)
                                pub_info = registry.get(cb_info["public_id"])
                            
                                if pub_info:
                                    # Используем параметры владельца
                                    real_user_id = owner_id
                                    real_codebase_id = pub_info["codebase_id"]
    
        # Получаем путь к файлам
        codebase_dir = self._get_codebase_dir(real_user_id, real_codebase_id)
        files_dir = os.path.join(codebase_dir, "files")
    
        # Подсчитываем статистику
        files_count = 0
        total_size = 0
    
        if os.path.exists(files_dir):
            for filename in os.listdir(files_dir):
                file_path = os.path.join(files_dir, filename)
                if os.path.isfile(file_path):
                    files_count += 1
                    try:
                        total_size += os.path.getsize(file_path)
                    except (OSError, IOError):
                        # Игнорируем ошибки доступа к файлу
                        pass
    
        return files_count, total_size

    def validate_codebase_name(self, name: str) -> tuple[bool, str]:
        """Валидация названия кодовой базы"""
        import re
    
        # Проверка длины
        if len(name) < 3 or len(name) > 50:
            return False, "Название должно быть от 3 до 50 символов"
    
        # Проверка на допустимые символы (русские/английские буквы, цифры, пробел, дефис)
        pattern = r'^[a-zA-Zа-яА-ЯёЁ0-9\s\-]+$'
        if not re.match(pattern, name):
            return False, "Используйте только буквы (рус/англ), цифры, пробелы и дефис"
    
        # Проверка что не только пробелы/дефисы
        if name.replace(" ", "").replace("-", "") == "":
            return False, "Название не может состоять только из пробелов и дефисов"
    
        # Проверка что начинается с буквы или цифры
        if not name[0].isalnum():
            return False, "Название должно начинаться с буквы или цифры"
    
        return True, ""

    def get_rag_params_for_codebase(self, user_id: str, codebase_id: str, cb_info: dict = None) -> tuple:
        """
        Получает правильные параметры для RAG индекса
        Для публичных баз возвращает параметры владельца
        """
        # Если cb_info не передан, получаем его
        if cb_info is None:
            list_file = self._get_user_codebases_file(user_id)
            if os.path.exists(list_file):
                with open(list_file, "r", encoding="utf-8") as f:
                    user_codebases = json.load(f)
                    cb_info = user_codebases.get("codebases", {}).get(codebase_id, {})
            else:
                cb_info = {}
    
        if cb_info.get("is_public_ref"):
            # Это публичная база - получаем данные владельца
            owner_id = cb_info.get("owner_id")
            registry_file = os.path.join(self.user_manager.users_dir, "public_codebases.json")
        
            if os.path.exists(registry_file):
                with open(registry_file, "r", encoding="utf-8") as f:
                    registry = json.load(f)
                    pub_info = registry.get(cb_info.get("public_id"))
                    if pub_info:
                        return owner_id, pub_info["codebase_id"]
        
            # Fallback на локальные параметры
            return user_id, codebase_id
        else:
            # Это своя база
            return user_id, codebase_id
