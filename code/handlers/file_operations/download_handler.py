# code/handlers/file_operations/download_handler.py
"""
Модуль обработки скачивания файлов
"""
import io
import re
import logging
from zipfile import ZipFile, ZIP_DEFLATED
from aiogram import types
from aiogram.fsm.context import FSMContext

from .states import FileStates
from .base import BaseFileHandler

from utils.markdown_utils import escape_markdown_v2

logger = logging.getLogger(__name__)


class FileDownloadHandler(BaseFileHandler):
    """Обработчик скачивания файлов"""
    
    async def cmd_download_files(self, message: types.Message, state: FSMContext):
        """Начинает процесс скачивания файлов"""
        user_id = str(message.from_user.id)
    
        if not await self.user_manager.is_active(user_id):
            await message.reply("У вас нет доступа к боту\\.", parse_mode="MarkdownV2")
            return
    
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        if not user_codebases["active"]:
            text = (
                "❌ Нет активной кодовой базы\\.\n"
                "Выберите кодовую базу командой /switch"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        # Проверяем права доступа для публичных баз
        codebase_id = user_codebases["active"]
        cb_info = user_codebases["codebases"].get(codebase_id, {})
    
        if cb_info.get("is_public_ref"):
            config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
            base_name = escape_markdown_v2(config['name']) if config else "Неизвестная база"
        
            text = (
                "❌ *Скачивание файлов недоступно\\!*\n\n"
                f"📂 База: {base_name}\n"
                f"🔒 Статус: Чужая публичная база\n\n"
                "Ограничения для пользователей:\n"
                "❌ Прямое скачивание файлов\n"
                "❌ Просмотр списка файлов\n"
                "❌ Изменение или удаление файлов\n\n"
                "Доступные возможности:\n"
                "✅ Использование /agents для анализа кода\n"
                "✅ Поиск через RAG\\-индекс\n"
                "✅ Чтение содержимого через агентов\n\n"
                "_Владелец базы защитил прямой доступ к файлам\\._"
            )
            await message.reply(text, parse_mode="MarkdownV2")
            return
    
        text = (
            "📥 Введите имена файлов для скачивания через запятую\\.\n"
            "Пример: file1\\.txt, script\\.py\n\n"
            "Или введите номера файлов из списка /files\n"
            "Пример: 1, 3, 5\n\n"
            "Или отправьте '\\*' чтобы выбрать все файлы\n"
            "⚠️ Можно скачать до 10 файлов за раз\n\n"
            "/cancel\\_file\\_job \\- отмена"
        )
        await message.reply(text, parse_mode="MarkdownV2")
        await state.set_state(FileStates.selecting_files_to_download)
    
    async def process_files_to_download(self, message: types.Message, state: FSMContext):
        """Обработка выбора файлов для скачивания"""
        user_id = str(message.from_user.id)
        text = message.text.strip()
    
        if text.lower() == "/cancel_file_job":
            await state.clear()
            await message.reply("❌ Скачивание отменено\\.", parse_mode="MarkdownV2")
            return
    
        user_codebases = await self.codebase_manager.get_user_codebases(user_id)
        codebase_id = user_codebases["active"]
    
        # Дополнительная проверка прав
        cb_info = user_codebases["codebases"].get(codebase_id, {})
        if cb_info.get("is_public_ref"):
            await state.clear()
            text_reply = (
                "❌ Операция отменена\\.\n"
                "Скачивание файлов из чужой публичной базы запрещено\\."
            )
            await message.reply(text_reply, parse_mode="MarkdownV2")
            return
    
        all_files_data = await self.file_manager.list_files(user_id, codebase_id, 1, per_page=10000)
        all_files = all_files_data['files']
    
        files_to_download = []
    
        # Обработка звездочки - все файлы
        if text == "*":
            total_count = len(all_files)
            if total_count == 0:
                await message.reply("❌ В кодовой базе нет файлов\\.", parse_mode="MarkdownV2")
                await state.clear()
                return
        
            if total_count > 5:
                # Создаем ZIP архив для большого количества файлов
                await self._send_files_as_zip(message, user_id, codebase_id, all_files)
                await state.clear()
                return
        
            files_to_download = [f['name'] for f in all_files][:10]
        else:
            # Проверяем, содержит ли текст только цифры, запятые и дефисы (номера)
            text_norm = text.replace(" ", "")
            if re.match(r'^[\d,\-\s]+$', text_norm):
                # Обработка номеров
                files_to_download = self._parse_file_indices(text_norm, all_files)
            else:
                # Обработка имен файлов
                files_to_download = self._parse_file_names(text, all_files)
    
        if not files_to_download:
            text_reply = (
                "❌ Файлы не найдены\\. Убедитесь что:\n"
                "• Имя файла указано точно \\(включая расширение\\)\n"
                "• Или используйте номера из списка /files\n"
                "Попробуйте еще раз:"
            )
            await message.reply(text_reply, parse_mode="MarkdownV2")
            return
    
        # Отправляем файлы
        await self._send_files(message, user_id, codebase_id, files_to_download)
        await state.clear()
  
    def _parse_file_indices(self, text_norm: str, all_files: list) -> list:
        """Парсит номера файлов из текста"""
        parts = text_norm.split(",")
        indices = []
        
        for part in parts:
            if "-" in part:
                try:
                    start, end = map(int, part.split("-"))
                    if start > end:
                        start, end = end, start
                    indices.extend(range(start, end + 1))
                except ValueError:
                    continue
            else:
                try:
                    indices.append(int(part))
                except ValueError:
                    continue
        
        files_to_download = []
        for idx in indices[:10]:
            if 1 <= idx <= len(all_files):
                files_to_download.append(all_files[idx - 1]['name'])
        
        return files_to_download
    
    def _parse_file_names(self, text: str, all_files: list) -> list:
        """Парсит имена файлов из текста"""
        requested_names = [name.strip() for name in text.split(",") if name.strip()]
        files_to_download = []
        
        for requested_name in requested_names[:10]:
            # Ищем точное совпадение
            found = False
            for f in all_files:
                if f['name'] == requested_name:
                    files_to_download.append(f['name'])
                    found = True
                    break
            
            # Если точного совпадения нет, пробуем частичное
            if not found:
                for f in all_files:
                    if requested_name.lower() in f['name'].lower():
                        files_to_download.append(f['name'])
                        found = True
                        break
            
            if not found:
                logger.warning(f"Файл '{requested_name}' не найден")
        
        return files_to_download

    async def _send_files(self, message: types.Message, user_id: str, codebase_id: str, filenames: list):
        """Отправляет файлы пользователю"""
        sent = 0
        not_sent = []
    
        for filename in filenames:
            file_data = await self.file_manager.get_file(user_id, codebase_id, filename)
            if file_data:
                try:
                    caption_escaped = f"📎 {escape_markdown_v2(filename)}"
                    await message.reply_document(
                        types.BufferedInputFile(file_data, filename),
                        caption=caption_escaped,
                        parse_mode="MarkdownV2"
                    )
                    sent += 1
                except Exception as e:
                    logger.error(f"Ошибка отправки файла {filename}: {e}")
                    not_sent.append(filename)
    
        sent_escaped = escape_markdown_v2(str(sent))
        total_escaped = escape_markdown_v2(str(len(filenames)))
    
        result_msg = f"✅ Отправлено файлов: {sent_escaped}/{total_escaped}"
        if not_sent:
            result_msg += f"\n❌ Не удалось отправить:\n"
            for f in not_sent:
                result_msg += f"• {escape_markdown_v2(f)}\n"
        result_msg += "\n\n/files \\- список файлов"
    
        await message.reply(result_msg, parse_mode="MarkdownV2")    
   
    async def _send_files_as_zip(self, message: types.Message, user_id: str, codebase_id: str, all_files: list):
        """Отправляет все файлы в виде ZIP архива"""
        buf = io.BytesIO()
        total_count = len(all_files)
    
        with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
            for f in all_files:
                file_name = f['name']
                file_bytes = await self.file_manager.get_file(user_id, codebase_id, file_name)
                if file_bytes is None:
                    continue
                zf.writestr(file_name, file_bytes)
    
        buf.seek(0)
    
        config = await self.codebase_manager.get_codebase_config(user_id, codebase_id)
        base_name = (config['name'] if config else f"codebase_{codebase_id}") or f"codebase_{codebase_id}"
        safe_base = re.sub(r'[^A-Za-z0-9_\-]+', '_', base_name).strip('_') or "codebase"
        zip_name = f"{safe_base}_all_{total_count}.zip"
    
        try:
            total_escaped = escape_markdown_v2(str(total_count))
            caption = f"📦 Архив всех файлов кодовой базы \\({total_escaped} шт\\.\\)"
        
            await message.reply_document(
                types.BufferedInputFile(buf.read(), zip_name),
                caption=caption,
                parse_mode="MarkdownV2"
            )
            await message.reply("✅ Готово\\! /files — список файлов", parse_mode="MarkdownV2")
        except Exception as e:
            logger.error(f"Ошибка отправки архива {zip_name}: {e}")
            text = "❌ Не удалось отправить архив\\. Попробуйте скачать по частям\\."
            await message.reply(text, parse_mode="MarkdownV2")    