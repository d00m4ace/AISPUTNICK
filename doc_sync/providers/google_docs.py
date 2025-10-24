# doc_sync/providers/google_docs.py
import os
import json
import logging
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from typing import Dict, Optional, Tuple
from datetime import datetime
from .base import DocumentProvider

logger = logging.getLogger(__name__)

class GoogleDocsProvider(DocumentProvider):
    """Provider for Google Docs/Sheets/Slides with JSON export support"""
    
    SCOPES = [
        'https://www.googleapis.com/auth/drive.readonly',
        'https://www.googleapis.com/auth/documents.readonly',
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/presentations.readonly'
    ]
    
    def __init__(self, auth_config: Dict, export_config: Dict = None):
        """Initialize with optional export configuration"""
        # Set export_config BEFORE calling parent __init__
        self.export_config = export_config or {}
        self.sheets_json_exporter = None
        self.auth_config = auth_config
        # Now call setup_auth directly instead of parent __init__
        self.setup_auth()
        
    def setup_auth(self):
        service_account_file = self.auth_config.get('service_account_file')
    
        if not os.path.isabs(service_account_file):
            service_account_file = os.path.abspath(service_account_file)
    
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file, scopes=self.SCOPES
        )
    
        self.drive_service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
        self.docs_service = build('docs', 'v1', credentials=credentials, cache_discovery=False)
        self.sheets_service = build('sheets', 'v4', credentials=credentials, cache_discovery=False)
        self.slides_service = build('slides', 'v1', credentials=credentials, cache_discovery=False)
        
        # Initialize JSON exporter for sheets if configured
        if self.export_config.get('google_sheets', {}).get('default_format') == 'json':
            try:
                from exporters.sheets_json import GoogleSheetsJSONExporter
                self.sheets_json_exporter = GoogleSheetsJSONExporter(
                    self.sheets_service,
                    self.export_config.get('google_sheets', {})
                )
                logger.info("JSON exporter initialized for Google Sheets")
            except ImportError:
                logger.warning("GoogleSheetsJSONExporter not available")
    
    def extract_file_id(self, url: str) -> str:
        """Extract file ID from URL"""
        if 'drive.google.com' in url or 'docs.google.com' in url:
            parts = url.split('/')
            for i, part in enumerate(parts):
                if part == 'd':
                    return parts[i + 1]
                elif 'spreadsheets' in part or 'document' in part or 'presentation' in part:
                    if i + 2 < len(parts):
                        return parts[i + 2].split('/')[0] if '/' in parts[i + 2] else parts[i + 2]
        return None
    
    def fetch_content(self, url: str, export_format: str = None) -> Tuple[str, Dict]:
        """
        Get Google document content with optional format override
        
        Args:
            url: Google Docs/Sheets/Slides URL
            export_format: Override export format ('markdown', 'json', 'html')
        """
        file_id = self.extract_file_id(url)
        if not file_id:
            raise ValueError(f"Cannot extract file ID from URL: {url}")

        # Очищаем кеш Discovery API чтобы получить свежие данные
        try:
            self.drive_service._http.cache = None
        except:
            pass
        
        # Get file information - ВАЖНО получить modifiedTime!
        file_info = self.drive_service.files().get(
            fileId=file_id,
            fields='name,mimeType,modifiedTime,version'  # Убедитесь что запрашиваем modifiedTime
        ).execute()

        mime_type = file_info.get('mimeType')
        
        metadata = {
            'title': file_info.get('name', 'Untitled'),
            'id': file_id,
            'mime_type': mime_type,
            'modified_time': file_info.get('modifiedTime'),  # ОБЯЗАТЕЛЬНО передаем это поле!
            'modifiedTime': file_info.get('modifiedTime')    # Дублируем для совместимости
        }
        
        # Process based on type
        if mime_type == 'application/vnd.google-apps.document':
            content = self._fetch_doc_as_html(file_id)
            metadata['export_format'] = 'html'
            
        elif mime_type == 'application/vnd.google-apps.spreadsheet':
            # Determine export format for spreadsheet
            if not export_format:
                export_format = self.export_config.get('google_sheets', {}).get('default_format', 'markdown')
            
            if export_format == 'json':
                content = self._fetch_sheet_as_json(file_id)
                metadata['export_format'] = 'json'
                metadata['_is_json'] = True
            else:
                content = self._fetch_sheet_as_html(file_id)
                metadata['export_format'] = 'html'
                
        elif mime_type == 'application/vnd.google-apps.presentation':
            content = self._fetch_slides_as_html(file_id)
            metadata['export_format'] = 'html'
        else:
            raise ValueError(f"Unsupported file type: {mime_type}")
        
        return content, metadata
    
    def _fetch_sheet_as_json(self, file_id: str) -> str:
        """Get Google Sheet as JSON"""
        if not self.sheets_json_exporter:
            # Initialize exporter if not already done
            try:
                from exporters.sheets_json import GoogleSheetsJSONExporter
                self.sheets_json_exporter = GoogleSheetsJSONExporter(
                    self.sheets_service,
                    self.export_config.get('google_sheets', {})
                )
            except ImportError:
                # Fallback to simple JSON export
                return self._fetch_sheet_as_simple_json(file_id)
        
        # Use the JSON exporter
        metadata, json_string = self.sheets_json_exporter.export_to_json(
            file_id,
            {'format': 'records'}  # Default to records format
        )
        
        return json_string
    
    def _fetch_sheet_as_simple_json(self, file_id: str) -> str:
        """Simple JSON export fallback"""
        spreadsheet = self.sheets_service.spreadsheets().get(
            spreadsheetId=file_id
        ).execute()
        
        result = {
            'spreadsheet': {
                'title': spreadsheet['properties']['title'],
                'id': file_id
            },
            'sheets': {}
        }
        
        for sheet in spreadsheet.get('sheets', []):
            sheet_title = sheet['properties']['title']
            
            try:
                values_result = self.sheets_service.spreadsheets().values().get(
                    spreadsheetId=file_id,
                    range=f"'{sheet_title}'"
                ).execute()
                
                values = values_result.get('values', [])
                
                if values:
                    # Convert to records format
                    headers = values[0] if values else []
                    records = []
                    
                    for row in values[1:]:
                        record = {}
                        for i, header in enumerate(headers):
                            value = row[i] if i < len(row) else None
                            record[str(header)] = value
                        records.append(record)
                    
                    result['sheets'][sheet_title] = {
                        'data': records,
                        'row_count': len(values),
                        'column_count': len(headers)
                    }
            except:
                result['sheets'][sheet_title] = {'data': [], 'error': 'Unable to read sheet'}
        
        return json.dumps(result, indent=2, ensure_ascii=False)
    
    def _fetch_doc_as_html(self, file_id: str) -> str:
        """Get Google Doc as HTML"""
        document = self.docs_service.documents().get(documentId=file_id).execute()
        
        html = f"<h1>{document.get('title', 'Untitled')}</h1>\n"
        content = document.get('body', {}).get('content', [])
        
        for element in content:
            if 'paragraph' in element:
                para_text = ""
                for elem in element['paragraph'].get('elements', []):
                    if 'textRun' in elem:
                        para_text += elem['textRun'].get('content', '')
                if para_text.strip():
                    html += f"<p>{para_text}</p>\n"
        
        return html
    
    def _fetch_sheet_as_html(self, file_id: str) -> str:
        """Get Google Sheet as HTML"""
        spreadsheet = self.sheets_service.spreadsheets().get(
            spreadsheetId=file_id
        ).execute()
        
        html = f"<h1>{spreadsheet['properties']['title']}</h1>\n"
        
        for sheet in spreadsheet.get('sheets', []):
            sheet_title = sheet['properties']['title']
            html += f"<h2>{sheet_title}</h2>\n"
            
            try:
                result = self.sheets_service.spreadsheets().values().get(
                    spreadsheetId=file_id,
                    range=f"'{sheet_title}'"
                ).execute()
                
                values = result.get('values', [])
                if values:
                    html += "<table>\n"
                    for i, row in enumerate(values):
                        html += "<tr>"
                        tag = "th" if i == 0 else "td"
                        for cell in row:
                            html += f"<{tag}>{cell}</{tag}>"
                        html += "</tr>\n"
                    html += "</table>\n"
            except:
                html += "<p>Unable to read sheet data</p>\n"
        
        return html
    
    def _fetch_slides_as_html(self, file_id: str) -> str:
        """Get Google Slides as HTML"""
        presentation = self.slides_service.presentations().get(
            presentationId=file_id
        ).execute()
        
        html = f"<h1>{presentation.get('title', 'Untitled')}</h1>\n"
        
        for idx, slide in enumerate(presentation.get('slides', []), 1):
            html += f"<h2>Slide {idx}</h2>\n"
            
            for element in slide.get('pageElements', []):
                if 'shape' in element:
                    shape = element['shape']
                    if 'text' in shape:
                        for text_element in shape['text']['textElements']:
                            if 'textRun' in text_element:
                                text = text_element['textRun']['content']
                                if text.strip():
                                    html += f"<p>{text}</p>\n"
        
        return html
    

    def check_for_updates(self, url: str, last_modified: Optional[datetime]) -> bool:
        """Check if document has been updated"""
        if not last_modified:
            logger.info(f"No last_modified date, will update")
            return True
    
        file_id = self.extract_file_id(url)
        if not file_id:
            return False
    
        try:
            from datetime import timezone
        
            file_info = self.drive_service.files().get(
                fileId=file_id,
                fields='modifiedTime,name'
            ).execute()
        
            modified_time_str = file_info.get('modifiedTime')
            file_name = file_info.get('name', 'Unknown')
        
            if modified_time_str:
                # Парсим время из Google формата
                modified_time = datetime.fromisoformat(modified_time_str.replace('Z', '+00:00'))
            
                # Обрабатываем last_modified
                if isinstance(last_modified, str):
                    if 'Z' in last_modified or '+' in last_modified or 'T' in last_modified:
                        last_modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                    else:
                        last_modified = datetime.fromisoformat(last_modified)
            
                # Убеждаемся что оба datetime имеют timezone
                if last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=timezone.utc)
                if modified_time.tzinfo is None:
                    modified_time = modified_time.replace(tzinfo=timezone.utc)
            
                # Добавляем отладочный вывод
                logger.info(f"Checking updates for '{file_name}':")
                logger.info(f"  Google Drive modified: {modified_time.isoformat()}")
                logger.info(f"  Local last modified:   {last_modified.isoformat()}")
                logger.info(f"  Needs update: {modified_time > last_modified}")
            
                return modified_time > last_modified
            
        except Exception as e:
            logger.error(f"Error checking updates for {url}: {e}")
            return True
    
        return False