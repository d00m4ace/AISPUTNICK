"""
Document Summarizer System - GPT-5+ Models Only

Система для создания умных резюме документов с поддержкой моделей GPT-5 и выше.
Использует параметр reasoning_effort для контроля скорости и качества анализа:
  - minimal: Максимальная скорость (2-5x быстрее)
  - medium: Баланс скорости и качества
  - high: Глубокий анализ (медленнее, но точнее)

Автор: AI Assistant
"""

import argparse
import sys
import os
import json
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from openai import OpenAI
import tiktoken


@dataclass
class ModelConfig:
    """Конфигурация модели"""
    name: str
    context_size: int
    temperature: float = 1.0
    reasoning_effort: str = "minimal"  # minimal, low, medium, high - для скорости ответов


class Config:
    """Менеджер конфигурации системы"""
    
    SUPPORTED_MODELS = {
        # GPT-5 серия (с минимальным reasoning для скорости)
        "gpt-5": ModelConfig("gpt-5", 256000, temperature=1.0, reasoning_effort="minimal"),
        "gpt-5-mini": ModelConfig("gpt-5-mini", 128000, temperature=1.0, reasoning_effort="minimal"),
        "gpt-5-nano": ModelConfig("gpt-5-nano", 64000, temperature=1.0, reasoning_effort="minimal"),
        
        # O-серия (будущие модели с reasoning control)
        "o3": ModelConfig("o3", 200000, temperature=1.0, reasoning_effort="minimal"),
        "o3-mini": ModelConfig("o3-mini", 100000, temperature=1.0, reasoning_effort="minimal"),
        "o4": ModelConfig("o4", 256000, temperature=1.0, reasoning_effort="minimal"),
        "o4-mini": ModelConfig("o4-mini", 128000, temperature=1.0, reasoning_effort="minimal"),
    }
    
    DEFAULT_CONFIG = {
        "api_key": "your-openai-api-key-here",
        "source_dir": "./documents",
        "summary_dir": "./summaries",
        "summary_model": "gpt-5-mini",
        "summary_max_chars": 800,
        "selection_model": "gpt-5-mini",
        "selection_retries": 3,
        "max_files_for_answer": 3,
        "answer_model": "gpt-5",
        "answer_max_tokens": None,
        "reasoning_effort": "minimal",  # minimal, low, medium, high - контроль скорости
        "enable_fast_mode": True,  # Включить быстрый режим ответов
    }
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._validate_models()
    
    def _load_config(self) -> Dict:
        """Загружает конфигурацию из файла"""
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                config = self.DEFAULT_CONFIG.copy()
                config.update(loaded_config)
                return config
        else:
            # Создаем файл с дефолтной конфигурацией
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
            return self.DEFAULT_CONFIG.copy()
    
    def _validate_models(self):
        """Проверяет, что модели в конфигурации поддерживаются"""
        for model_key in ["summary_model", "selection_model", "answer_model"]:
            model_name = self.config.get(model_key)
            if model_name not in self.SUPPORTED_MODELS:
                print(f"⚠️ Модель '{model_name}' не поддерживается. Используется gpt-5-mini")
                self.config[model_key] = "gpt-5-mini"
        
        # Применяем настройку reasoning_effort если она указана
        reasoning = self.config.get("reasoning_effort", "minimal")
        if reasoning in ["minimal", "low", "medium", "high"]:
            for model in self.SUPPORTED_MODELS.values():
                model.reasoning_effort = reasoning
    
    def get(self, key: str, default=None):
        """Получает значение из конфигурации"""
        return self.config.get(key, default)
    
    def get_model_config(self, model: str) -> ModelConfig:
        """Получает конфигурацию модели"""
        return self.SUPPORTED_MODELS.get(model, self.SUPPORTED_MODELS["gpt-5-mini"])


