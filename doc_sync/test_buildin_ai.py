#!/usr/bin/env python3
"""
Полный рекурсивный сканер страниц Buildin с экспортом всего содержимого
Включая загрузку Google Drive документов
"""

import requests
import json
import sys
import re
from datetime import datetime
from typing import Dict, List, Set, Optional

class BuildinScanner:
    def __init__(self, bot_token: str, include_gdrive: bool = False, gdrive_auth_file: str = None):
        self.bot_token = bot_token
        self.base_url = "https://api.buildin.ai/v1"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        self.processed_pages: Set[str] = set()
        self.all_content: Dict = {}
        self.stats = {
            'total_pages': 0,
            'total_blocks': 0,
            'block_types': {},
            'max_depth': 0,
            'child_pages': [],
            'google_docs_found': [],
            'google_docs_fetched': 0
        }
        
        # Google Drive integration
        self.include_gdrive = include_gdrive
        self.gdrive_provider = None
        if include_gdrive and gdrive_auth_file:
            try:
                # Динамически импортируем GoogleDocsProvider
                import os
                import sys
                # Добавляем путь к providers если нужно
                current_dir = os.path.dirname(os.path.abspath(__file__))
                providers_dir = os.path.join(current_dir, 'providers')
                if os.path.exists(providers_dir):
                    sys.path.insert(0, current_dir)
                
                from providers.google_docs import GoogleDocsProvider
                
                gdrive_auth = {
                    'service_account_file': gdrive_auth_file
                }
                self.gdrive_provider = GoogleDocsProvider(gdrive_auth)
                print("✓ Google Drive provider initialized")
            except Exception as e:
                print(f"⚠️ Failed to initialize Google Drive provider: {e}")
                self.include_gdrive = False
    
    def scan_page(self, page_id: str, depth: int = 0, parent_title: str = None, max_depth: int = 3) -> Dict:
        """Рекурсивно сканировать страницу и все её вложения"""
        
        # Избегаем повторной обработки
        if page_id in self.processed_pages:
            return {'id': page_id, 'note': 'Already processed'}
        
        self.processed_pages.add(page_id)
        self.stats['total_pages'] += 1
        self.stats['max_depth'] = max(self.stats['max_depth'], depth)
        
        indent = "  " * depth
        print(f"{indent}Scanning page: {page_id[:8]}... (depth: {depth})")
        
        # Получаем информацию о странице
        page_response = self.session.get(f"{self.base_url}/pages/{page_id}")
        
        if page_response.status_code != 200:
            print(f"{indent}  ✗ Failed to fetch page: {page_response.status_code}")
            return {'id': page_id, 'error': f"Status {page_response.status_code}"}
        
        page_data = page_response.json()
        title = self.extract_title(page_data)
        print(f"{indent}  Title: {title}")
        
        # Создаем структуру для хранения данных страницы
        page_info = {
            'id': page_id,
            'title': title,
            'depth': depth,
            'parent_title': parent_title,
            'url': page_data.get('url', ''),
            'created_time': page_data.get('created_time'),
            'last_edited_time': page_data.get('last_edited_time'),
            'properties': self.extract_all_properties(page_data.get('properties', {})),
            'blocks': [],
            'child_pages': [],
            'google_docs': [],
            'stats': {
                'total_blocks': 0,
                'block_types': {},
                'has_content': False,
                'has_google_docs': False
            }
        }
        
        # Ищем Google Drive ссылки в свойствах
        google_urls = self.find_google_urls_in_properties(page_data.get('properties', {}))
        if google_urls:
            print(f"{indent}  Found {len(google_urls)} Google Doc(s) in properties")
            page_info['google_docs'] = google_urls
            page_info['stats']['has_google_docs'] = True
            
            # Добавляем в общую статистику
            for doc in google_urls:
                self.stats['google_docs_found'].append({
                    'page_title': title,
                    'property': doc['property_name'],
                    'url': doc['url'],
                    'type': doc['type']
                })
            
            # Пробуем загрузить содержимое
            if self.include_gdrive and self.gdrive_provider:
                for doc in google_urls:
                    print(f"{indent}    Fetching {doc['type']}: {doc['property_name']}")
                    content = self.fetch_google_content(doc['url'])
                    if content:
                        doc['content'] = content
                        doc['fetched'] = True
                        self.stats['google_docs_fetched'] += 1
                        print(f"{indent}      ✓ Fetched {len(content)} chars")
                    else:
                        doc['content'] = None
                        doc['fetched'] = False
                        print(f"{indent}      ✗ Failed to fetch content")
        
        # Получаем все блоки страницы
        all_blocks = self.fetch_all_blocks(page_id, indent + "  ")
        page_info['blocks'] = all_blocks
        page_info['stats']['total_blocks'] = len(all_blocks)
        
        # Анализируем блоки
        for block in all_blocks:
            block_type = block.get('type')
            page_info['stats']['block_types'][block_type] = \
                page_info['stats']['block_types'].get(block_type, 0) + 1
            
            # Проверяем наличие контента
            if block_type != 'child_page' and self.block_has_content(block):
                page_info['stats']['has_content'] = True
            
            # Ищем Google ссылки в блоках
            if block_type in ['paragraph', 'bookmark', 'embed']:
                block_google_urls = self.find_google_urls_in_block(block)
                if block_google_urls:
                    page_info['google_docs'].extend(block_google_urls)
                    page_info['stats']['has_google_docs'] = True
            
            # Обрабатываем дочерние страницы
            if block_type == 'child_page':
                child_id = block.get('id')
                child_data = block.get('data', {})
                child_title = child_data.get('title', 'Untitled')
                
                print(f"{indent}  Found child page: {child_title}")
                
                # Рекурсивно сканируем дочернюю страницу
                if depth < max_depth:
                    child_info = self.scan_page(child_id, depth + 1, title, max_depth)
                    page_info['child_pages'].append(child_info)
                    self.stats['child_pages'].append({
                        'title': child_title,
                        'id': child_id,
                        'parent': title,
                        'depth': depth + 1
                    })
                else:
                    page_info['child_pages'].append({
                        'id': child_id,
                        'title': child_title,
                        'note': 'Max depth reached'
                    })
        
        # Обновляем общую статистику
        self.stats['total_blocks'] += len(all_blocks)
        for block_type, count in page_info['stats']['block_types'].items():
            self.stats['block_types'][block_type] = \
                self.stats['block_types'].get(block_type, 0) + count
        
        return page_info
    
    def find_google_urls_in_properties(self, properties: Dict) -> List[Dict]:
        """Найти Google Drive URLs в свойствах страницы"""
        google_urls = []
        
        for prop_name, prop_value in properties.items():
            prop_type = prop_value.get('type')
            
            if prop_type == 'url':
                url = prop_value.get('url', '')
                if url and ('docs.google.com' in url or 'drive.google.com' in url):
                    google_urls.append({
                        'property_name': prop_name,
                        'url': url,
                        'type': self.detect_google_doc_type(url),
                        'source': 'property'
                    })
            
            elif prop_type == 'rich_text':
                for item in prop_value.get('rich_text', []):
                    if 'text' in item:
                        text = item['text'].get('content', '')
                        urls = re.findall(r'https?://(?:docs|drive)\.google\.com/[^\s]+', text)
                        for url in urls:
                            google_urls.append({
                                'property_name': prop_name,
                                'url': url,
                                'type': self.detect_google_doc_type(url),
                                'source': 'rich_text'
                            })
        
        return google_urls
    
    def find_google_urls_in_block(self, block: Dict) -> List[Dict]:
        """Найти Google Drive URLs в блоке"""
        google_urls = []
        block_type = block.get('type')
        
        if block_type == 'bookmark':
            url = block.get('bookmark', {}).get('url', '')
            if url and ('docs.google.com' in url or 'drive.google.com' in url):
                google_urls.append({
                    'property_name': 'bookmark',
                    'url': url,
                    'type': self.detect_google_doc_type(url),
                    'source': 'block'
                })
        
        elif block_type == 'embed':
            url = block.get('embed', {}).get('url', '')
            if url and ('docs.google.com' in url or 'drive.google.com' in url):
                google_urls.append({
                    'property_name': 'embed',
                    'url': url,
                    'type': self.detect_google_doc_type(url),
                    'source': 'block'
                })
        
        elif block_type == 'paragraph':
            rich_text = block.get('paragraph', {}).get('rich_text', [])
            for item in rich_text:
                if 'text' in item:
                    text = item['text'].get('content', '')
                    urls = re.findall(r'https?://(?:docs|drive)\.google\.com/[^\s]+', text)
                    for url in urls:
                        google_urls.append({
                            'property_name': 'paragraph',
                            'url': url,
                            'type': self.detect_google_doc_type(url),
                            'source': 'block'
                        })
        
        return google_urls
    
    def detect_google_doc_type(self, url: str) -> str:
        """Определить тип Google документа"""
        if 'spreadsheets' in url:
            return 'spreadsheet'
        elif 'document' in url:
            return 'document'
        elif 'presentation' in url:
            return 'presentation'
        elif 'drive.google.com' in url:
            return 'file'
        return 'unknown'
    
    def fetch_google_content(self, url: str) -> Optional[str]:
        """Загрузить содержимое Google документа"""
        if not self.gdrive_provider:
            return None
        
        try:
            content, metadata = self.gdrive_provider.fetch_content(url)
            
            # Если это HTML, конвертируем в текст для упрощения
            if '<' in content and '>' in content:
                # Простое удаление HTML тегов
                content = re.sub(r'<[^>]+>', '', content)
                content = content.strip()
            
            return content[:5000]  # Ограничиваем размер для тестирования
            
        except Exception as e:
            print(f"        Error fetching Google content: {e}")
            return None
    
    def fetch_all_blocks(self, page_id: str, indent: str = "") -> List[Dict]:
        """Получить все блоки страницы с пагинацией"""
        all_blocks = []
        has_more = True
        start_cursor = None
        
        while has_more:
            params = {'page_size': 100}
            if start_cursor:
                params['start_cursor'] = start_cursor
            
            response = self.session.get(
                f"{self.base_url}/blocks/{page_id}/children",
                params=params
            )
            
            if response.status_code != 200:
                print(f"{indent}✗ Failed to fetch blocks: {response.status_code}")
                break
            
            data = response.json()
            blocks = data.get('results', [])
            all_blocks.extend(blocks)
            
            has_more = data.get('has_more', False)
            start_cursor = data.get('next_cursor')
            
            print(f"{indent}Fetched {len(blocks)} blocks (total: {len(all_blocks)}, has_more: {has_more})")
            
            # Защита от бесконечного цикла
            if len(all_blocks) > 1000:
                print(f"{indent}⚠️ Reached 1000 blocks limit")
                break
        
        return all_blocks
    
    def extract_title(self, page_data: Dict) -> str:
        """Извлечь заголовок страницы"""
        properties = page_data.get('properties', {})
        
        for prop_name in ['title', 'Title', 'Name', 'name', 'Название']:
            if prop_name in properties:
                prop = properties[prop_name]
                if prop.get('type') == 'title' and 'title' in prop:
                    for item in prop['title']:
                        if 'text' in item:
                            return item['text'].get('content', 'Untitled')
        
        return 'Untitled'
    
    def extract_all_properties(self, properties: Dict) -> Dict:
        """Извлечь все свойства страницы"""
        result = {}
        
        for prop_name, prop_value in properties.items():
            prop_type = prop_value.get('type')
            content = self.extract_property_content(prop_value, prop_type)
            if content:
                result[prop_name] = {
                    'type': prop_type,
                    'value': content
                }
        
        return result
    
    def extract_property_content(self, prop_value: Dict, prop_type: str) -> str:
        """Извлечь содержимое свойства"""
        if prop_type == 'title':
            texts = []
            for item in prop_value.get('title', []):
                if 'text' in item:
                    texts.append(item['text'].get('content', ''))
            return ' '.join(texts)
        
        elif prop_type == 'rich_text':
            texts = []
            for item in prop_value.get('rich_text', []):
                if 'text' in item:
                    texts.append(item['text'].get('content', ''))
            return ' '.join(texts)
        
        elif prop_type == 'select':
            select = prop_value.get('select', {})
            return select.get('name', '')
        
        elif prop_type == 'multi_select':
            items = prop_value.get('multi_select', [])
            return ', '.join([item.get('name', '') for item in items])
        
        elif prop_type == 'checkbox':
            return 'Yes' if prop_value.get('checkbox') else 'No'
        
        elif prop_type == 'number':
            number = prop_value.get('number')
            return str(number) if number is not None else ''
        
        elif prop_type == 'date':
            date_obj = prop_value.get('date', {})
            start = date_obj.get('start', '')
            end = date_obj.get('end', '')
            return f"{start} - {end}" if end else start
        
        elif prop_type == 'url':
            return prop_value.get('url', '')
        
        elif prop_type == 'email':
            return prop_value.get('email', '')
        
        elif prop_type == 'phone_number':
            return prop_value.get('phone_number', '')
        
        elif prop_type == 'people':
            people = prop_value.get('people', [])
            return ', '.join([person.get('name', 'Unknown') for person in people])
        
        elif prop_type == 'files':
            files = prop_value.get('files', [])
            file_names = []
            for file in files:
                name = file.get('name', 'File')
                file_names.append(name)
            return ', '.join(file_names)
        
        return ''
    
    def block_has_content(self, block: Dict) -> bool:
        """Проверить, есть ли в блоке текстовое содержимое"""
        block_type = block.get('type')
        
        content_fields = {
            'paragraph': 'paragraph',
            'heading_1': 'heading_1',
            'heading_2': 'heading_2',
            'heading_3': 'heading_3',
            'bulleted_list_item': 'bulleted_list_item',
            'numbered_list_item': 'numbered_list_item',
            'to_do': 'to_do',
            'toggle': 'toggle',
            'code': 'code',
            'quote': 'quote',
            'callout': 'callout'
        }
        
        if block_type in content_fields:
            field = content_fields[block_type]
            rich_text = block.get(field, {}).get('rich_text', [])
            for item in rich_text:
                if 'text' in item and item['text'].get('content', '').strip():
                    return True
        
        return False
    
    def extract_block_content(self, block: Dict) -> str:
        """Извлечь текстовое содержимое из блока"""
        block_type = block.get('type')
        
        if block_type == 'child_page':
            child_data = block.get('data', {})
            return child_data.get('title', 'Untitled')
        
        content_fields = {
            'paragraph': 'paragraph',
            'heading_1': 'heading_1',
            'heading_2': 'heading_2',
            'heading_3': 'heading_3',
            'bulleted_list_item': 'bulleted_list_item',
            'numbered_list_item': 'numbered_list_item',
            'to_do': 'to_do',
            'toggle': 'toggle',
            'code': 'code',
            'quote': 'quote',
            'callout': 'callout'
        }
        
        if block_type in content_fields:
            field = content_fields[block_type]
            rich_text = block.get(field, {}).get('rich_text', [])
            texts = []
            for item in rich_text:
                if 'text' in item:
                    texts.append(item['text'].get('content', ''))
            return ' '.join(texts)
        
        elif block_type == 'table':
            return f"[Table with {block.get('table', {}).get('table_width', 0)} columns]"
        
        elif block_type == 'image':
            caption = self.extract_rich_text(block.get('image', {}).get('caption', []))
            return f"[Image: {caption}]" if caption else "[Image]"
        
        elif block_type == 'divider':
            return "---"
        
        return ""
    
    def extract_rich_text(self, rich_text_array: List) -> str:
        """Извлечь текст из rich_text массива"""
        texts = []
        for item in rich_text_array:
            if 'text' in item:
                texts.append(item['text'].get('content', ''))
        return ' '.join(texts)
    
    def generate_report(self, page_info: Dict) -> str:
        """Генерировать текстовый отчет по странице"""
        lines = []
        
        def add_page(info: Dict, indent: int = 0):
            prefix = "  " * indent
            lines.append(f"{prefix}{'=' * 60}")
            lines.append(f"{prefix}Page: {info['title']}")
            lines.append(f"{prefix}ID: {info['id']}")
            lines.append(f"{prefix}URL: {info.get('url', 'N/A')}")
            lines.append(f"{prefix}Depth: {info.get('depth', 0)}")
            if info.get('parent_title'):
                lines.append(f"{prefix}Parent: {info['parent_title']}")
            lines.append(f"{prefix}Last edited: {info.get('last_edited_time', 'N/A')}")
            
            # Свойства
            if info.get('properties'):
                lines.append(f"{prefix}Properties:")
                for prop_name, prop_data in info['properties'].items():
                    lines.append(f"{prefix}  - {prop_name} ({prop_data['type']}): {prop_data['value'][:100]}...")
            
            # Google документы
            if info.get('google_docs'):
                lines.append(f"{prefix}Google Docs found: {len(info['google_docs'])}")
                for doc in info['google_docs']:
                    lines.append(f"{prefix}  - {doc['type']}: {doc['url'][:50]}...")
                    if doc.get('fetched'):
                        content_preview = doc.get('content', '')[:100] if doc.get('content') else 'No content'
                        lines.append(f"{prefix}    Content: {content_preview}...")
            
            # Статистика блоков
            stats = info.get('stats', {})
            lines.append(f"{prefix}Blocks: {stats.get('total_blocks', 0)}")
            if stats.get('block_types'):
                lines.append(f"{prefix}Block types:")
                for block_type, count in stats['block_types'].items():
                    lines.append(f"{prefix}  - {block_type}: {count}")
            lines.append(f"{prefix}Has content: {stats.get('has_content', False)}")
            lines.append(f"{prefix}Has Google docs: {stats.get('has_google_docs', False)}")
            
            # Контент блоков (первые 10 для preview)
            content_blocks = []
            for block in info.get('blocks', [])[:10]:
                content = self.extract_block_content(block)
                if content:
                    block_type = block.get('type')
                    content_blocks.append(f"{block_type}: {content[:100]}...")
            
            if content_blocks:
                lines.append(f"{prefix}Content preview:")
                for cb in content_blocks:
                    lines.append(f"{prefix}  - {cb}")
            
            # Рекурсивно добавляем дочерние страницы
            for child in info.get('child_pages', []):
                if isinstance(child, dict) and 'title' in child:
                    lines.append("")
                    add_page(child, indent + 1)
                elif isinstance(child, dict):
                    lines.append(f"{prefix}  Child: {child.get('id', 'Unknown')} - {child.get('note', '')}")
        
        add_page(page_info)
        
        # Добавляем общую статистику
        lines.append("\n" + "=" * 60)
        lines.append("OVERALL STATISTICS")
        lines.append("=" * 60)
        lines.append(f"Total pages scanned: {self.stats['total_pages']}")
        lines.append(f"Total blocks: {self.stats['total_blocks']}")
        lines.append(f"Max depth reached: {self.stats['max_depth']}")
        lines.append(f"Total child pages found: {len(self.stats['child_pages'])}")
        lines.append(f"Google docs found: {len(self.stats['google_docs_found'])}")
        lines.append(f"Google docs fetched: {self.stats['google_docs_fetched']}")
        
        if self.stats['block_types']:
            lines.append("\nBlock type distribution:")
            for block_type, count in sorted(self.stats['block_types'].items(), 
                                           key=lambda x: x[1], reverse=True):
                lines.append(f"  - {block_type}: {count}")
        
        if self.stats['child_pages']:
            lines.append(f"\nChild pages hierarchy:")
            for cp in self.stats['child_pages'][:20]:  # Ограничиваем вывод
                indent = "  " * cp['depth']
                lines.append(f"{indent}- {cp['title']} (depth: {cp['depth']})")
        
        if self.stats['google_docs_found']:
            lines.append(f"\nGoogle Documents found:")
            for doc in self.stats['google_docs_found'][:10]:  # Ограничиваем вывод
                lines.append(f"  - {doc['page_title']} → {doc['property']}: {doc['type']}")
                lines.append(f"    URL: {doc['url'][:70]}...")
        
        return "\n".join(lines)

