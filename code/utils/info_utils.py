# code/utils/info_utils.py

import os
import json
from typing import Dict, Any, List, Optional, Tuple
from aiogram import types

from .markdown_utils import escape_markdown_v2

def info_agent_processing(agent_name: str) -> str:
    """Сообщение о начале обработки запроса агентом"""
    return f"💭 *@{escape_markdown_v2(agent_name)}* обрабатывает запрос\\.\\.\\."

def info_agent_not_found(agent_name: str) -> str:
    """Сообщение о том, что агент не найден"""
    return f"⚠ Агент @{escape_markdown_v2(agent_name)} не найден"

def info_agent_success(agent_name: str) -> str:
    """Сообщение об успешном выполнении агента"""
    return f"✅ *@{escape_markdown_v2(agent_name)}* выполнил запрос\\."

def info_agent_error(error_text: str) -> str:
    """Сообщение об ошибке выполнения агента"""
    return f"⚠ Ошибка при выполнении агента: {error_text}"

def info_agent_result_too_large(agent_name: str) -> str:
    """Сообщение когда ответ слишком большой и сохранен в файл"""
    return f"✅ *@{escape_markdown_v2(agent_name)}* выполнил запрос\\.\nОтвет слишком большой и сохранен в файл\\."

def info_invalid_format() -> str:
    """Сообщение о неверном формате команды"""
    return "⚠ Неверный формат\\. Используйте: @имя\\_агента запрос"

def info_invalid_agent_response() -> str:
    """Сообщение о неверном формате ответа от агента"""
    return "⚠ Неверный формат ответа от агента"

def info_no_access() -> str:
    """Сообщение об отсутствии доступа к боту"""
    return "У вас нет доступа к боту."

def info_unprocessed_message_in_state(state: str, text: str) -> str:
    """Сообщение о необработанном сообщении в состоянии"""
    return "❌ Произошла ошибка обработки. Попробуйте еще раз или используйте /cancel для отмены."

def info_system_agent_immutable(agent_name: str) -> str:
    """Сообщение о невозможности изменить системного агента"""
    return f"⚠ Нельзя изменить системного агента @{escape_markdown_v2(agent_name)}"

def info_not_public_agent_owner(agent_name: str) -> str:
    """Сообщение о том, что пользователь не владелец публичного агента"""
    return f"⚠ Вы не владелец публичного агента @{escape_markdown_v2(agent_name)}"

def info_public_agent_saved(agent_name: str, type_indicator: str = "") -> str:
    """Сообщение о сохранении публичного агента"""
    return f"✅ Публичный агент *@{escape_markdown_v2(agent_name)}*{escape_markdown_v2(type_indicator)} сохранен"

def info_private_agent_saved(agent_name: str, type_indicator: str = "") -> str:
    """Сообщение о сохранении личного агента"""
    return f"✅ Личный агент *@{escape_markdown_v2(agent_name)}*{escape_markdown_v2(type_indicator)} сохранен"

def info_invalid_config_format() -> str:
    """Сообщение о неверном формате конфигурации"""
    return "⚠ Неверный формат конфигурации\\. Необходимые поля: name, description"

def info_agent_name_not_determined() -> str:
    """Сообщение о невозможности определить имя агента"""
    return "⚠ Не удалось определить имя агента"

def info_json_parse_error() -> str:
    """Сообщение об ошибке парсинга JSON"""
    return "⚠ Ошибка парсинга JSON файла"

def info_agent_config_error(error: str) -> str:
    """Сообщение об ошибке конфигурации агента"""
    return f"⚠ Ошибка: {escape_markdown_v2(error)}"

def info_agent_config_caption(agent_name: str) -> str:
    """Подпись для файла конфигурации агента"""
    return f"📄 Конфигурация агента *@{escape_markdown_v2(agent_name)}*\n\nВы можете отредактировать этот файл и отправить обратно для обновления агента\\."

def info_upload_preparing() -> str:
    """Сообщение о подготовке к загрузке"""
    return "📥 *Подготовка к загрузке\\.\\.\\.*"

def info_upload_error(error: str) -> str:
    """Сообщение об ошибке загрузки"""
    return f"❌ Ошибка загрузки: {escape_markdown_v2(error)}"

def info_zip_agent_expects_archive() -> str:
    """Сообщение о том, что ZIP агент ожидает архив"""
    info = "⚠️ *Агент @zip ожидает архив*\n\n"
    info += "Отправьте \\.zip или \\.7z файл\n"
    info += "Или используйте /agent\\_stop для выхода"
    return info