class DocumentProcessor:
    """Процессор для создания резюме документов"""
    
    TEXT_EXTENSIONS = ['.txt', '.md', '.markdown']
    
    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(api_key=config.get("api_key"))
        self.source_dir = Path(config.get("source_dir"))
        self.summary_dir = Path(config.get("summary_dir"))
        self.summary_dir.mkdir(parents=True, exist_ok=True)
        self.encoding = tiktoken.get_encoding("cl100k_base")
    
    def _get_api_params(self, model_name: str, model_config: ModelConfig) -> dict:
        """Получает параметры для API вызова с учетом reasoning_effort"""
        params = {}
        # Добавляем reasoning_effort для моделей, которые его поддерживают
        if self.config.get("enable_fast_mode", True):
            if any(x in model_name.lower() for x in ['o3', 'o4', 'o5', 'gpt-5']):
                params['reasoning_effort'] = model_config.reasoning_effort
        return params
    
    def extract_body_content(self, content: str) -> str:
        """Извлекает тело документа после разделителя ---"""
        parts = content.split('---', 1)
        return parts[1].strip() if len(parts) > 1 else content.strip()
    
    def should_skip_file(self, content: str) -> bool:
        """Определяет, нужно ли пропустить файл"""
        skip_markers = [
            '**Type:** Google Drive Folder',
            '[FOLDER]',
            '[SYSTEM FILE]'
        ]
        return any(marker in content for marker in skip_markers)
    
    def count_tokens(self, text: str) -> int:
        """Подсчитывает количество токенов в тексте"""
        return len(self.encoding.encode(text))
    
    def truncate_content_if_needed(self, content: str, model_name: str, reserve_tokens: int = 2000) -> str:
        """Обрезает контент, если он превышает лимит модели"""
        model_config = self.config.get_model_config(model_name)
        max_tokens = model_config.context_size - reserve_tokens
        
        tokens = self.encoding.encode(content)
        if len(tokens) > max_tokens:
            content = self.encoding.decode(tokens[:max_tokens])
            content += "\n\n[Документ обрезан из-за превышения лимита токенов]"
        
        return content
    
    def create_summary(self, content: str, filename: str) -> str:
        """Создает детальное резюме документа"""
        model_name = self.config.get("summary_model")
        model_config = self.config.get_model_config(model_name)
        max_chars = self.config.get("summary_max_chars")
        
        # Обрезаем контент если необходимо
        content = self.truncate_content_if_needed(content, model_name)
        
        prompt = f"""Создай детальное и структурированное резюме документа '{filename}'.

ВАЖНЫЕ ТРЕБОВАНИЯ:
1. На основе содержания документа, создай заголовок, который точно отражает его тему
2. Далее в резюме ОБЯЗАТЕЛЬНО укажи секцию "🎯 ТОЧНОЕ НАЗНАЧЕНИЕ:" где перечисли конкретные задачи и запросы, для которых этот документ ИДЕАЛЬНО подходит
3. Затем добавь секцию "❌ НЕ ПОДХОДИТ ДЛЯ:" где укажи типы задач, для которых этот документ НЕ следует использовать
4. После этого дай подробное резюме основного содержания документа
5. Включи ключевые факты, цифры, термины и важные детали

Максимальная длина резюме: {max_chars} символов

Документ для анализа:
{content}

Структурированное резюме:"""
        
        try:
            # Получаем дополнительные параметры для API
            api_params = self._get_api_params(model_name, model_config)
            
            response = self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system", 
                        "content": """Ты - эксперт по анализу документов. Создавай точные резюме, которые помогают понять:
                        1) Для каких КОНКРЕТНЫХ запросов документ подходит идеально
                        2) Для чего документ категорически НЕ подходит
                        3) Ключевое содержание и важные детали"""
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=model_config.temperature,
                **api_params  # Добавляем reasoning_effort если поддерживается
            )
            
            summary = response.choices[0].message.content.strip()
            
            # Проверяем длину и обрезаем если нужно
            if len(summary) > max_chars:
                summary = summary[:max_chars - 3] + "..."
            
            return summary
            
        except Exception as e:
            error_msg = f"Ошибка при создании резюме: {str(e)}"
            print(f"    ❌ {error_msg}")
            
            # Пробуем fallback на другую модель
            if model_name != "gpt-5-mini":
                print("    🔄 Пробуем резервную модель gpt-5-mini...")
                self.config.config["summary_model"] = "gpt-5-mini"
                return self.create_summary(content, filename)
            
            return error_msg
    
    def process_file(self, file_path: Path) -> bool:
        """Обрабатывает один файл"""
        print(f"\n📄 Обработка: {file_path.name}")
        
        try:
            # Читаем файл
            with open(file_path, 'r', encoding='utf-8') as f:
                full_content = f.read()
            
            # Проверяем, нужно ли пропустить
            if self.should_skip_file(full_content):
                print(f"  → Пропущен (системный файл или папка)")
                return False
            
            # Проверяем существование резюме
            summary_file = self.summary_dir / f"{file_path.stem}_summary.txt"
            if summary_file.exists():
                print(f"  → Резюме уже существует")
                return False
            
            # Извлекаем контент
            body_content = self.extract_body_content(full_content)
            token_count = self.count_tokens(body_content)
            
            print(f"  → Размер: {token_count:,} токенов")
            
            # Показываем режим работы
            reasoning = self.config.get('reasoning_effort', 'minimal')
            speed_emoji = "⚡⚡⚡" if reasoning == "minimal" else "⚡⚡" if reasoning == "low" else "⚡" if reasoning == "medium" else "🔍"
            print(f"  → Создание резюме ({self.config.get('summary_model')}, reasoning: {reasoning} {speed_emoji})")
            
            # Создаем резюме
            start_time = time.time()
            summary = self.create_summary(body_content, file_path.name)
            elapsed = time.time() - start_time
            
            # Сохраняем резюме
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(summary)
            
            # Показываем скорость обработки
            speed_indicator = "🚀" if elapsed < 2 else "✅" if elapsed < 5 else "🐌"
            print(f"  {speed_indicator} Резюме создано за {elapsed:.2f}с")
            return True
            
        except Exception as e:
            print(f"  ❌ Ошибка: {e}")
            return False
    
    def process_directory(self):
        """Обрабатывает все файлы в директории"""
        print("\n" + "=" * 50)
        print("📚 ОБРАБОТКА ДОКУМЕНТОВ")
        print("=" * 50)
        
        # Информация о конфигурации
        print(f"\n⚙️ Конфигурация:")
        print(f"  • Модель для резюме: {self.config.get('summary_model')}")
        print(f"  • Входная папка: {self.source_dir}")
        print(f"  • Папка резюме: {self.summary_dir}")
        print(f"  • Макс. размер резюме: {self.config.get('summary_max_chars')} символов")
        print(f"  • Режим reasoning: {self.config.get('reasoning_effort', 'minimal')} (быстрый)" if self.config.get('enable_fast_mode', True) else "  • Режим reasoning: стандартный")
        print(f"  • Быстрый режим: {'✅ Включен' if self.config.get('enable_fast_mode', True) else '❌ Выключен'}")
        
        # Собираем файлы для обработки
        files_to_process = [
            f for f in self.source_dir.iterdir()
            if f.is_file() and f.suffix in self.TEXT_EXTENSIONS
        ]
        
        if not files_to_process:
            print("\n⚠️ Не найдено файлов для обработки")
            return
        
        print(f"\n📊 Найдено файлов: {len(files_to_process)}")
        print("-" * 50)
        
        # Статистика
        processed = 0
        skipped = 0
        errors = 0
        total_start = time.time()
        
        # Обработка файлов
        for i, file_path in enumerate(files_to_process, 1):
            print(f"\n[{i}/{len(files_to_process)}]", end="")
            
            result = self.process_file(file_path)
            
            if result:
                processed += 1
            else:
                skipped += 1
        
        # Итоговая статистика
        total_time = time.time() - total_start
        
        print("\n" + "=" * 50)
        print("📈 РЕЗУЛЬТАТЫ")
        print("=" * 50)
        print(f"  ✅ Обработано: {processed}")
        print(f"  ⏭️ Пропущено: {skipped}")
        print(f"  ⏱️ Общее время: {total_time:.2f}с")
        if processed > 0:
            avg_time = total_time/processed
            print(f"  ⚡ Среднее время: {avg_time:.2f}с/файл")
            
            # Показываем эффективность reasoning
            reasoning = self.config.get('reasoning_effort', 'minimal')
            if reasoning == 'minimal':
                print(f"  🚀 Режим: Максимальная скорость (reasoning: minimal)")
            elif reasoning == 'low':
                print(f"  ⚡ Режим: Быстрый (reasoning: low)")
            elif reasoning == 'medium':
                print(f"  ⚖️ Режим: Баланс скорости и качества (reasoning: medium)")
            else:
                print(f"  🔍 Режим: Глубокий анализ (reasoning: high)")
            
            # Прогноз времени для разных объемов
            if avg_time < 3:
                print(f"  💡 Совет: Отличная скорость! При таком темпе 100 файлов = ~{(avg_time*100/60):.1f} мин")
            elif avg_time < 10:
                print(f"  💡 Совет: Хорошая скорость. Для ускорения используйте --fast")
            else:
                print(f"  💡 Совет: Используйте --fast или --reasoning minimal для ускорения")


