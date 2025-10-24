# doc_sync/exporters/sheets_json.py
import json
import logging
import time
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

class GoogleSheetsJSONExporter:
    """Export Google Sheets to JSON format with rate limiting"""
    
    def __init__(self, sheets_service, config: Dict = None):
        """
        Initialize the exporter with a Google Sheets service instance
        
        Args:
            sheets_service: Google Sheets API service instance
            config: Export configuration options
        """
        self.sheets_service = sheets_service
        self.config = config or {}
        
        # Export options
        self.include_metadata = self.config.get('include_metadata', True)
        self.include_formulas = self.config.get('include_formulas', False)
        self.include_formatting = self.config.get('include_formatting', False)
        self.empty_cell_value = self.config.get('empty_cell_value', None)
        self.date_format = self.config.get('date_format', 'iso')
        
        # Rate limiting
        self.request_delay = self.config.get('request_delay_seconds', 1.5)  # 1.5 seconds between requests
        self.max_retries = self.config.get('max_retries', 3)
        self.retry_delay = self.config.get('retry_delay_seconds', 65)  # Wait 65 seconds on rate limit
        
    def _make_api_request(self, request_func, *args, **kwargs):
        """Make API request with retry logic for rate limiting"""
        for attempt in range(self.max_retries):
            try:
                # Add delay before request to avoid hitting rate limits
                time.sleep(self.request_delay)
                
                # Make the request
                result = request_func(*args, **kwargs)
                return result
                
            except HttpError as e:
                if e.resp.status == 429:  # Rate limit exceeded
                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_delay * (attempt + 1)  # Exponential backoff
                        logger.warning(f"Rate limit hit, waiting {wait_time} seconds before retry {attempt + 2}/{self.max_retries}")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Rate limit exceeded after {self.max_retries} attempts")
                        raise
                else:
                    raise
        
    def export_to_json(self, file_id: str, options: Dict = None) -> Tuple[Dict, str]:
        """
        Export a Google Sheet to JSON format with rate limiting
        
        Returns:
            Tuple of (metadata dict, json_string)
        """
        options = options or {}
        
        try:
            # Get spreadsheet metadata with retry logic
            spreadsheet = self._make_api_request(
                self.sheets_service.spreadsheets().get,
                spreadsheetId=file_id,
                includeGridData=False
            ).execute()
            
            # Extract metadata
            metadata = {
                'title': spreadsheet['properties']['title'],
                'spreadsheet_id': file_id,
                'sheets_count': len(spreadsheet.get('sheets', [])),
                'locale': spreadsheet['properties'].get('locale', 'en'),
                'time_zone': spreadsheet['properties'].get('timeZone', 'UTC'),
                'sheets': []
            }
            
            # Prepare JSON structure
            json_data = {
                'spreadsheet': {
                    'title': metadata['title'],
                    'id': file_id
                }
            }
            
            if self.include_metadata:
                json_data['metadata'] = metadata
            
            # Process each sheet with rate limiting
            sheets_data = {}
            
            for i, sheet in enumerate(spreadsheet.get('sheets', [])):
                sheet_properties = sheet['properties']
                sheet_title = sheet_properties['title']
                sheet_id = sheet_properties['sheetId']
                
                logger.info(f"Processing sheet {i+1}/{len(spreadsheet.get('sheets', []))}: {sheet_title}")
                
                # Get sheet data based on export format
                sheet_export_format = options.get('format', 'records')
                
                try:
                    if sheet_export_format == 'raw':
                        sheet_data = self._export_sheet_raw(file_id, sheet_title)
                    elif sheet_export_format == 'records':
                        sheet_data = self._export_sheet_as_records(file_id, sheet_title)
                    elif sheet_export_format == 'matrix':
                        sheet_data = self._export_sheet_as_matrix(file_id, sheet_title)
                    elif sheet_export_format == 'dict':
                        sheet_data = self._export_sheet_as_dict(file_id, sheet_title)
                    else:
                        sheet_data = self._export_sheet_as_records(file_id, sheet_title)
                        
                except HttpError as e:
                    if e.resp.status == 429:
                        logger.warning(f"Skipping sheet {sheet_title} due to rate limit")
                        sheet_data = {'error': 'Rate limit exceeded', 'sheet': sheet_title}
                    else:
                        logger.error(f"Error processing sheet {sheet_title}: {e}")
                        sheet_data = {'error': str(e), 'sheet': sheet_title}
                
                # Add sheet metadata
                sheet_meta = {
                    'title': sheet_title,
                    'id': sheet_id,
                    'index': sheet_properties.get('index', 0),
                    'row_count': sheet_properties.get('gridProperties', {}).get('rowCount', 0),
                    'column_count': sheet_properties.get('gridProperties', {}).get('columnCount', 0)
                }
                
                metadata['sheets'].append(sheet_meta)
                
                # Store sheet data
                sheets_data[sheet_title] = {
                    'info': sheet_meta,
                    'data': sheet_data
                }
            
            json_data['sheets'] = sheets_data
            
            # Convert to JSON string with proper formatting
            json_string = json.dumps(json_data, indent=2, ensure_ascii=False, default=str)
            
            return metadata, json_string
            
        except Exception as e:
            logger.error(f"Error exporting spreadsheet to JSON: {e}")
            raise
    
    def _export_sheet_raw(self, spreadsheet_id: str, sheet_name: str) -> List[List[Any]]:
        """Export sheet as raw 2D array with rate limiting"""
        try:
            result = self._make_api_request(
                self.sheets_service.spreadsheets().values().get,
                spreadsheetId=spreadsheet_id,
                range=f"'{sheet_name}'",
                valueRenderOption='UNFORMATTED_VALUE' if not self.include_formatting else 'FORMATTED_VALUE',
                dateTimeRenderOption='SERIAL_NUMBER' if self.date_format == 'serial' else 'FORMATTED_STRING'
            ).execute()
            
            values = result.get('values', [])
            
            # Normalize rows to have same length
            if values:
                max_cols = max(len(row) for row in values)
                normalized = []
                for row in values:
                    normalized_row = row + [self.empty_cell_value] * (max_cols - len(row))
                    normalized.append(normalized_row)
                return normalized
            
            return []
            
        except Exception as e:
            logger.error(f"Error exporting sheet {sheet_name}: {e}")
            return []
    
    def _export_sheet_as_records(self, spreadsheet_id: str, sheet_name: str) -> List[Dict]:
        """Export sheet as array of records (objects) with headers as keys"""
        raw_data = self._export_sheet_raw(spreadsheet_id, sheet_name)
        
        if not raw_data or len(raw_data) < 1:
            return []
        
        # First row as headers
        headers = [str(h).strip() if h else f"Column_{i+1}" for i, h in enumerate(raw_data[0])]
        
        # Convert to records
        records = []
        for row in raw_data[1:]:
            record = {}
            for i, header in enumerate(headers):
                value = row[i] if i < len(row) else self.empty_cell_value
                # Clean up the value
                if value == self.empty_cell_value or value == "":
                    value = None
                record[header] = value
            records.append(record)
        
        return records
    
    def _export_sheet_as_matrix(self, spreadsheet_id: str, sheet_name: str) -> Dict:
        """Export sheet as matrix with row and column indices"""
        raw_data = self._export_sheet_raw(spreadsheet_id, sheet_name)
        
        return {
            'rows': len(raw_data),
            'columns': len(raw_data[0]) if raw_data else 0,
            'data': raw_data
        }
    
    def _export_sheet_as_dict(self, spreadsheet_id: str, sheet_name: str) -> Dict:
        """Export sheet as dictionary with first column as keys"""
        raw_data = self._export_sheet_raw(spreadsheet_id, sheet_name)
        
        if not raw_data or len(raw_data[0]) < 2:
            return {}
        
        result = {}
        for row in raw_data:
            if row and row[0]:
                key = str(row[0])
                if len(row) == 2:
                    result[key] = row[1] if len(row) > 1 else None
                else:
                    result[key] = row[1:] if len(row) > 1 else []
        
        return result