def info_upload_agent_expects_url() -> str:
    """Сообщение о том, что Upload агент ожидает URL"""
    info = "⚠️ *Агент @upload ожидает ссылку*\n\n"
    info += "Отправьте URL файла для скачивания\n"
    info += "Или используйте /agent\\_stop для выхода"
    return info

def info_active_file_processing() -> str:
    """Сообщение о наличии активной задачи обработки файлов"""
    return "⚠️ У вас есть активная задача обработки файлов.\nДождитесь её завершения перед загрузкой новых файлов."

def info_archive_agent_help(agent_name: str) -> str:
    """Справка по архивному агенту"""
    info = "📦 *Тип:* Обработка архивов\n\n"
    info += "*Использование:*\n"
    info += f"`@{agent_name}` \\- активировать агент\n"
    info += "Затем отправьте \\.zip или \\.7z архив\n\n"
    info += "*Возможности:*\n"
    info += "• Распаковка ZIP и 7z архивов\n"
    info += "• Автоматическое определение кодировки\n"
    info += "• Сохранение текстовых файлов в базу\n"
    info += "• Преобразование путей в безопасные имена\n"
    return info

def info_rag_agent_help(agent_name: str) -> str:
    """Справка по RAG агенту"""
    info = "🔍 *Тип:* Поиск по базе знаний\n\n"
    info += "*Использование:*\n"
    info += f"`@{agent_name} ваш вопрос` \\- поиск ответа в базе\n\n"
    info += "*Примеры запросов:*\n"
    info += f"• `@{agent_name} как работает функция X?`\n"
    info += f"• `@{agent_name} найди примеры использования Y`\n"
    info += f"• `@{agent_name} объясни алгоритм Z`\n\n"
    info += "💡 *Совет:* Можете загрузить документ для анализа\\.\n"
    info += "Просто отправьте текстовый файл после использования агента\\."
    return info

def info_chat_agent_help(agent_name: str) -> str:
    """Справка по чат агенту"""
    info = "💬 *Тип:* Чат с ИИ\n\n"
    info += "*Использование:*\n"
    info += f"`@{agent_name}` \\- начать чат\\-сессию\n"
    info += f"`@{agent_name} привет` \\- начать с приветствия\n\n"
    info += "*В режиме чата:*\n"
    info += "• Все сообщения отправляются агенту\n"
    info += "• Можно загружать текстовые файлы\n"
    info += "• История сохраняется между сообщениями\n"
    info += "• `/stop_chat` \\- завершить чат\n"
    return info

def info_fileworker_agent_help(agent_name: str) -> str:
    """Справка по fileworker агенту"""
    info = "📂 *Тип:* Пакетная обработка файлов\n\n"
    info += "*Использование:*\n"
    info += f"`@{agent_name} селектор_файлов`\n"
    info += "`запрос для обработки`\n\n"
    info += "*Примеры селекторов:*\n"
    info += "• `*` \\- все файлы\n"
    info += "• `*.py` \\- все Python файлы\n"
    info += "• `1,3,5` \\- файлы с номерами\n"
    info += "• `test_*.js` \\- файлы по маске\n\n"
    info += "*Пример:*\n"
    info += f"`@{agent_name} *.py`\n"
    info += "`найди все функции`"
    return info

def info_generic_agent_help(agent_name: str, agent_type: str) -> str:
    """Справка по агенту с неизвестным типом"""
    info = f"*Тип:* {escape_markdown_v2(agent_type)}\n\n"
    info += "*Использование:*\n"
    info += f"`@{agent_name} ваш запрос`\n"
    return info

def info_system_agent_help(agent_name: str) -> str:
    """Справка по системному агенту"""
    info = "Системный агент\n\n"
    info += "*Использование:*\n"
    info += f"`@{agent_name} ваш запрос`\n"
    return info

def info_agent_help_header(agent_name: str) -> str:
    """Заголовок справки по агенту"""
    return f"ℹ️ *Агент @{escape_markdown_v2(agent_name)}*\n\n"

def info_agent_description(description: str) -> str:
    """Описание агента"""
    return f"📝 *Описание:* {escape_markdown_v2(description)}\n\n"

def info_agent_config_command(agent_name: str) -> str:
    """Команда для получения конфигурации агента"""
    return f"\n`@{agent_name} config` \\- скачать конфигурацию агента"