class DocumentRetriever:
    """Система поиска релевантных документов"""
    
    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(api_key=config.get("api_key"))
        self.source_dir = Path(config.get("source_dir"))
        self.summary_dir = Path(config.get("summary_dir"))
        self.encoding = tiktoken.get_encoding("cl100k_base")
    
    def _get_api_params(self, model_name: str, model_config: ModelConfig) -> dict:
        """Получает параметры для API вызова с учетом reasoning_effort"""
        params = {}
        # Добавляем reasoning_effort для моделей, которые его поддерживают
        if self.config.get("enable_fast_mode", True):
            if any(x in model_name.lower() for x in ['o3', 'o4', 'o5', 'gpt-5']):
                params['reasoning_effort'] = model_config.reasoning_effort
        return params
    
    def load_all_summaries(self) -> Dict[str, str]:
        """Загружает все резюме документов"""
        summaries = {}
        
        for summary_file in self.summary_dir.glob("*_summary.txt"):
            try:
                original_name = summary_file.stem.replace('_summary', '')
                with open(summary_file, 'r', encoding='utf-8') as f:
                    summaries[original_name] = f.read()
            except Exception as e:
                print(f"⚠️ Ошибка загрузки {summary_file}: {e}")
        
        return summaries
    
    def select_relevant_files(self, query: str, summaries: Dict[str, str]) -> List[str]:
        """Выбирает наиболее релевантные файлы для запроса"""
        if not summaries:
            return []
        
        files_info = "\n\n".join([
            f"===== ФАЙЛ: {filename} =====\n{summary}"
            for filename, summary in summaries.items()
        ])
        
        prompt = f"""Проанализируй запрос и выбери файлы, которые ТОЧНО подходят для ответа.

ЗАПРОС ПОЛЬЗОВАТЕЛЯ: {query}

ДОСТУПНЫЕ ФАЙЛЫ С ИХ РЕЗЮМЕ:
{files_info}

ИНСТРУКЦИИ:
1. Выбери ТОЛЬКО те файлы, которые содержат информацию, напрямую отвечающую на запрос
2. Обрати внимание на секции "🎯 ТОЧНОЕ НАЗНАЧЕНИЕ" и "❌ НЕ ПОДХОДИТ ДЛЯ" в резюме
3. Упорядочи файлы по релевантности (первый - самый важный)
4. Если ни один файл не подходит точно, ответь: NONE

Ответь ТОЛЬКО списком имен файлов (без расширений), по одному на строку.
Выбранные файлы (в порядке убывания релевантности):"""
        
        model_name = self.config.get("selection_model")
        model_config = self.config.get_model_config(model_name)
        retries = self.config.get("selection_retries")
        
        for attempt in range(retries):
            try:
                # Получаем дополнительные параметры для API
                api_params = self._get_api_params(model_name, model_config)
                
                response = self.client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "Ты - эксперт по поиску релевантных документов. Выбирай только те, что ТОЧНО отвечают на запрос."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,  # Низкая температура для точности
                    **api_params  # Добавляем reasoning_effort если поддерживается
                )
                
                result = response.choices[0].message.content.strip()
                
                if result == "NONE":
                    if attempt < retries - 1:
                        print(f"  Попытка {attempt + 1}: релевантные файлы не найдены")
                        continue
                    return []
                
                # Парсим результат
                selected_files = []
                for line in result.split('\n'):
                    line = line.strip()
                    if line and line in summaries:
                        selected_files.append(line)
                
                if selected_files:
                    return selected_files
                    
            except Exception as e:
                print(f"⚠️ Ошибка при выборе файлов: {e}")
                
                if attempt == retries - 1:
                    return []
        
        return []
    
    def load_file_content(self, filename: str) -> Tuple[str, int]:
        """Загружает содержимое файла"""
        for ext in ['.txt', '.md', '.markdown']:
            file_path = self.source_dir / f"{filename}{ext}"
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Извлекаем тело документа
                    parts = content.split('---', 1)
                    body = parts[1].strip() if len(parts) > 1 else content.strip()
                    tokens = self.count_tokens(body)
                    return body, tokens
        return "", 0
    
    def count_tokens(self, text: str) -> int:
        """Подсчитывает количество токенов"""
        return len(self.encoding.encode(text))


