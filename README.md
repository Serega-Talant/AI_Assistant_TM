# 🔧 ИИ-ассистент для студентов специальности «Технология машиностроения»

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://python.org)
[![LangChain](https://img.shields.io/badge/LangChain-0.3%2B-orange)](https://langchain.com)
[![GigaChat](https://img.shields.io/badge/GigaChat-Freemium-green)](https://developers.sber.ru/portal/products/gigachat)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30%2B-red)](https://streamlit.io)

RAG-система (Retrieval-Augmented Generation) для ответов на вопросы студентов на основе лекций, учебных материалов и глоссария по технологии машиностроения. Ассистент строго опирается на предоставленную базу знаний, минимизируя галлюцинации.

---

## 📌 Особенности

- **Полностью бесплатное решение**:  
  - Эмбеддинги — локальная модель `paraphrase-multilingual-MiniLM-L12-v2` (SentenceTransformers).  
  - Генерация ответов — GigaChat в режиме Freemium (1 млн токенов/мес).  
- **Строгая опора на контекст**: ассистент не придумывает факты, а использует только ваши документы.  
- **Поддержка форматов**: `.txt`, `.pdf`, `.docx`.  
- **Веб-интерфейс** на Streamlit с историей диалога.  
- **Лёгкое развёртывание** через Docker (опционально).

---

## 🧠 Как это работает

1. **Индексация** (`ingest.py`)  
   - Документы из папки `data/` загружаются, разбиваются на смысловые фрагменты.  
   - Локальная модель эмбеддингов преобразует каждый фрагмент в вектор.  
   - Векторы сохраняются в ChromaDB (папка `vector_db/`).  

2. **Ответ на вопрос** (`rag_engine.py` + `app_streamlit.py`)  
   - Вопрос студента векторизуется той же моделью.  
   - ChromaDB находит 4 наиболее похожих фрагмента из базы.  
   - Контекст передаётся в GigaChat с инструкцией отвечать только на его основе.  
   - Ответ возвращается в чат.

---

## ⚙️ Требования

- Python 3.11 или выше  
- Установленные зависимости из `requirements.txt`  
- API-ключ GigaChat (бесплатный для физических лиц)

---

## 🚀 Быстрый старт (локально)

### 1. Клонируйте репозиторий и перейдите в папку

```bash
git clone <url-репозитория>
cd machinery-assistant
```

### 2. Создайте виртуальное окружение и установите зависимости

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Настройте доступ к GigaChat

- Получите **Client ID** и **Client Secret** в личном кабинете [GigaChat API](https://developers.sber.ru/).  
- Сгенерируйте ключ авторизации (Base64 от строки `ClientID:ClientSecret`).  
- Создайте файл `.env` в корне проекта:

```ini
GIGACHAT_CREDENTIALS=ваш_base64_ключ
GIGACHAT_SCOPE=GIGACHAT_API_PERS
```

### 4. Поместите ваши учебные материалы

Скопируйте лекции, глоссарий и другие документы в папку `data/`.  
Поддерживаемые расширения: `.txt`, `.pdf`, `.docx`.

### 5. Запустите индексацию

```bash
python ingest.py
```

При первом запуске загрузится модель эмбеддингов (~420 МБ). Индексация может занять некоторое время в зависимости от объёма данных.

### 6. Запустите веб-интерфейс

```bash
streamlit run app_streamlit.py
```

Откройте браузер по адресу [http://localhost:8501](http://localhost:8501) и начните задавать вопросы.

---

## 🐳 Запуск через Docker

Убедитесь, что у вас установлены Docker и Docker Compose.

### 1. Создайте `.env` и скопируйте данные (как в пункте 3 выше)

### 2. Поместите документы в `data/`

### 3. Соберите и запустите контейнер

```bash
docker-compose up --build
```

После первого запуска необходимо выполнить индексацию **внутри контейнера**:

```bash
docker-compose exec assistant python ingest.py
```

После этого веб-интерфейс будет доступен на порту `8501`.

---

## 📁 Структура проекта

```
.
├── data/                     # Ваши документы (.txt, .pdf, .docx)
├── vector_db/                # Хранилище векторов (создаётся автоматически)
├── .env.example              # Пример файла с переменными окружения
├── .env                      # Реальные ключи (не включается в Git)
├── requirements.txt          # Python-зависимости
├── ingest.py                 # Скрипт индексации базы знаний
├── rag_engine.py             # Ядро RAG-системы
├── app_streamlit.py          # Веб-интерфейс на Streamlit
├── Dockerfile                # Инструкция сборки Docker-образа
├── docker-compose.yml        # Конфигурация Docker Compose
└── README.md                 # Этот файл
```

---

## 🔧 Настройка и доработка

### Смена модели эмбеддингов

В файлах `ingest.py` и `rag_engine.py` замените название модели в строке:

```python
model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
```

на любую другую модель с [HuggingFace Hub](https://huggingface.co/models?pipeline_tag=sentence-similarity&sort=downloads).  
Для русского языка также хорошо подходит `intfloat/multilingual-e5-large`.

### Изменение количества чанков для ответа

В `rag_engine.py` измените параметр `k` в строке:

```python
self.retriever = self.vector_store.as_retriever(search_kwargs={"k": 4})
```

### Обновление базы знаний

При добавлении новых документов удалите папку `vector_db/` и выполните индексацию заново:

```bash
rm -rf vector_db
python ingest.py
```

---

## ❗ Возможные проблемы и решения

| Проблема | Вероятная причина | Решение |
|----------|-------------------|---------|
| `402 Payment Required` при индексации | Используются эмбеддинги GigaChat (платные) | Убедитесь, что в коде используются локальные эмбеддинги HuggingFace |
| `AuthenticationError` | Неверный или просроченный ключ авторизации | Сгенерируйте новый Authorization Key и обновите `.env` |
| `ModuleNotFoundError` | Не установлены все зависимости | Выполните `pip install -r requirements.txt` |
| Предупреждения при загрузке модели | Отсутствует токен HuggingFace | Можно игнорировать или добавить `HF_TOKEN` в `.env` |
| Медленная работа эмбеддингов | Модель работает на CPU | Для ускорения установите `device='cuda'` при наличии GPU |

---

## 📜 Лицензия

Данный проект распространяется под лицензией MIT. Вы можете свободно использовать, модифицировать и распространять его при условии сохранения уведомления об авторских правах.

"# AI_Assistant_TM" 
