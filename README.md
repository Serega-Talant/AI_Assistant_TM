# 🔧 ИИ-ассистент для студентов специальности «Технология машиностроения»

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://python.org)
[![LangChain](https://img.shields.io/badge/LangChain-0.3%2B-orange)](https://langchain.com)
[![GigaChat](https://img.shields.io/badge/GigaChat-Freemium-green)](https://developers.sber.ru/portal/products/gigachat)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30%2B-red)](https://streamlit.io)

RAG-система (Retrieval-Augmented Generation) для ответов на вопросы студентов на основе лекций, учебных материалов и глоссария по технологии машиностроения. Ассистент строго опирается на предоставленную базу знаний, сводя к минимуму выдуманные ответы.

---

## 📌 Особенности

- **Полностью бесплатное решение**:
  - Эмбеддинги — локальная модель `paraphrase-multilingual-MiniLM-L12-v2` (SentenceTransformers).
  - Генерация ответов — GigaChat в режиме Freemium (1 млн токенов/мес).
- **Строгая опора на контекст**: ответ всегда начинается с краткого вывода, затем идёт подробное объяснение. При отсутствии информации в базе ассистент честно сообщает об этом.
- **MMR-поиск**: алгоритм Maximum Marginal Relevance находит разнообразные фрагменты из базы знаний, а не несколько похожих кусков об одном и том же.
- **Устойчивость к сбоям**: при недоступности GigaChat пользователь видит понятное сообщение, а не необработанную ошибку.
- **Поддержка форматов**: `.txt`, `.pdf`, `.docx`.
- **Современный веб-интерфейс** на Streamlit:
  - История диалога в тёмном промышленном дизайне.
  - Встроенная форма обратной связи.
  - Защищённый вход по логину и паролю (PBKDF2-HMAC-SHA256, 310 000 итераций).
  - Автоматическая очистка устаревших сессионных файлов.
- **Безопасное развёртывание** через Docker: секреты не вшиваются в образ.

---

## 🧠 Как это работает

**1. Индексация** (`ingest.py`)

Документы из папки `data/` загружаются, нарезаются на фрагменты по 1000 символов с перекрытием 200. Локальная модель эмбеддингов преобразует каждый фрагмент в вектор, который сохраняется в ChromaDB (папка `vector_db/`).

**2. Ответ на вопрос** (`rag_engine.py`)

Вопрос студента векторизуется той же моделью. ChromaDB с помощью MMR-алгоритма находит 4 наиболее релевантных и разнообразных фрагмента из базы. Контекст **один раз** передаётся в GigaChat вместе с инструкцией отвечать только на его основе — ретривер не вызывается дважды.

**3. Веб-интерфейс** (`app_streamlit.py`)

Ответ отображается в чате с указанием источников. История сохраняется в `sessions/` и восстанавливается при обновлении страницы. При закрытии вкладки браузера сессия завершается и при следующем открытии потребуется повторная авторизация.

---

## 📁 Структура проекта

```text
.
├── data/                     # Ваши документы (.txt, .pdf, .docx)
├── vector_db/                # Хранилище векторов (создаётся при индексации)
├── sessions/                 # Файлы сессий пользователей (создаётся автоматически)
├── .env.example              # Пример переменных окружения
├── .env                      # Реальные ключи (не включается в Git и Docker-образ)
├── .dockerignore             # Исключения для Docker-сборки
├── requirements.txt          # Python-зависимости
├── embeddings.py             # Единая конфигурация модели эмбеддингов
├── ingest.py                 # Скрипт индексации базы знаний
├── rag_engine.py             # Ядро RAG-системы
├── app_streamlit.py          # Веб-интерфейс с авторизацией и обратной связью
├── Dockerfile                # Инструкция сборки Docker-образа
├── docker-compose.yml        # Конфигурация Docker Compose
└── README.md                 # Этот файл
```

---

## ⚙️ Требования

- Python 3.11 или выше
- Docker и Docker Compose (для запуска через Docker)
- API-ключ GigaChat (бесплатный для физических лиц)

---

## 🚀 Запуск через Docker (рекомендуется)

Подробная инструкция — в файле [`DOCKER_GUIDE.md`](DOCKER_GUIDE.md). Краткая последовательность:

### 1. Заполните `.env`

```ini
GIGACHAT_CREDENTIALS=ваш_base64_ключ
GIGACHAT_SCOPE=GIGACHAT_API_PERS
TM_PASSWORD=ваш_надёжный_пароль
```

Как получить `GIGACHAT_CREDENTIALS`: зарегистрируйтесь на [developers.sber.ru](https://developers.sber.ru/), создайте приложение, скопируйте Client ID и Client Secret, закодируйте строку `ClientID:ClientSecret` в Base64.

### 2. Положите документы в `data/`

```bash
mkdir data
# скопируйте сюда лекции, глоссарий и другие учебные материалы
```

### 3. Соберите образ

```bash
docker compose build
```

### 4. Проиндексируйте базу знаний

```bash
docker compose run --rm assistant python ingest.py
```

Запускать при каждом добавлении новых документов (предварительно удалив `vector_db/`).

### 5. Запустите ассистента

```bash
docker compose up -d
```

Откройте [http://localhost:8501](http://localhost:8501), войдите с логином `TM` и паролем из `.env`.

---

## 💻 Локальный запуск (без Docker)

### 1. Создайте виртуальное окружение

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

### 2. Установите зависимости

```bash
pip install -r requirements.txt
```

### 3. Заполните `.env`

```ini
GIGACHAT_CREDENTIALS=ваш_base64_ключ
GIGACHAT_SCOPE=GIGACHAT_API_PERS
TM_PASSWORD=ваш_надёжный_пароль
```

### 4. Положите документы и запустите индексацию

```bash
python ingest.py
```

При первом запуске скачается модель эмбеддингов (~420 МБ).

### 5. Запустите веб-интерфейс

```bash
streamlit run app_streamlit.py
```

---

## 🔧 Настройка

### Смена модели эмбеддингов

Откройте `embeddings.py` и замените значение константы:

```python
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
```

Изменение автоматически применится и в `ingest.py`, и в `rag_engine.py`. После смены модели **обязательно** переиндексируйте базу знаний заново.

Хорошие альтернативы для русского языка: `intfloat/multilingual-e5-large`, `DeepPavlov/rubert-base-cased-sentence`.

### Количество и разнообразие найденных фрагментов

В `rag_engine.py` настройте параметры MMR-поиска:

```python
self.retriever = self.vector_store.as_retriever(
    search_type="mmr",
    search_kwargs={
        "k": 4,            # финальное число фрагментов в контексте
        "fetch_k": 12,     # кандидаты для MMR-отбора (рекомендуется: k × 3)
        "lambda_mult": 0.65  # 1.0 = только релевантность, 0.0 = только разнообразие
    }
)
```

### Ускорение на GPU

В `embeddings.py` замените `"cpu"` на `"cuda"`:

```python
def get_embeddings(device: str = "cuda") -> HuggingFaceEmbeddings:
```

### Добавление пользователей

В `app_streamlit.py` добавьте новую соль, вычислите хеш и добавьте запись в `_VALID_USERS`:

```python
# Генерация новой соли: import os; os.urandom(16).hex()
_NEW_SALT = bytes.fromhex("...")
_NEW_HASH = hashlib.pbkdf2_hmac(
    "sha256",
    os.getenv("NEW_USER_PASSWORD", "").encode("utf-8"),
    _NEW_SALT,
    _PBKDF2_ITERS
).hex()

_VALID_USERS = {
    "TM":       (_TM_SALT, _TM_HASH),
    "STUDENT1": (_NEW_SALT, _NEW_HASH),
}
```

### Обновление базы знаний

```bash
rm -rf vector_db/
python ingest.py          # локально
# или
docker compose run --rm assistant python ingest.py   # через Docker
```

---

## ❗ Возможные проблемы

| Проблема | Вероятная причина | Решение |
|---|---|---|
| `EnvironmentError: TM_PASSWORD не задана` | Переменная не добавлена в `.env` | Добавьте `TM_PASSWORD=...` в `.env` |
| Пустые ответы или «информации нет» | Индексация не запускалась | Выполните `python ingest.py` |
| `AuthenticationError` от GigaChat | Неверный или просроченный ключ | Сгенерируйте новый Authorization Key и обновите `.env` |
| `ModuleNotFoundError` | Не установлены зависимости | Выполните `pip install -r requirements.txt` |
| Предупреждения при загрузке модели | Отсутствует токен HuggingFace Hub | Добавьте `HF_TOKEN=hf_...` в `.env` или игнорируйте |
| Медленная индексация | Модель работает на CPU | Установите `device='cuda'` в `embeddings.py` при наличии GPU |
| Порт 8501 занят | Другой процесс использует порт | В `docker-compose.yml` замените `"8501:8501"` на `"8502:8501"` |

---

## 📜 Лицензия

Проект распространяется под лицензией MIT. Вы можете свободно использовать, модифицировать и распространять его при условии сохранения уведомления об авторских правах.

---

**Удачи в учёбе и разработке!**
По вопросам и предложениям — открывайте Issue в репозитории.