def main():
    """Главная функция приложения"""
    
    parser = argparse.ArgumentParser(
        description="📚 Document Summarizer System - GPT-5+ Models Only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python doc_sum.py --config config.json
  python doc_sum.py -c ./configs/my_config.json --fast
  python doc_sum.py --reasoning minimal  # быстрый режим
  python doc_sum.py --reasoning high  # глубокий анализ
        """
    )
    
    parser.add_argument(
        '-c', '--config',
        type=str,
        default='./NETHACK/herocraft/config_sum.json',
        help='Путь к файлу конфигурации'
    )   
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Подробный вывод'
    )
    
    parser.add_argument(
        '--reasoning',
        type=str,
        choices=['minimal', 'low', 'medium', 'high'],
        help='Уровень reasoning для моделей (minimal=быстро, high=глубоко)'
    )
    
    parser.add_argument(
        '--fast',
        action='store_true',
        help='Быстрый режим (эквивалент --reasoning minimal)'
    )
    
    args = parser.parse_args()
    
    # Проверка конфигурации
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"❌ Файл конфигурации '{args.config}' не найден!")
        print(f"   Создайте файл или укажите правильный путь.")
        sys.exit(1)
    
    # Приветствие
    print("\n" + "=" * 60)
    print("🚀 DOCUMENT SUMMARIZER SYSTEM")
    print("   Поддержка моделей: GPT-5, GPT-5-mini, GPT-5-nano")
    print("=" * 60)
    
    try:
        # Загрузка конфигурации
        config = Config(str(config_path))
        
        # Применяем настройки из CLI
        if args.fast:
            config.config['reasoning_effort'] = 'minimal'
            config.config['enable_fast_mode'] = True
            print("⚡ Включен быстрый режим (reasoning_effort: minimal)")
        elif args.reasoning:
            config.config['reasoning_effort'] = args.reasoning
            config.config['enable_fast_mode'] = True
            print(f"⚙️ Установлен reasoning_effort: {args.reasoning}")
        
        # Обновляем модели с новыми настройками
        config._validate_models()
        
        print(f"\n✅ Конфигурация загружена: {config_path.name}")
        
        if args.verbose:
            print(f"\nДетали конфигурации:")
            print(f"  • API ключ: {'*' * 10}...")
            print(f"  • Входная папка: {config.get('source_dir')}")
            print(f"  • Папка резюме: {config.get('summary_dir')}")
            print(f"  • Модель резюме: {config.get('summary_model')}")
            print(f"  • Reasoning effort: {config.get('reasoning_effort', 'minimal')}")
            print(f"  • Быстрый режим: {'Да' if config.get('enable_fast_mode', True) else 'Нет'}")
        
        # Обработка документов
        processor = DocumentProcessor(config)
        processor.process_directory()
        
        print("\n✨ Обработка завершена успешно!")
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Операция прервана пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()