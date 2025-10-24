# code/utils/codebase_utils.py

import os
import json
from typing import Dict, Any, List, Optional, Tuple

import logging
logger = logging.getLogger(__name__)

def _get_owner_config(user_id: str, codebase_id: str) -> Optional[Dict]:
    """
    Получает полную конфигурацию кодовой базы владельца для публичных баз.
    Для обычных баз возвращает None.
    """
    if not codebase_id.startswith("pub_"):
        return None
    
    try:
        from config import Config
        public_id = codebase_id[4:]
        users_dir = Config.USERS_DIR
        
        # Читаем информацию о публичной ссылке
        user_dir = os.path.join(users_dir, user_id)
        codebases_file = os.path.join(user_dir, "codebases.json")
        
        if not os.path.exists(codebases_file):
            return None
            
        with open(codebases_file, "r", encoding="utf-8") as f:
            user_codebases = json.load(f)
            cb_info = user_codebases.get("codebases", {}).get(codebase_id, {})
            
            if not cb_info.get("is_public_ref"):
                return None
                
            owner_id = cb_info.get("owner_id")
            
            # Получаем информацию из реестра
            registry_file = os.path.join(users_dir, "public_codebases.json")
            if not os.path.exists(registry_file):
                return None
                
            with open(registry_file, "r", encoding="utf-8") as f:
                registry = json.load(f)
                pub_info = registry.get(public_id)
                
                if not pub_info:
                    return None
                    
                real_codebase_id = pub_info.get("codebase_id")
                
                # Получаем конфигурацию владельца
                owner_dir = os.path.join(users_dir, owner_id)
                owner_codebases_file = os.path.join(owner_dir, "codebases.json")
                
                if not os.path.exists(owner_codebases_file):
                    return None
                    
                with open(owner_codebases_file, "r", encoding="utf-8") as f:
                    owner_codebases = json.load(f)
                    owner_cb_info = owner_codebases.get("codebases", {}).get(real_codebase_id, {})
                    folder_name = owner_cb_info.get("folder_name")
                    
                    if not folder_name:
                        return None
                        
                    # Читаем config.json владельца
                    config_file = os.path.join(owner_dir, "codebases", folder_name, "config.json")
                    if os.path.exists(config_file):
                        with open(config_file, "r", encoding="utf-8") as f:
                            return json.load(f)
                            
    except Exception as e:
        logger.error(f"Ошибка получения конфигурации владельца: {e}")
        
    return None


def _get_owner_params_and_settings(user_id: str, codebase_id: str) -> Tuple[str, str, Optional[Dict]]:
    """
    Получает параметры владельца и его RAG настройки для публичных баз.
    Возвращает (owner_id, real_codebase_id, rag_settings).
    Для обычных баз возвращает исходные параметры.
    """
    if not codebase_id.startswith("pub_"):
        return user_id, codebase_id, None
    
    try:
        from config import Config
        public_id = codebase_id[4:]
        users_dir = Config.USERS_DIR
        
        # Читаем информацию о публичной ссылке
        user_dir = os.path.join(users_dir, user_id)
        codebases_file = os.path.join(user_dir, "codebases.json")
        
        if not os.path.exists(codebases_file):
            return user_id, codebase_id, None
            
        with open(codebases_file, "r", encoding="utf-8") as f:
            user_codebases = json.load(f)
            cb_info = user_codebases.get("codebases", {}).get(codebase_id, {})
            
            if not cb_info.get("is_public_ref"):
                return user_id, codebase_id, None
                
            owner_id = cb_info.get("owner_id")
            
            # Получаем информацию из реестра
            registry_file = os.path.join(users_dir, "public_codebases.json")
            if not os.path.exists(registry_file):
                return user_id, codebase_id, None
                
            with open(registry_file, "r", encoding="utf-8") as f:
                registry = json.load(f)
                pub_info = registry.get(public_id)
                
                if not pub_info:
                    return user_id, codebase_id, None
                    
                real_codebase_id = pub_info.get("codebase_id")
                
                # Получаем полную конфигурацию владельца
                owner_config = _get_owner_config(user_id, codebase_id)
                
                if owner_config:
                    rag_settings = owner_config.get("rag_settings")
                    return owner_id, real_codebase_id, rag_settings
                else:
                    return owner_id, real_codebase_id, None
                            
    except Exception as e:
        logger.error(f"Ошибка получения параметров владельца: {e}")
        
    return user_id, codebase_id, None