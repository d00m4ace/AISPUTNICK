# AISPUTNICK / ИИ Спутник телеграм бот

Привет всем! Я записал ряд видео того, как работает ИИ Спутник Telegram бот. Это универсальный ИИ-помощник для компаний и их сотрудников, доступный прямо в Telegram.

Полный код ИИ Спутник выкладываю как есть для ознакомления и пробного запуска самостоятельно. 
Обновления и доводка под организации тут отсутствуют, но базовый функционал доступен и работает.
Лично бесплатно помощь в настройке и запуске не оказываю.

Оказываю платные консультации только по его внедрение для организаций.
Пишите в личку ТГ: @d00m4ace
Есть возможность оформить договор на ООО или купить платные консалтинговые часы по запросу.

Краткое введение в AI Sputnik Телеграм-бот .pdf файл:
https://d00m4ace.com/files/ai_sputnik_telegram_bot.pdf

Агент @nethack
YT видео: https://www.youtube.com/watch?v=kz1s13YF-hA
VK видео: https://vkvideo.ru/video-233018674_456239021
@nethack - ИИ онлайн база знаний компании.
Он умеет:  
✅ Обрабатывать документы по ссылкам из сети
✅ Работать в простом режиме «вопрос/ответ»
✅ Управлять доступом к документам
✅ Автоматически синхронизировать данные для ИИ

Агент @chat
YT видео: https://www.youtube.com/watch?v=jGzTqk06EU8
VK видео: https://vkvideo.ru/video-233018674_456239025
Возможности:
 💬 Отправляйте текстовые сообщения для диалога
 📎 Отправьте текстовый файл для добавления в контекст
 📚 Управление историей чата:
 • save [ID] - сохранить текущую историю
 • load [ID] - загрузить сохраненную историю
 • delete [ID] - удалить сохраненную историю
 • rename [старый] [новый] - переименовать историю
 • list - показать список сохраненных историй (до 50 чатов) 

Основа работы с кодовыми базами (пример работы двух агентов @rag и @filejob)
YT видео: https://www.youtube.com/watch?v=NcJ6E4JCzmk
VK видео: https://vkvideo.ru/video-233018674_456239022
Хорошая ассоциация с обычной папкой в Windows.
Все файлы при отправки в папку автоматически конвертируются в текстовые с разметкой MarkDown.

Публичная кодовая база
YT видео: https://www.youtube.com/watch?v=qIV0ZcBxC6s
VK видео: https://vkvideo.ru/video-233018674_456239023
Доступна для работы агентов других пользователей, например @rag

Автоматическое преобразование различных типов файлов в текст и сохранение в кодовой базе
VK видео: https://www.youtube.com/watch?v=2ENHPF1mEmo
YT видео: https://vkvideo.ru/video-233018674_456239024
Поддерживаются:
• Текстовые файлы (.txt, .md, .c, .py, .js, .json, .xml и др.)
• Документы (.docx, .rtf, .odt)
• Таблицы (.xlsx, .xls, .csv)
• Презентации (.pptx, .ppt)
• PDF файлы
• HTML файлы
• Изображения (.jpg, .png, .gif и др.)
• Аудио файлы (.mp3, .wav, .ogg, .m4a и др.)

## Установка зависимостей:

*****
pip install pandas pillow pdf2image chardet aiofiles
*****
https://github.com/microsoft/markitdown
pip install markitdown[all]
*****
HTML conversion
pip install markdownify
*****
PowerPoint conversion  
pip install pptx2md python-pptx
*****
Для PDF страниц сканирования:
Windows: poppler скачать с https://github.com/oschwartz10612/poppler-windows
add to PATH: C:\poppler-25.07.0\Library\bin
*****
pandas
pip install pandas pillow pdf2image chardet aiofiles
*****
pandoc 
need install pandoc for windows https://github.com/jgm/pandoc/releases/tag/3.7.0.2
https://github.com/jgm/pandoc/releases/download/3.7.0.2/pandoc-3.7.0.2-windows-x86_64.msi
*****
Для работы с большими файлами потребуется установить ffmpeg:
https://www.ffmpeg.org/download.html
add to PATH: C:\ffmpeg\bin
*****
# Также нужно установить Tesseract OCR:
# Windows: https://github.com/UB-Mannheim/tesseract/wiki
# Linux: sudo apt-get install tesseract-ocr tesseract-ocr-rus
# Mac: brew install tesseract
add to PATH: C:\Program Files\Tesseract-OCR
***************
C:\projects\python\SuperBotAI>path
PATH=C:\Python313\Scripts\;C:\Python313\;C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0\;C:\Windows\System32\OpenSSH\;C:\Program Files (x86)\NVIDIA Corporation\PhysX\Common;C:\Program Files\Git\cmd;C:\w64devkit\bin;C:\ffmpeg\bin;C:\curl;C:\Program Files (x86)\Windows Kits\10\Windows Performance Toolkit\;C:\poppler-25.07.0\Library\bin\;C:\Program Files\PowerShell\7\;C:\Program Files\Tesseract-OCR;C:\Users\d00m4ace\AppData\Local\Microsoft\WindowsApps;C:\Users\d00m4ace\AppData\Local\Pandoc\
***************
получить yandex.ru токен

