# code/handlers/agent_handlers/session_manager.py

import logging
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)

class SessionManager:
    """Управление активными сессиями и агентами"""
    
    def __init__(self, handler):
        self.handler = handler
    
    async def stop_all_active_agents(self, user_id: str, state: FSMContext):
        """
        Тихая остановка всех активных агентов и процессов для пользователя
        
        Args:
            user_id: ID пользователя
            state: FSM контекст
        """
        stopped_count = 0
        
        # 1. Останавливаем активный чат
        if hasattr(self.handler, 'chat_handler') and user_id in self.handler.chat_handler.active_chat_sessions:
            agent_name = self.handler.chat_handler.active_chat_sessions[user_id].get('agent_name', 'chat')
            del self.handler.chat_handler.active_chat_sessions[user_id]
            await state.clear()
            stopped_count += 1
            logger.debug(f"Автоостановка: чат с агентом {agent_name}")
        
        # 2. Останавливаем активные filejob задачи
        if 'filejob' in self.handler.system_agents:
            filejob_agent = self.handler.system_agents['filejob']
            jobs_to_cancel = []
            
            for job_id, job_info in filejob_agent.active_jobs.items():
                if job_info['user_id'] == user_id and not job_info.get('cancelled', False):
                    jobs_to_cancel.append(job_id)
            
            for job_id in jobs_to_cancel:
                if filejob_agent.cancel_job(job_id):
                    stopped_count += 1
                    logger.debug(f"Автоостановка: filejob задача {job_id}")
        
        # 3. Очищаем временные контексты RAG
        if 'rag' in self.handler.system_agents:
            rag_agent = self.handler.system_agents['rag']
            if hasattr(rag_agent, 'temp_document_context') and user_id in rag_agent.temp_document_context:
                del rag_agent.temp_document_context[user_id]
                stopped_count += 1
                logger.debug(f"Автоостановка: временный документ RAG")
        
        # 4. Завершаем активную nethack сессию
        if hasattr(self.handler, 'nethack_manager'):
            if self.handler.nethack_manager.has_active_session(user_id):
                self.handler.nethack_manager.deactivate_session(user_id)
                stopped_count += 1
                logger.debug(f"Автоостановка: nethack сессия")
        
        # 5. Очищаем файловые контексты
        files_cleared = False
        if hasattr(self.handler, 'chat_handler') and hasattr(self.handler.chat_handler, 'user_file_contexts'):
            if user_id in self.handler.chat_handler.user_file_contexts:
                del self.handler.chat_handler.user_file_contexts[user_id]
                files_cleared = True
        
        # Очищаем файлы в chat агенте
        if 'chat' in self.handler.system_agents:
            chat_agent = self.handler.system_agents['chat']
            if hasattr(chat_agent, 'user_file_contexts') and user_id in chat_agent.user_file_contexts:
                chat_agent.clear_user_files(user_id)
                files_cleared = True
        
        if files_cleared:
            stopped_count += 1
            logger.debug(f"Автоостановка: файловые контексты")
        
        # Логируем общий результат
        if stopped_count > 0:
            logger.info(f"Автоостановка: остановлено {stopped_count} процессов для пользователя {user_id}")