def main():
    bot_token = "hxj9hMaF5lvS12yCp0TGDZ9YjKf3JaGt8lfJ3QGO"
    
    # Опциональные параметры
    include_gdrive = True
    gdrive_auth_file = "test_ai_bot_data/netrunner/superbotai-40dec23cb052.json"   
    max_depth = 3    
    
    test_urls = [
        'https://buildin.ai/herocraft/03de34f5-d53f-4d11-a68c-031be9fbbb0e#eb2017cf-ef60-40f3-9e77-81f2922b8041',
        'https://buildin.ai/herocraft/0022c61e-d443-493c-aa07-c22b463a469b',
        'https://buildin.ai/herocraft/9140750c-e1ab-481c-b204-95014a2c8e8c#ed8db980-6798-472e-8805-cc50b6194bf7'
    ]
    
    # Инициализируем сканер
    scanner = BuildinScanner(bot_token, include_gdrive, gdrive_auth_file)
    
    # Выбираем URL для сканирования
    print("Available URLs:")
    for i, url in enumerate(test_urls):
        print(f"{i+1}. {url}")
    choice = input("Select URL (1-3) or press Enter for #2 (Animal Village): ").strip()
    if choice and choice.isdigit() and 1 <= int(choice) <= 3:
        url = test_urls[int(choice) - 1]
    else:
        url = test_urls[1]  # По умолчанию Animal Village
    
    print(f"\nScanning URL: {url}")
    print(f"Token: {bot_token[:10]}...{bot_token[-5:]}")
    print(f"Include Google Drive: {include_gdrive}")
    if include_gdrive:
        print(f"Google Auth File: {gdrive_auth_file}")
    print(f"Max depth: {max_depth}")
    print("=" * 60)
    
    # Извлекаем ID страницы
    if '#' in url:
        url = url.split('#')[0]
    page_id = url.rstrip('/').split('/')[-1]
    
    # Сканируем страницу рекурсивно
    result = scanner.scan_page(page_id, max_depth=max_depth)
    
    # Сохраняем полные данные в JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_filename = f"buildin_scan_{page_id[:8]}_{timestamp}.json"
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Full data saved to: {json_filename}")
    
    # Генерируем и сохраняем текстовый отчет
    report = scanner.generate_report(result)
    report_filename = f"buildin_report_{page_id[:8]}_{timestamp}.txt"
    with open(report_filename, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"✓ Report saved to: {report_filename}")
    
    # Выводим краткую статистику
    print("\n" + "=" * 60)
    print("SCAN COMPLETE")
    print("=" * 60)
    print(f"Total pages scanned: {scanner.stats['total_pages']}")
    print(f"Total blocks found: {scanner.stats['total_blocks']}")
    print(f"Maximum depth: {scanner.stats['max_depth']}")
    print(f"Child pages found: {len(scanner.stats['child_pages'])}")
    print(f"Google docs found: {len(scanner.stats['google_docs_found'])}")
    print(f"Google docs fetched: {scanner.stats['google_docs_fetched']}")
    
    if scanner.stats['block_types']:
        print("\nTop block types:")
        for block_type, count in sorted(scanner.stats['block_types'].items(), 
                                       key=lambda x: x[1], reverse=True)[:5]:
            print(f"  - {block_type}: {count}")
    
    if scanner.stats['google_docs_found']:
        print(f"\nGoogle Documents summary:")
        doc_types = {}
        for doc in scanner.stats['google_docs_found']:
            doc_type = doc['type']
            doc_types[doc_type] = doc_types.get(doc_type, 0) + 1
        for doc_type, count in doc_types.items():
            print(f"  - {doc_type}: {count}")

if __name__ == "__main__":
    main()