def info_global_help_message() -> str:
    info = "🤖 *Доступные команды бота:*\n\n"
    info += "/start \\- начать работу с ботом\n"
    info += "/help \\- показать эту справку\n"
    info += "/settings \\- настройки профиля и верификация email\n"
    info += "/codebases \\- список ваших кодовых баз\n"
    info += "/active \\- показать активную кодовую базу\n"
    info += "/agents \\- справка по агентам\n"
    info += "/agents\\_pub \\- публичные агенты\n"
    info += "/agents\\_user \\- ваши личные агенты\n"
    info += "@macros \\- справка по макро командам\n"
    return info

def info_chat_help_message() -> str:
    """Получение текста справки по командам управления историей"""
    info = "📚 *Управление историей чата:*\n"
    info += "`save [ID]` \\- сохранить текущую историю\n"
    info += "`load [ID]` \\- загрузить сохраненную историю\n"
    info += "`delete [ID]` \\- удалить сохраненную историю\n"
    info += "`rename [старый] [новый]` \\- переименовать историю\n"
    info += "`list` \\- показать список сохраненных историй\n\n"
    info += "*Примеры:*\n"
    info += "`save project_v1` \\- сохранить как project\\_v1\n"
    info += "`load project_v1` \\- загрузить project\\_v1\n"
    info += "`rename project_v1 project_final`\n\n"
    info += "💡 ID может содержать буквы, цифры, \\_ и \\-"
    return info

def info_welcome_chat_message(agent_name: str) -> str:
    info = f"💬 *Чат с @{agent_name} активирован*\n\n"
    info += "Теперь все ваши сообщения будут отправляться этому агенту\\.\n"
    info += "\n*Возможности:*\n"
    info += "• 💬 Отправляйте текстовые сообщения для диалога\n"
    info += "• 📎 Отправьте текстовый файл для добавления в контекст\n"
    info += "• 📄 Загружайте несколько файлов для работы с ними\n"
    info += "• ⛔ Используйте /agent\\_stop для завершения чата\n"
    return info

def info_nocmd_chat_message(agent_name: str, cmd: str) -> str:
    info = f"💬 *Чат с @{agent_name} активирован*\n\n"
    info += f"Команда {cmd} не найдена или не поддерживается в чате\\.\n"
    return info

def info_cmd_chat_message() -> str:
    info = "🤖 *Команды управления чатом:*\n"
    info += "• /clear\\_history \\- очистить историю и файлы\n"
    info += "• /export\\_history \\- экспорт в файл\n"
    info += "• /history\\_info \\- информация и статистика\n"
    info += "• /agent\\_stop \\- завершить чат и очистить контексты\n"
    return info

def info_upload_help_message() -> str:
    info = "📥 *Агент @upload \\- Загрузчик файлов*\n\n"
    info += "*Использование:*\n"
    info += "`@upload URL` \\- скачать и обработать файл по публичной ссылке\n\n"
    info += "*Примеры:*\n"
    info += "`@upload https://example\\.com/document\\.pdf`\n"
    info += "`@upload https://site\\.com/audio\\.mp3`\n"
    info += "`@upload https://raw\\.githubusercontent\\.com/user/repo/main/file\\.py`\n"
    info += "`@upload https://drive\\.google\\.com/file/d/FILE_ID/view`\n"
    info += "`@upload https://disk\\.yandex\\.ru/d/XXXXXX`\n\n"
    info += "*Поддерживаемые типы:*\n"
    info += "• PDF, Word, Excel, PowerPoint\n"
    info += "• Аудио файлы \\(транскрипция\\)\n"
    info += "• Изображения \\(OCR\\)\n"
    info += "• Текстовые файлы и код\n"
    info += "• HTML, JSON и XML документы\n"
    info += "• Архивы \\(zip, 7z\\) — обрабатываются автоматически\n\n"
    info += "*Особенности:*\n"
    info += "• Автоматическое определение типа файла\n"
    info += "• Поддержка загрузки по публичным ссылкам \\(Google Drive, Яндекс\\.Диск, Dropbox, GitHub\\)\n"
    info += "• Конвертация документов в Markdown\n"
    info += "• Транскрипция аудио в текст\n"
    info += "• OCR распознавание текста на изображениях\n"
    info += "• Распаковка архивов и сохранение содержимого\n"
    info += "• Сохранение файлов в активную кодовую базу\n"
    info += "• Автоматическая индексация для RAG\n\n"
    info += "*Ограничения:*\n"
    info += "• Максимальный размер: 100 МБ\n"
    info += "• Протоколы: HTTP, HTTPS\n"
    info += "• Таймаут: 60 секунд\n"
    return info

    