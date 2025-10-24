# code/utils/markdown_utils.py

"""
Утилиты для работы с Markdown в Telegram
"""

def escape_markdown_v2(text: str) -> str:
    """
    Экранирует специальные символы для MarkdownV2 в Telegram
    
    Args:
        text: Исходный текст
        
    Returns:
        Текст с экранированными символами для MarkdownV2
    """
    if not text:
        return text
    
    # Список символов, которые нужно экранировать в MarkdownV2
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    result = str(text)
    for char in escape_chars:
        result = result.replace(char, f'\\{char}')
    
    return result