1. Зарегистрируйте приложение:
   - Перейдите на https://oauth.yandex.ru
   - Нажмите "Зарегистрировать новое приложение"
   - Укажите название приложения
   - В разделе "Платформы" выберите "Веб-сервисы"
   - В "Callback URI" укажите: https://oauth.yandex.ru/verification_code
   - В разделе "Доступы" выберите:
     * cloud_api:disk.app_folder - доступ к папке приложения
     * cloud_api:disk.read - чтение всего диска
     * cloud_api:disk.write - запись на диск (если нужно)
     * cloud_api:disk.info - информация о диске

2. Получите токен:
   - После создания приложения получите Client ID
   - Перейдите по ссылке (замените CLIENT_ID на ваш):
     https://oauth.yandex.ru/authorize?response_type=token&client_id=CLIENT_ID
   - Авторизуйтесь и разрешите доступ
   - Скопируйте токен из URL после редиректа
   
https://oauth.yandex.ru/
     
ClientID   5...0
Client secret   b...b

Redirect URI для веб-сервисов
https://oauth.yandex.ru/verification_code

https://oauth.yandex.ru/authorize?response_type=token&client_id=5...0
в окне браузера после авторизации увидите:
токен
y0__...ZDg

***************
JSON-ключ сервисного аккаунта Google Cloud (Service Account Key).

---

### 🧩 1. Войдите в Google Cloud Console

Перейдите по адресу:
👉 [https://console.cloud.google.com/](https://console.cloud.google.com/)

Убедитесь, что вы вошли под аккаунтом, у которого есть доступ к нужному проекту (`project_id` у вас — `superbotai`).

---

### ⚙️ 2. Выберите проект

В верхнем меню выберите ваш проект **superbotai**
(или создайте новый, если его ещё нет).

---

### 👤 3. Перейдите в раздел **IAM & Admin → Service Accounts**

* Слева в меню: **IAM & Admin → Service Accounts**
  (или напрямую: [https://console.cloud.google.com/iam-admin/serviceaccounts](https://console.cloud.google.com/iam-admin/serviceaccounts))
* Найдите существующий сервисный аккаунт
  или нажмите **Create Service Account**.

---

### 🧱 4. Создайте сервисный аккаунт (если нужно)

Укажите:

* **Name:** например, `superbotai`
* **ID:** генерируется автоматически
* **Description:** любое описание

Нажмите **Create and continue**

Затем:

* Добавьте нужные роли (например, `Editor`, `Storage Admin`, `BigQuery User` — зависит от целей)
* Нажмите **Done**

---

### 🔑 5. Создайте ключ

Когда аккаунт создан:

1. Откройте его в списке.
2. Перейдите на вкладку **Keys**
3. Нажмите **Add key → Create new key**
4. Выберите формат: **JSON**
5. Нажмите **Create**

Файл с ключом автоматически скачается на ваш компьютер — это именно тот JSON, который вы показали в примере.

---

### ⚠️ 6. Безопасность

* Этот файл содержит **приватный ключ**, его **нельзя публиковать** или отправлять в публичные репозитории.
* Если файл утёк — **немедленно удалите ключ** и создайте новый.

Удалить можно в том же разделе “Keys” — кнопка **Delete key**.

---

### ✅ 7. Использование

Для подключения, например, к Google API, используйте переменную окружения:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"
```

---


