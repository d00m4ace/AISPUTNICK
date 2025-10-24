# code/handlers/file_operations/states.py
"""
FSM состояния для файловых операций
"""
from aiogram.fsm.state import State, StatesGroup


class FileStates(StatesGroup):
    """Состояния для операций с файлами"""
    # Загрузка файлов
    waiting_for_replacement = State()
    selecting_encoding = State()
    processing_pdf = State()
    
    # Управление файлами
    selecting_files_to_delete = State()
    selecting_files_to_download = State()
    searching_files = State()