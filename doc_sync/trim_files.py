import os
from pathlib import Path

def trim_text_files(folder_path, max_size_bytes, file_extension='.txt', encoding='utf-8'):
    """
    Читает все текстовые файлы из указанной папки и обрезает их размер,
    аккуратно ищя границы строк, чтобы размер содержимого не превышал максимальный.
    
    Args:
        folder_path (str): Путь к папке с файлами
        max_size_bytes (int): Максимальный размер файла в байтах
        file_extension (str): Расширение текстовых файлов (по умолчанию '.txt')
        encoding (str): Кодировка файлов (по умолчанию 'utf-8')
    
    Returns:
        dict: Словарь с результатами обработки {имя_файла: (старый_размер, новый_размер)}
    """
    results = {}
    folder = Path(folder_path)
    
    # Проверяем существование папки
    if not folder.exists():
        raise FileNotFoundError(f"Папка не найдена: {folder_path}")
    
    # Перебираем все файлы с указанным расширением
    for file_path in folder.glob(f'*{file_extension}'):
        if not file_path.is_file():
            continue
            
        try:
            # Читаем содержимое файла
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            
            original_size = len(content.encode(encoding))
            
            # Если размер уже меньше максимального, пропускаем
            if original_size <= max_size_bytes:
                results[file_path.name] = (original_size, original_size)
                continue
            
            # Разбиваем на строки
            lines = content.split('\n')
            trimmed_content = ''
            current_size = 0
            
            # Добавляем строки, пока не превысим максимальный размер
            for line in lines:
                line_with_newline = line + '\n'
                line_size = len(line_with_newline.encode(encoding))
                
                if current_size + line_size <= max_size_bytes:
                    trimmed_content += line_with_newline
                    current_size += line_size
                else:
                    break
            
            # Убираем последний перенос строки, если нужно
            trimmed_content = trimmed_content.rstrip('\n')
            new_size = len(trimmed_content.encode(encoding))
            
            # Записываем обрезанное содержимое обратно
            with open(file_path, 'w', encoding=encoding) as f:
                f.write(trimmed_content)
            
            results[file_path.name] = (original_size, new_size)
            print(f"✓ {file_path.name}: {original_size} → {new_size} байт")
            
        except Exception as e:
            print(f"✗ Ошибка при обработке {file_path.name}: {e}")
            results[file_path.name] = (0, 0)
    
    return results


# Пример использования
if __name__ == "__main__":
    folder = "./text_files"  # Путь к папке
    max_size = 10240  # Максимальный размер 10KB
    
    results = trim_text_files(folder, max_size)
    
    print("\n=== Итоги обработки ===")
    for filename, (old_size, new_size) in results.items():
        if old_size > new_size:
            print(f"{filename}: обрезан с {old_size} до {new_size} байт")
        else:
            print(f"{filename}: размер в норме ({old_size} байт)")