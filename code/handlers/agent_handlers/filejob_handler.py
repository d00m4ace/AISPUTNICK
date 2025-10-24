# code/handlers/agent_handlers/filejob_handler.py
import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from utils.markdown_utils import escape_markdown_v2

from time import perf_counter
from user_activity_logger import activity_logger

logger = logging.getLogger(__name__)

class FilejobAgentHandler:
    """Обработчик для filejob агентов"""
    
    def __init__(self, parent_handler):
        self.parent = parent_handler
        self.bot = parent_handler.bot
        
    def has_active_jobs(self, user_id: str) -> bool:
        """Проверяет наличие активных задач у пользователя"""
        for job_id, job_info in self.parent.system_agents.get('filejob', {}).active_jobs.items():
            if job_info['user_id'] == user_id and not job_info.get('cancelled', False):
                return True
        return False

    async def process_fileworker_agent(self, message: types.Message, user_id: str,
                                       agent_name: str, query: str, agent, cont=None):
        """Обработка агентов типа fileworker с прогрессом и возможностью отмены"""
    
        if not query:
            help_text = f"""@{agent_name} - Пакетная обработка файлов

    Формат использования:
    @filejob селектор_файлов
    запрос для применения к каждому файлу

    Примеры селекторов:
    - * - все файлы
    - *.py - все Python файлы
    - 1,3,5 - файлы с номерами 1, 3 и 5
    - 2-10 - файлы с 2 по 10
    - test_*.js - файлы по маске
    - main.py, utils.py - конкретные файлы

    Пример:
    @filejob *.py
    Найди все функции и опиши что они делают"""
        
            await message.reply(help_text, parse_mode=None)
            return
    
        # Создаем предварительный job_id для отслеживания
        job_id = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
        # Кнопка отмены
        cancel_button = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отменить обработку", callback_data=f"cancel_job_{job_id}")
        ]])
    
        progress_msg = await message.reply(
            "📄 Начинаю обработку файлов...\n\n"
            "Анализ селектора и подготовка...",
            reply_markup=cancel_button
        )
    
        try:
            context = {
                'codebase_manager': self.parent.codebase_manager,
                'file_manager': self.parent.file_manager,
                'ai_interface': self.parent.ai_interface,
                'user_manager': self.parent.user_manager,
                'message': message  # Передаем message для возможности отправки архива
            }

            # Если передан дополнительный контекст, объединяем
            if cont:
                context.update(cont)
        
            # Сохраняем job_id в агенте перед началом обработки
            agent.current_job_id = job_id

            activity_logger.log(user_id, "AGENT_CALL_START", f"agent={agent_name},type=fileworker,job_id={job_id}")
            t0 = perf_counter()
        
            # Запускаем обработку в отдельной корутине
            async def process_with_progress():
                try:
                    # Запускаем обработку
                    result = await agent.process(user_id, query, context)
                
                    # Проверяем формат результата
                    if isinstance(result, tuple) and len(result) >= 2:
                        success = result[0]
                        status_msg = result[1]
                        # Третий элемент может быть путем к архиву, текстом или None
                        third_element = result[2] if len(result) > 2 else None
                        return success, status_msg, third_element
                    else:
                        return False, "Неверный формат ответа от агента", None
                except Exception as e:
                    logger.error(f"Ошибка в process_with_progress: {e}")
                    return False, str(e), None
        
            # Функция обновления прогресса
            async def update_progress():
                try:
                    # Ждем пока задача появится в active_jobs
                    wait_count = 0
                    while job_id not in agent.active_jobs and wait_count < 10:
                        await asyncio.sleep(0.5)
                        wait_count += 1
                
                    if job_id not in agent.active_jobs:
                        logger.warning(f"Задача {job_id} не найдена в active_jobs")
                        return
                
                    # Обновляем прогресс
                    while job_id in agent.active_jobs:
                        job_status = agent.get_job_status(job_id)
                    
                        # Проверяем, не отменена ли задача
                        if not job_status or job_status.get('cancelled'):
                            logger.debug(f"Задача {job_id} отменена, прекращаем обновление прогресса")
                            break
                    
                        processed = job_status.get('processed', 0)
                        files = job_status.get('files', [])
                        total = len(files)
                        status = job_status.get('status', 'processing')
                    
                        if total == 0:
                            progress_text = "📄 Подготовка к обработке..."
                        else:
                            progress_text = f"📄 Обработка файлов\n\n"
                            progress_text += f"Прогресс: {processed}/{total} файлов\n"
                        
                            # Прогресс-бар
                            progress_percent = int((processed / total) * 100) if total > 0 else 0
                            progress_bar_length = 20
                            filled = int(progress_bar_length * progress_percent / 100)
                            bar = '█' * filled + '░' * (progress_bar_length - filled)
                            progress_text += f"\n[{bar}] {progress_percent}%\n"
                        
                            # Текущий файл
                            if processed > 0 and processed <= total:
                                current_file = files[min(processed - 1, total - 1)]
                                progress_text += f"\nОбрабатывается: {current_file}"
                        
                            # Статус
                            if status == 'loading':
                                progress_text += "\n\n🔄 Загрузка файлов..."
                            elif status == 'processing':
                                progress_text += "\n\n⚙️ Обработка ИИ..."
                            elif status == 'archiving':
                                progress_text += "\n\n📦 Создание архива..."
                    
                        try:
                            # Обновляем только если задача НЕ отменена
                            if not job_status.get('cancelled'):
                                await progress_msg.edit_text(
                                    progress_text,
                                    reply_markup=cancel_button
                                )
                        except Exception:
                            pass  # Игнорируем ошибки обновления сообщения
                    
                        await asyncio.sleep(2)  # Обновляем каждые 2 секунды
                
                except asyncio.CancelledError:
                    logger.debug(f"Задача обновления прогресса для {job_id} была отменена")
                    return
                except Exception as e:
                    logger.error(f"Ошибка в update_progress: {e}")
                    return
        
            # Запускаем обработку и обновление прогресса параллельно
            process_task = asyncio.create_task(process_with_progress())
            progress_task = asyncio.create_task(update_progress())
        
            # Ждем завершения обработки
            result = await process_task

            # Проверяем результат
            if result:
                success, status_msg, third_element = result
                logger.info(f"FilejobAgent вернул: success={success}")
            else:
                success = False
                status_msg = "Ошибка при обработке"
                third_element = None
                logger.error("FilejobAgent вернул пустой результат")
        
            # Отменяем обновление прогресса
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
        
            # Проверяем результат
            if result:
                success, status_msg, third_element = result
            else:
                success = False
                status_msg = "Ошибка при обработке"
                third_element = None
        
            # Удаляем сообщение с прогрессом
            try:
                await progress_msg.delete()
            except:
                pass
        
            duration = perf_counter() - t0
            activity_logger.log(user_id, "AGENT_CALL_END", 
                               f"agent={agent_name},type=fileworker,job_id={job_id},success={success},duration={duration:.2f}s")
        
            # Обрабатываем результат
            if success:
                if third_element is None:
                    # Агент уже отправил архив самостоятельно (новое поведение)
                    # Просто показываем статус (уже отправлен агентом)
                    pass  # Архив уже отправлен, ничего не делаем
                
                elif isinstance(third_element, str) and os.path.exists(third_element):
                    # Это путь к архиву, который нужно отправить
                    try:
                        from aiogram.types import FSInputFile
                        archive_name = os.path.basename(third_element)
                        document = FSInputFile(third_element, filename=archive_name)
                    
                        await message.reply_document(
                            document,
                            caption=status_msg if len(status_msg) <= 1024 else status_msg[:1021] + "..."
                        )
                    
                        # Удаляем временный архив
                        try:
                            await asyncio.sleep(2)
                            os.remove(third_element)
                            temp_dir = os.path.dirname(third_element)
                            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                                os.rmdir(temp_dir)
                        except Exception as e:
                            logger.debug(f"Не удалось удалить временный архив: {e}")
                        
                    except Exception as e:
                        logger.error(f"Ошибка отправки архива: {e}")
                        await message.reply(f"✅ {status_msg}\n⚠️ Не удалось отправить архив: {str(e)}")
                    
                elif isinstance(third_element, str):
                    # Это текстовый результат (старое поведение для обратной совместимости)
                    file_content = f"# Результаты пакетной обработки файлов\n\n"
                    file_content += f"**Агент:** @{agent_name}\n"
                    file_content += f"**Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    file_content += f"**Запрос:** {query.split(chr(10))[1] if chr(10) in query else query[:100]}\n\n"
                    file_content += "---\n\n"
                    file_content += third_element
                
                    file_bytes = file_content.encode('utf-8')
                    input_file = BufferedInputFile(
                        file=file_bytes,
                        filename=f"filejob_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    )
                
                    await message.reply_document(
                        document=input_file,
                        caption="✅ Обработка завершена\n\n" + status_msg
                    )
                else:
                    # Просто статус без результата
                    await message.reply(status_msg, parse_mode="MarkdownV2")
            else:
                # Ошибка
                await message.reply(f"❌ {status_msg}")
            
        except Exception as e:
            logger.error(f"Ошибка при обработке fileworker агента {agent_name}: {e}", exc_info=True)
            try:
                await progress_msg.delete()
            except:
                pass
            await message.reply(f"❌ Ошибка: {str(e)}")
          
    async def handle_cancel_job(self, callback: types.CallbackQuery):
        """Обработчик отмены задачи обработки файлов"""
        job_id = callback.data.replace("cancel_job_", "")
        
        # Находим агент filejob
        if 'filejob' in self.parent.system_agents:
            filejob_agent = self.parent.system_agents['filejob']
            
            # Проверяем, есть ли задача
            job_status = filejob_agent.get_job_status(job_id)
            
            if job_status and not job_status.get('cancelled'):
                # Отменяем задачу
                if filejob_agent.cancel_job(job_id):
                    await callback.answer("Обработка отменяется...")
                    
                    # Обновляем сообщение БЕЗ кнопки
                    processed = job_status.get('processed', 0)
                    total = len(job_status.get('files', []))
                    
                    cancel_text = (
                        "⚠️ Обработка файлов отменена\n\n"
                        f"Обработано файлов: {processed}/{total}\n"
                        "Задача была прервана пользователем.\n"
                    )

                    activity_logger.log(str(callback.from_user.id), "AGENT_JOB_CANCELLED", f"agent=filejob,job_id={job_id}")
                    
                    if processed > 0:
                        cancel_text += "Обработанные файлы будут включены в результат."
                    
                    try:
                        # Важно: убираем reply_markup чтобы убрать кнопку
                        await callback.message.edit_text(
                            cancel_text,
                            reply_markup=None  # Убираем кнопку
                        )
                    except Exception as e:
                        logger.error(f"Ошибка обновления сообщения при отмене: {e}")
                else:
                    await callback.answer("Не удалось отменить задачу", show_alert=True)
            else:
                await callback.answer("Задача уже завершена или не найдена", show_alert=True)
        else:
            await callback.answer("Агент не найден", show_alert=True)