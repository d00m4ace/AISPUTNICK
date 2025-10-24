import os
import re
from pathlib import Path


def get_first_line_title(file_path):
    """Извлекает название из первой строки файла (формат: # Название.pdf)"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            # Извлекаем название после # и до конца строки
            match = re.match(r'^#\s+(.+)$', first_line)
            if match:
                return match.group(1)
    except Exception as e:
        print(f"Ошибка при чтении {file_path}: {e}")
    return None


def read_txt_content(file_path):
    """Читает полное содержимое txt файла"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Ошибка при чтении {file_path}: {e}")
        return None


def update_md_file(md_path, new_content):
    """Обновляет md файл, сохраняя заголовок и заменяя содержимое после ---"""
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Находим первый разделитель ---
        separator_index = -1
        for i, line in enumerate(lines):
            if line.strip() == '---':
                separator_index = i
                break
        
        if separator_index == -1:
            print(f"Не найден разделитель '---' в {md_path}")
            return False
        
        # Сохраняем заголовок (все до первого ---)
        header = ''.join(lines[:separator_index + 1])
        
        # Формируем новое содержимое файла
        updated_content = header + '\n' + new_content
        
        # Записываем обновленное содержимое
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        return True
    
    except Exception as e:
        print(f"Ошибка при обновлении {md_path}: {e}")
        return False


def find_md_file_by_title(md_folder, title):
    """Ищет md файл, который начинается с указанного заголовка"""
    for md_file in Path(md_folder).glob('*.md'):
        first_line_title = get_first_line_title(md_file)
        if first_line_title and first_line_title == title:
            return md_file
    return None


def process_files(txt_folder='hotfix_hc', md_folder='md_files'):
    """Основная функция обработки файлов"""
    
    # Проверяем существование папок
    if not os.path.exists(txt_folder):
        print(f"Папка {txt_folder} не найдена!")
        return
    
    if not os.path.exists(md_folder):
        print(f"Папка {md_folder} не найдена!")
        return
    
    # Получаем все txt файлы
    txt_files = list(Path(txt_folder).glob('*.txt'))
    
    if not txt_files:
        print(f"В папке {txt_folder} не найдено .txt файлов")
        return
    
    print(f"Найдено {len(txt_files)} .txt файлов для обработки\n")
    
    # Обрабатываем каждый txt файл
    for txt_file in txt_files:
        print(f"Обработка: {txt_file.name}")
        
        # Получаем заголовок из первой строки txt файла
        title = get_first_line_title(txt_file)
        if not title:
            print(f"  ⚠️  Не удалось извлечь заголовок из первой строки")
            continue
        
        print(f"  Заголовок: {title}")
        
        # Ищем соответствующий md файл
        md_file = find_md_file_by_title(md_folder, title)
        if not md_file:
            print(f"  ⚠️  Не найден md файл с заголовком '{title}'")
            continue
        
        print(f"  Найден md файл: {md_file.name}")
        
        # Читаем содержимое txt файла
        txt_content = read_txt_content(txt_file)
        if not txt_content:
            print(f"  ⚠️  Не удалось прочитать содержимое txt файла")
            continue
        
        # Обновляем md файл
        if update_md_file(md_file, txt_content):
            print(f"  ✅ Успешно обновлен: {md_file.name}")
        else:
            print(f"  ❌ Ошибка при обновлении: {md_file.name}")
        
        print()
    
    print("Обработка завершена!")


if __name__ == "__main__":
    # Запуск обработки с параметрами по умолчанию
    process_files('hotfix_hc', 'md_files')
    
    # Если нужно указать другие папки, можно вызвать так:
    # process_files('путь/к/txt/папке', 'путь/к/md/папке')