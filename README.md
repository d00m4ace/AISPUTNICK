# AISPUTNICK / ИИ Спутник телеграм бот

Привет всем! Я записал ряд видео того, как работает ИИ Спутник Telegram бот. Это универсальный ИИ-помощник для компаний и их сотрудников, доступный прямо в Telegram.

Полный код ИИ Спутник выкладываю как есть для ознакомления и пробного запуска самостоятельно. 
Обновления и доводка под организации тут отсутствуют, но базовый функционал доступен и работает.

Лично бесплатно помощь в настройке и запуске не оказываю.

Платные консультации только по его внедрение для организаций.
Пишите в личку ТГ: @d00m4ace

Есть возможность оформить договор на ООО или купить платные консалтинговые часы по запросу.

Краткое введение в AI Sputnik Телеграм-бот .pdf файл:
https://d00m4ace.com/files/ai_sputnik_telegram_bot.pdf

# 🤖 Руководство по агентам и возможностям системы

## 📚 Агент @nethack — ИИ база знаний компании

**Видео:**
- [YouTube](https://www.youtube.com/watch?v=kz1s13YF-hA)
- [VK Видео](https://vkvideo.ru/video-233018674_456239021)

### Возможности:
- ✅ Обрабатывает документы по ссылкам из сети
- ✅ Работает в режиме «вопрос/ответ»
- ✅ Управляет доступом к документам
- ✅ Автоматически синхронизирует данные для ИИ

---

## 💬 Агент @chat — Интерактивный диалог

**Видео:**
- [YouTube](https://www.youtube.com/watch?v=jGzTqk06EU8)
- [VK Видео](https://vkvideo.ru/video-233018674_456239025)

### Возможности:
- 💬 Текстовые сообщения для диалога
- 📎 Добавление текстовых файлов в контекст

### Управление историей чата:
| Команда | Описание |
|---------|----------|
| `save [ID]` | Сохранить текущую историю |
| `load [ID]` | Загрузить сохраненную историю |
| `delete [ID]` | Удалить сохраненную историю |
| `rename [старый] [новый]` | Переименовать историю |
| `list` | Показать список историй (до 50 чатов) |

---

## 🗂️ Работа с кодовыми базами

**Пример работы агентов @rag и @filejob**

**Видео:**
- [YouTube](https://www.youtube.com/watch?v=NcJ6E4JCzmk)
- [VK Видео](https://vkvideo.ru/video-233018674_456239022)

> 💡 **Аналогия:** Работает как обычная папка в Windows

Все файлы автоматически конвертируются в текст с разметкой Markdown при добавлении.

---

## 🌐 Публичная кодовая база

**Видео:**
- [YouTube](https://www.youtube.com/watch?v=qIV0ZcBxC6s)
- [VK Видео](https://vkvideo.ru/video-233018674_456239023)

Доступна для работы агентов других пользователей, например **@rag**.

---

## 🔄 Автоматическое преобразование файлов

**Видео:**
- [YouTube](https://www.youtube.com/watch?v=2ENHPF1mEmo)
- [VK Видео](https://vkvideo.ru/video-233018674_456239024)

### Поддерживаемые форматы:

**📝 Текст и код:**
`.txt`, `.md`, `.c`, `.py`, `.js`, `.json`, `.xml` и др.

**📄 Документы:**
`.docx`, `.rtf`, `.odt`

**📊 Таблицы:**
`.xlsx`, `.xls`, `.csv`

**📽️ Презентации:**
`.pptx`, `.ppt`

**📕 PDF:**
`.pdf`

**🌐 Веб:**
`.html`

**🖼️ Изображения:**
`.jpg`, `.png`, `.gif` и др.

**🎵 Аудио:**
`.mp3`, `.wav`, `.ogg`, `.m4a` и др.

---

*Все файлы автоматически преобразуются в текстовый формат и сохраняются в кодовой базе.*

## Установка зависимостей:

*****
poppler for windows

https://github.com/oschwartz10612/poppler-windows

```add to PATH: C:\poppler-25.07.0\Library\bin```
*****
pandoc for windows 

https://github.com/jgm/pandoc/releases/tag/3.7.0.2

https://github.com/jgm/pandoc/releases/download/3.7.0.2/pandoc-3.7.0.2-windows-x86_64.msi
*****
ffmpeg:

https://www.ffmpeg.org/download.html

```add to PATH: C:\ffmpeg\bin```
*****
Tesseract OCR:

Windows: https://github.com/UB-Mannheim/tesseract/wiki

Linux: sudo apt-get install tesseract-ocr tesseract-ocr-rus

Mac: brew install tesseract

```add to PATH: C:\Program Files\Tesseract-OCR```
*****

***************
---

# 🪙 Получение Yandex OAuth-токена

Эта инструкция поможет вам зарегистрировать приложение на [Yandex OAuth](https://oauth.yandex.ru), настроить права доступа и получить **токен авторизации**, необходимый для работы с API (например, **Yandex.Disk API** или другими сервисами Яндекса).

---

## 🧩 1. Регистрация приложения

1. Перейдите на страницу регистрации приложений:
   👉 [https://oauth.yandex.ru](https://oauth.yandex.ru)

2. Нажмите **«Зарегистрировать новое приложение»**.

3. Заполните поля:

   * **Название приложения:**
     любое удобное название (например, `SuperBot Disk Access`).
   * **Платформа:**
     выберите **«Веб-сервисы»**.
   * **Callback URI:**

     ```
     https://oauth.yandex.ru/verification_code
     ```

4. В разделе **Доступы** отметьте нужные разрешения:

   | Разрешение                  | Назначение                                                   |
   | --------------------------- | ------------------------------------------------------------ |
   | `cloud_api:disk.app_folder` | доступ к специальной папке приложения                        |
   | `cloud_api:disk.read`       | чтение всего содержимого диска                               |
   | `cloud_api:disk.write`      | запись файлов на диск                                        |
   | `cloud_api:disk.info`       | получение информации о диске (размер, использование и т. д.) |

   > 💡 Если вам нужен только просмотр, достаточно `cloud_api:disk.read` и `cloud_api:disk.info`.

5. Нажмите **Создать приложение**.

---

## 🔑 2. Получение Client ID и Client Secret

После регистрации появится страница приложения, где вы увидите:

```
Client ID:     5...0
Client Secret: b...b
```

Запомните или сохраните эти значения — они понадобятся для авторизации.

---

## 🌐 3. Укажите Redirect URI

Для веб-сервисов необходимо использовать стандартный адрес обратного вызова (redirect URI):

```
https://oauth.yandex.ru/verification_code
```

---

## 🚀 4. Получение OAuth-токена вручную

Чтобы получить токен без SDK, используйте следующий URL:

```
https://oauth.yandex.ru/authorize?response_type=token&client_id=CLIENT_ID
```

Замените `CLIENT_ID` на свой реальный идентификатор приложения.

**Пример:**

```
https://oauth.yandex.ru/authorize?response_type=token&client_id=5...0
```

### ➤ Что произойдёт:

1. Откроется страница авторизации Яндекса.
2. Войдите в свой аккаунт (если не вошли).
3. Разрешите приложению доступ к указанным правам.
4. После редиректа вы попадёте на страницу с адресом вроде:

```
https://oauth.yandex.ru/verification_code#access_token=y0_AQAAA...ZDg&token_type=bearer&expires_in=31536000
```

---

## 📋 5. Скопируйте токен

Ваш токен — это значение после `access_token=`
Например:

```
y0_AQAAA...ZDg
```

💡 Этот токен вы используете в запросах к API Яндекса:

```bash
curl -H "Authorization: OAuth y0_AQAAA...ZDg" \
     https://cloud-api.yandex.net/v1/disk/
```

---

## 🧰 6. Пример использования в Python

```python
import requests

token = "y0_AQAAA...ZDg"
headers = {"Authorization": f"OAuth {token}"}

response = requests.get("https://cloud-api.yandex.net/v1/disk", headers=headers)
info = response.json()

print("Доступно:", info.get("total_space") / 1e9, "ГБ")
print("Использовано:", info.get("used_space") / 1e9, "ГБ")
```

---

## ⚠️ 7. Безопасность

* Храните токен в **переменных окружения** или **секретных хранилищах** (например, `.env`, Secret Manager).
* Не публикуйте токен в GitHub или открытых источниках.
* Если токен утёк — **отозовите** его через [https://oauth.yandex.ru](https://oauth.yandex.ru) и создайте новый.

---

## ✅ Готово!

Теперь вы получили:

* 🔹 **Client ID** и **Client Secret**
* 🔹 **OAuth-токен** (`y0_AQAAA...ZDg`)
* 🔹 Рабочий доступ к API Яндекса (Disk, Cloud и др.)

---

***************

JSON-ключ сервисного аккаунта Google Cloud (Service Account Key).

---

# 🔐 Настройка сервисного аккаунта Google Cloud для проекта `superbotai`

Этот документ описывает процесс создания и настройки сервисного аккаунта с полным доступом к основным Google API: **Drive**, **Sheets**, **BigQuery**, **Cloud Storage**, **Docs**, **Slides**, и другим.

---

## 🧩 1. Вход в Google Cloud Console

Перейдите в панель управления Google Cloud:
👉 [https://console.cloud.google.com/](https://console.cloud.google.com/)

Убедитесь, что вы вошли под аккаунтом с правами администратора и выберите проект **superbotai** (или создайте новый при необходимости).

---

## 👤 2. Создание сервисного аккаунта

1. Откройте раздел **IAM & Admin → Service Accounts**
   [https://console.cloud.google.com/iam-admin/serviceaccounts](https://console.cloud.google.com/iam-admin/serviceaccounts)
2. Нажмите **Create Service Account**.
3. Укажите:

   * **Name:** `superbotai`
   * **Description:** Сервисный аккаунт для доступа к API
4. Нажмите **Create and continue**.
5. Добавьте базовые роли (можно позже отредактировать).
6. Нажмите **Done**.

---

## 🔑 3. Создание ключа JSON

1. Найдите созданный аккаунт в списке.
2. Перейдите на вкладку **Keys**.
3. Нажмите **Add key → Create new key**.
4. Выберите формат **JSON**.
5. Нажмите **Create** — файл автоматически скачается.

📄 **Этот файл выглядит примерно так:**

```json
{
  "type": "service_account",
  "project_id": "superbotai",
  "private_key_id": "40...30",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMI...jj\n-----END PRIVATE KEY-----\n",
  "client_email": "superbotai@superbotai.iam.gserviceaccount.com",
  "client_id": "10...7",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/superbotai%40superbotai.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}
```

💡 Этот файл нужно хранить **в секрете** — не размещайте его в GitHub, не пересылайте через мессенджеры и не публикуйте публично.

---

## ⚙️ 4. Активация необходимых API

Перейдите в раздел
👉 [**APIs & Services → Library**](https://console.cloud.google.com/apis/library)

Для проекта `superbotai` включите (Enable) следующие API:

| Категория                    | API                                                                                                 |
| ---------------------------- | --------------------------------------------------------------------------------------------------- |
| **Документы и Таблицы**      | Google Drive API, Google Sheets API, Google Docs API, Google Slides API                             |
| **Хранилище и данные**       | Cloud Storage API, Google Cloud Storage JSON API, BigQuery API, BigQuery Storage API                |
| **BigQuery экосистема**      | BigQuery Connection API, BigQuery Data Policy API, BigQuery Migration API, BigQuery Reservation API |
| **Мониторинг и логирование** | Cloud Logging API, Cloud Monitoring API, Cloud Trace API                                            |
| **Базы и аналитика**         | Cloud Datastore API, Cloud SQL Admin API, Analytics Hub API, Dataform API                           |
| **Инфраструктура и сервисы** | Cloud Dataplex API, Service Management API, Service Usage API, Google Cloud APIs                    |

После включения каждый сервис отобразится в списке активных API вашего проекта.

---

## 🧱 5. Назначение ролей сервисному аккаунту

Перейдите в:
**IAM & Admin → IAM**
[https://console.cloud.google.com/iam-admin/iam](https://console.cloud.google.com/iam-admin/iam)

Найдите аккаунт `superbotai@superbotai.iam.gserviceaccount.com` и нажмите **Edit principal**.
Добавьте следующие роли:

| API                        | Роль                                                        |
| -------------------------- | ----------------------------------------------------------- |
| Google Drive               | `roles/drive.admin` или `roles/drive.file`                  |
| Google Sheets              | `roles/sheets.editor`                                       |
| Google Docs                | `roles/docs.editor`                                         |
| Google Slides              | `roles/slides.editor`                                       |
| BigQuery                   | `roles/bigquery.admin`                                      |
| BigQuery Storage           | `roles/bigquerystorage.admin`                               |
| Cloud Storage              | `roles/storage.admin`                                       |
| Cloud SQL                  | `roles/cloudsql.admin`                                      |
| Cloud Logging              | `roles/logging.admin`                                       |
| Cloud Monitoring           | `roles/monitoring.admin`                                    |
| Cloud Trace                | `roles/cloudtrace.admin`                                    |
| Dataform                   | `roles/dataform.admin`                                      |
| Dataplex                   | `roles/dataplex.admin`                                      |
| Service Management / Usage | `roles/servicemanagement.admin`, `roles/serviceusage.admin` |

> 💡 Можно добавить несколько ролей сразу, нажав **Add another role**.

---

## 🧾 6. Проверка прав и активности

Проверьте, что всё работает корректно:

```bash
# Аутентификация через ключ
gcloud auth activate-service-account --key-file=superbotai-key.json

# Просмотр активированных API
gcloud services list --enabled

# Проверка BigQuery
gcloud bigquery datasets list

# Проверка Cloud Storage
gcloud storage buckets list
```

Если команды выполняются без ошибок — настройки успешны ✅

---

## 🧰 7. Использование в коде

Пример использования ключа в Python:

```python
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Укажите путь к JSON-файлу
creds = service_account.Credentials.from_service_account_file("superbotai-key.json")

# Пример: подключение к Google Drive
service = build("drive", "v3", credentials=creds)
results = service.files().list(pageSize=10).execute()
print(results.get("files", []))
```

---

## ⚠️ 8. Безопасность и управление ключами

* Не храните ключ в общих репозиториях.
* Храните файл в **Google Secret Manager** или шифруйте с помощью KMS.
* При утечке — **немедленно удалите** старый ключ и создайте новый:

  * **Service Account → Keys → Delete Key → Create New Key**

---

## ✅ Готово!

Теперь ваш сервисный аккаунт полностью готов к работе с:

* Google Drive
* Google Sheets
* Google Docs
* Google Slides
* BigQuery
* Cloud Storage
* И другими сервисами Google Cloud.

---


