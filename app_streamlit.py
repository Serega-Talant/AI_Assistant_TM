"""
app_streamlit.py — веб-интерфейс RAG-ассистента на Streamlit.

Этот файл — «лицо» всего приложения: именно здесь происходит всё, что видит
и с чем взаимодействует пользователь. Остальные модули (rag_engine.py,
embeddings.py, ingest.py) работают «под капотом» и не имеют собственного UI.

Архитектура интерфейса:
  • Сессии: каждая вкладка браузера получает уникальный UUID, который
    сохраняется в браузере как сессионная cookie и на сервере как JSON-файл
    в папке sessions/. F5 → cookie жива → история восстанавливается.
    Закрытие вкладки → браузер удаляет сессионную cookie → при следующем
    открытии начинается чистая сессия с пустой историей.
  • Чат: история хранится в st.session_state (оперативная память Streamlit)
    и дублируется в JSON-файл на диске (персистентность между перезагрузками).
  • Безопасность: ответы ассистента проходят XSS-фильтрацию до рендеринга —
    это блокирует попытки внедрить вредоносный JavaScript через Markdown-ссылки.
  • UX: тёмный промышленный дизайн, CSS-анимации, встроенная форма обратной
    связи через Яндекс Формы в боковой панели.

Поток выполнения при каждом запросе пользователя:
  Ввод текста → sanitize_markdown_links (XSS-фильтр) → MachineryAssistant.ask()
  → получение ответа и источников → sanitize_markdown_links → st.markdown

Зависимости:
  • rag_engine.py  — класс MachineryAssistant (RAG-ядро)
  • sessions/      — JSON-файлы истории диалогов (создаётся автоматически)
  • .env           — GIGACHAT_CREDENTIALS, GIGACHAT_SCOPE (читает rag_engine.py)
"""
import streamlit as st
from rag_engine import MachineryAssistant
import streamlit.components.v1 as components  # для вставки произвольного HTML/JS в iframe
import time
import re
import html as html_module  # стандартная библиотека Python для html.unescape
import uuid                 # для генерации глобально уникальных идентификаторов сессий
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# КОНСТАНТЫ И ИНИЦИАЛИЗАЦИЯ ПАПКИ СЕССИЙ
# ---------------------------------------------------------------------------
# Каждая активная вкладка браузера = один JSON-файл в sessions/.
# Имя файла: session_<uuid4>.json
# Несколько пользователей открывают приложение одновременно → несколько
# файлов → полная изоляция историй диалогов друг от друга.
#
# Path("sessions") — путь относительно рабочей директории запуска
# (обычно корень проекта). mkdir(exist_ok=True) — не падает если папка уже есть.
SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# XSS-ЗАЩИТА: ФИЛЬТРАЦИЯ MARKDOWN-ССЫЛОК
# ---------------------------------------------------------------------------
# Проблема: st.markdown() рендерит ссылки из текста ответа ассистента.
# GigaChat теоретически может вернуть ответ, содержащий вредоносную ссылку
# вида [нажмите](javascript:document.cookie) — браузер исполнит JS-код,
# что позволит злоумышленнику украсть cookies или выполнить другие действия.
#
# Атаки через нестандартные схемы:
#   javascript:alert(1)           — прямое выполнение JS
#   data:text/html,<script>...    — встроенный HTML-документ с JS
#   vbscript:MsgBox(1)            — VBScript (старый IE)
#   java\nscript:alert(1)         — обход фильтров через управляющие символы
#   &#106;avascript:alert(1)      — обход через HTML-сущности (j = &#106;)
#
# Решение: whitelist-подход — разрешаем только явно безопасные схемы.
# Всё остальное заменяется на '#' (безопасная ссылка-якорь, ни к чему не ведёт).

# Разрешённые схемы URL (регистронезависимо):
#   https://, http:// — обычные веб-ссылки
#   mailto:           — ссылки на email
#   tel:              — ссылки на телефонный звонок
_SAFE_SCHEMES = re.compile(r'^(https?|mailto|tel)://', re.IGNORECASE)

# Паттерн для поиска всех Markdown-ссылок в тексте:
#   \[([^\]]*)\]  — группа 1: текст ссылки в квадратных скобках
#   \(([^)]*)\)   — группа 2: URL в круглых скобках
_MD_LINK = re.compile(r'\[([^\]]*)\]\(([^)]*)\)')


def sanitize_markdown_links(text: str) -> str:
    """
    Фильтрует небезопасные URL во всех Markdown-ссылках текста.

    Вызывается дважды:
      1. До сохранения вопроса пользователя — защита от намеренного ввода XSS.
      2. До рендеринга ответа ассистента — защита от XSS в контенте GigaChat.

    Алгоритм для каждой найденной ссылки [label](url):
      1. Извлекаем label и url_raw из групп регулярного выражения.
      2. html.unescape() декодирует HTML-сущности:
         &amp; → &, &#106; → j, &lt; → < и т.д.
         Это важно: «&#106;avascript:» после декодирования становится «javascript:»
      3. re.sub(r'[\s\x00-\x1f]+', ...) удаляет все пробелы и управляющие
         символы (коды 0x00–0x1F). Без этого «java\nscript:» обходил бы фильтр.
      4. Проверяем нормализованный URL по whitelist:
         — _SAFE_SCHEMES.match()  — разрешённые схемы (https, http, mailto, tel)
         — startswith('#')        — якоря (#section) — безопасны
         — startswith('/')        — относительные пути (/page) — безопасны
      5. Если проверка не пройдена — заменяем URL на '#'.

    Функция не изменяет текст без ссылок и не трогает разрешённые ссылки.
    """
    def replace_link(m: re.Match) -> str:
        label = m.group(1)
        url_raw = m.group(2).strip()

        # Шаг 2: декодируем HTML-сущности перед проверкой
        url = html_module.unescape(url_raw)

        # Шаг 3: убираем все пробелы и управляющие символы
        url_normalized = re.sub(r'[\s\x00-\x1f]+', '', url)

        # Шаг 4: проверяем по whitelist
        if _SAFE_SCHEMES.match(url_normalized) or url_normalized.startswith(('#', '/')):
            # URL безопасен — возвращаем ссылку без изменений (с исходным url_raw,
            # не нормализованным — чтобы не ломать нормальные ссылки)
            return f'[{label}]({url})'

        # Шаг 5: URL опасен — заменяем заглушкой
        return f'[{label}](#)'

    return _MD_LINK.sub(replace_link, text)


# ---------------------------------------------------------------------------
# УПРАВЛЕНИЕ СЕССИОННЫМИ КУКАМИ ЧЕРЕЗ JAVASCRIPT
# ---------------------------------------------------------------------------
# Ограничение Streamlit: в отличие от Flask или FastAPI, Streamlit не имеет
# встроенного API для работы с HTTP-cookies на стороне сервера.
# Единственный способ установить cookie — выполнить JS в браузере через
# components.html(), который рендерит произвольный HTML в скрытом iframe.
#
# Атрибуты cookie безопасности:
#   path=/        — кука передаётся для всех путей домена, а не только
#                   текущего пути. Без этого после редиректа кука пропадёт.
#   SameSite=Lax  — браузер не отправляет куку при запросах с других сайтов
#                   (защита от CSRF-атак). Lax (а не Strict) разрешает
#                   переходы по обычным ссылкам — это нужно для работы.
#   Secure        — кука передаётся только по HTTPS. Добавляем динамически
#                   (через JS location.protocol) — на localhost HTTP нормален,
#                   на продакшн-сервере с HTTPS нужна эта защита.
#
# Почему сессионная кука (без атрибута max-age / expires):
#   Браузер хранит «сессионные» куки только до закрытия вкладки/окна.
#   Это реализует требуемую логику: каждое новое открытие = новая чистая сессия.
#   Если бы max-age был установлен, история сохранялась бы между сессиями,
#   что нежелательно на публичном учебном компьютере.

def set_session_cookie(name: str, value: str) -> None:
    """
    Устанавливает сессионную cookie в браузере через инъекцию JS.

    Параметры:
        name  — имя cookie (используем 'session_id')
        value — значение cookie (UUID4 сессии)

    После вызова cookie появится в браузере и будет доступна при следующей
    загрузке страницы через st.context.cookies.get(name).
    height=0 — iframe невидим, занимает 0 пикселей высоты.
    """
    components.html(
        f"""
        <script>
        var isSecure = (location.protocol === 'https:') ? '; Secure' : '';
        document.cookie = "{name}={value}; path=/; SameSite=Lax" + isSecure;
        </script>
        """,
        height=0,
    )


def delete_cookie(name: str) -> None:
    """
    Удаляет cookie из браузера через инъекцию JS.

    Механизм удаления: установка max-age=-1 заставляет браузер немедленно
    «просрочить» куку и удалить её. Атрибуты path и SameSite должны
    совпадать с теми, что были при создании — иначе браузер посчитает
    это разными куками и не удалит нужную.
    """
    components.html(
        f"""
        <script>
        var isSecure = (location.protocol === 'https:') ? '; Secure' : '';
        document.cookie = "{name}=; max-age=-1; path=/; SameSite=Lax" + isSecure;
        </script>
        """,
        height=0,
    )


# ---------------------------------------------------------------------------
# КОНФИГУРАЦИЯ СТРАНИЦЫ STREAMLIT
# ---------------------------------------------------------------------------
# ВАЖНО: set_page_config() ОБЯЗАН быть первым вызовом st.* в скрипте.
# Streamlit выполняет этот вызов при первой загрузке и при каждом rerun.
# Если вызвать его после любого другого st.* — Streamlit выбросит исключение.
#
# layout="centered" — контент располагается по центру с максимальной шириной
# ~730px. Альтернатива: "wide" — растягивается на всю ширину браузера.
# Для чат-интерфейса "centered" предпочтительнее — удобнее читать.
st.set_page_config(
    page_title="Ассистент по Технологии машиностроения",
    page_icon="⚙️",
    layout="centered",
)

# ---------------------------------------------------------------------------
# КАСТОМНЫЕ СТИЛИ CSS
# ---------------------------------------------------------------------------
# Streamlit использует Material UI под капотом, но позволяет переопределять
# стили через st.markdown с unsafe_allow_html=True.
#
# Дизайн-концепция: тёмная «промышленная» тема, вдохновлённая техническими
# чертежами. Фоновая сетка имитирует миллиметровую бумагу. Акцентный цвет
# #dd6b20 (насыщенный оранжевый) отсылает к промышленным цветовым схемам.
#
# Шрифты загружаются с Google Fonts:
#   Inter        — основной UI-шрифт (читаемый, современный, без засечек)
#   JetBrains Mono — моноширинный шрифт для кода и технических данных
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400&display=swap');

    /* Фон приложения: тёмный (#0b0f13) + тонкая сетка 32×32px.
       Два overlapping linear-gradient создают горизонтальные и вертикальные
       линии с очень низкой прозрачностью (0.018) — едва заметная сетка. */
    .stApp {
        background-color: #0b0f13; 
        background-image: 
            linear-gradient(rgba(255, 255, 255, 0.018) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255, 255, 255, 0.018) 1px, transparent 1px);
        background-size: 32px 32px;
        font-family: 'Inter', sans-serif;
    }
    body, .stMarkdown, p, li { color: #b0b7c3; }
    h1, h2, h3, h4, h5, h6 { color: #e2e8f0; font-weight: 600; letter-spacing: -0.3px; }

    /* Inline-код и блоки кода — оранжевый на тёмном фоне */
    code {
        font-family: 'JetBrains Mono', monospace;
        color: #f6ad55 !important; 
        background-color: rgba(246, 173, 85, 0.12) !important;
        border-radius: 4px;
        padding: 2px 6px;
    }

    /* Боковая панель — чуть светлее основного фона, отделена тонкой границей */
    [data-testid="stSidebar"] {
        background-color: #11151a;
        border-right: 1px solid #2d3748;
    }
    [data-testid="stSidebar"] * { color: #cbd5e0 !important; }

    /* Сообщения в чате: рамка, тень, плавный hover-эффект.
       transition задаёт анимацию изменения border-color и box-shadow за 0.2с. */
    .stChatMessage {
        border-radius: 10px;
        padding: 16px;
        margin: 12px 0;
        border: 1px solid #2d3748;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }
    .stChatMessage:hover {
        border-color: #dd6b20; 
        box-shadow: 0 2px 12px rgba(221, 107, 32, 0.12);
    }

    /* Сообщения пользователя: нейтральный тёмно-серый фон, серая левая полоса */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background-color: #1e2229;
        border-left: 4px solid #4a5568;
    }

    /* Сообщения ассистента: самый тёмный фон, акцентная оранжевая полоса.
       :has() — современный CSS-селектор, работает в Chrome 105+, Firefox 121+ */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
        background-color: #12161c;
        border-left: 4px solid #dd6b20; 
    }

    /* Кнопки: тёмный фон → оранжевый при hover, мягкое свечение */
    .stButton > button {
        border-radius: 8px;
        background-color: #2d3748;
        color: #e2e8f0;
        font-weight: 500;
        border: 1px solid #4a5568;
        padding: 10px 20px;
        transition: all 0.2s ease;
        font-size: 0.9rem;
        letter-spacing: 0.2px;
    }
    .stButton > button:hover {
        background-color: #dd6b20;
        color: #ffffff;
        border-color: #dd6b20;
        box-shadow: 0 0 12px rgba(221, 107, 32, 0.35);
    }
    /* translateY(1px) при клике создаёт эффект «нажатия» кнопки */
    .stButton > button:active {
        transform: translateY(1px);
        box-shadow: 0 0 8px rgba(221, 107, 32, 0.5);
    }

    /* Поле ввода чата: тёмный фон, оранжевое выделение при фокусе.
       box-shadow: 0 0 0 3px rgba(...) — «кольцо» вокруг поля (outline-эффект). */
    .stChatInput input {
        border-radius: 8px;
        border: 1px solid #4a5568;
        padding: 14px 20px;
        background-color: #11151a;
        color: #e2e8f0;
        font-size: 1rem;
        transition: border-color 0.2s, box-shadow 0.2s;
    }
    .stChatInput input:focus {
        border-color: #dd6b20;
        box-shadow: 0 0 0 3px rgba(221, 107, 32, 0.25);
        outline: none;
    }
    .stChatInput input::placeholder { color: #6b7280; }

    /* Разделитель: не просто линия, а градиент — «растворяется» по краям */
    hr {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
        margin: 25px 0;
    }

    /* Шапка сайдбара с аватаром ассистента */
    .assistant-header {
        background: linear-gradient(145deg, #1a202c, #11151a);
        border-radius: 10px;
        padding: 22px 20px;
        margin: 10px 0 20px 0;
        text-align: center;
        border: 1px solid #2d3748;
        box-shadow: inset 0 2px 4px rgba(255,255,255,0.02);
    }
    .assistant-header h3 { color: #e2e8f0; margin: 10px 0 0 0; font-weight: 600; font-size: 1.2rem; }

    /* Карточка приветствия: левая граница отделяет её от фона сайдбара */
    .greeting-card {
        background-color: rgba(26, 32, 44, 0.5);
        border-left: 3px solid #718096;
        border-radius: 0 8px 8px 0;
        padding: 16px;
        margin: 10px 0;
    }
    .greeting-card p { font-size: 0.95rem; line-height: 1.5; margin: 0; color: #cbd5e0; }

    /* Блок-подсказка над чатом: оранжевая рамка, акцент */
    .advice-box {
        background: rgba(221, 107, 32, 0.06);
        border: 1px solid rgba(221, 107, 32, 0.25);
        border-left: 4px solid #dd6b20;
        padding: 14px 18px;
        border-radius: 8px;
        margin-bottom: 28px;
        color: #cbd5e0;
        display: flex;
        align-items: center;
        gap: 12px;
    }

    /* Блок обратной связи: тёмный фон + декоративная оранжевая линия сверху.
       ::before — псевдоэлемент для линии без дополнительного HTML-тега. */
    .feedback-module {
        background: linear-gradient(180deg, #161b22 0%, #0b0f13 100%);
        border: 1px solid #2d3748;
        border-radius: 8px 8px 0 0;
        padding: 16px;
        position: relative;
        overflow: hidden;
    }
    .feedback-module::before {
        content: '';
        position: absolute;
        top: 0; left: 0;
        width: 100%; height: 2px;
        background: linear-gradient(90deg, transparent, #dd6b20, transparent);
    }
    .feedback-title-wrapper {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
    }
    .feedback-title-wrapper h3 { margin: 0; font-size: 1.1rem; display: flex; align-items: center; gap: 8px; color: #e2e8f0; }

    /* Индикатор «Online»: зелёная точка с CSS-анимацией пульсации.
       @keyframes pulse — анимация через масштабирование и box-shadow.
       Период: 2 секунды, бесконечный повтор. */
    .status-indicator {
        display: flex; align-items: center; gap: 6px;
        font-size: 0.75rem; color: #48bb78;
        font-family: 'JetBrains Mono', monospace;
        background: rgba(72, 187, 120, 0.1);
        padding: 2px 10px; border-radius: 12px;
        border: 1px solid rgba(72, 187, 120, 0.2);
    }
    .status-dot {
        width: 7px; height: 7px; background-color: #48bb78; border-radius: 50%;
        box-shadow: 0 0 6px #48bb78; animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%   { transform: scale(1);   box-shadow: 0 0 0 0   rgba(72, 187, 120, 0.7); }
        70%  { transform: scale(1.1); box-shadow: 0 0 0 5px rgba(72, 187, 120, 0);   }
        100% { transform: scale(1);   box-shadow: 0 0 0 0   rgba(72, 187, 120, 0);   }
    }
    .feedback-desc { color: #8b949e; font-size: 0.85rem; margin: 0; line-height: 1.4; }

    /* Скрываем стандартный хедер Streamlit — используем собственный заголовок */
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ФАЙЛАМИ СЕССИЙ
# ---------------------------------------------------------------------------
# Каждая сессия хранится в отдельном JSON-файле:
#   sessions/session_<uuid4>.json
#
# Пример содержимого файла:
#   {
#     "session_id":  "a1b2c3d4-...",   ← тот же UUID, что в cookie
#     "start_time":  1718000000.0,     ← Unix timestamp начала сессии
#     "messages":    [                 ← полная история диалога
#       {"role": "assistant", "content": "Привет! Я твой помощник..."},
#       {"role": "user",      "content": "Что такое допуск?"},
#       {"role": "assistant", "content": "Допуск — это разность..."}
#     ]
#   }
#
# Жизненный цикл файла:
#   Создан:   при первом открытии вкладки (_build_initial_messages + save_session)
#   Обновлён: после каждого сообщения (save_session в конце обработки)
#   Прочитан: при F5 / перезагрузке (load_session по cookie)
#   Удалён:   при нажатии «Очистить историю» (save_session с новой историей,
#             старый файл перезаписывается) или вручную через delete_session

def _session_file(sid: str) -> Path:
    """
    Формирует путь к JSON-файлу сессии по её UUID.

    Пример: _session_file("abc123") → Path("sessions/session_abc123.json")
    Функция не проверяет существование файла — это задача вызывающего кода.
    """
    return SESSIONS_DIR / f"session_{sid}.json"


def load_session(sid: str) -> dict | None:
    """
    Загружает данные сессии из JSON-файла на диске.

    Возвращает словарь с ключами session_id, start_time, messages
    или None в двух случаях:
      — файл не существует (сессия устарела, была удалена вручную)
      — файл повреждён / содержит невалидный JSON (маловероятно, но защищаемся)

    json.JSONDecodeError — исключение стандартной библиотеки при ошибке парсинга.
    OSError — исключение при проблемах чтения файла (нет прав, диск занят).
    """
    f = _session_file(sid)
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except (json.JSONDecodeError, OSError):
            # Повреждённый файл — лучше начать новую сессию, чем упасть с ошибкой
            return None
    return None


def save_session(sid: str, messages: list[dict]) -> None:
    """
    Сохраняет текущую историю диалога в JSON-файл сессии.

    Вызывается после каждого сообщения пользователя и ответа ассистента.
    Это гарантирует, что при случайном F5 пользователь не потеряет диалог.

    ensure_ascii=False — позволяет сохранять кириллицу «как есть» (UTF-8),
    без замены на. Файл остаётся читаемым в текстовом редакторе.

    st.session_state.get("start_time", time.time()) — если start_time не задан
    (теоретически возможно при нестандартных сценариях), используем текущее время.
    """
    data = {
        "session_id": sid,
        "start_time": st.session_state.get("start_time", time.time()),
        "messages": messages,
    }
    with open(_session_file(sid), "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)


def delete_session(sid: str) -> None:
    """
    Удаляет JSON-файл сессии с диска.

    Используется при необходимости полной очистки (например, при ручной
    очистке устаревших сессий). В текущей версии интерфейса напрямую не
    вызывается — очистка истории реализована через перезапись файла.
    f.unlink() — аналог os.remove(), но более идиоматичен для pathlib.
    """
    f = _session_file(sid)
    if f.exists():
        f.unlink()


def _build_initial_messages() -> list[dict]:
    """
    Формирует начальное состояние истории чата для новой сессии.

    Первое сообщение всегда от ассистента — это создаёт ощущение живого диалога
    и сразу показывает пользователю, что система готова к работе.
    Список с одним элементом: расширяется по мере общения в чате.
    """
    return [
        {
            "role": "assistant",
            "content": (
                "Привет! Я твой помощник по технологии машиностроения. "
                "Задавай вопрос — я найду ответ в лекциях."
            ),
        }
    ]


# ---------------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ СЕССИИ ПРИ ЗАГРУЗКЕ СТРАНИЦЫ
# ---------------------------------------------------------------------------
# Этот блок выполняется ОДИН РАЗ за жизнь вкладки благодаря проверке
# "session_initialized" not in st.session_state.
#
# При каждом rerun (ввод текста, нажатие кнопки) Streamlit перезапускает
# скрипт сверху вниз. Без этой проверки сессия пересоздавалась бы при
# каждом действии пользователя.
#
# Логика инициализации:
#   1. Пытаемся прочитать session_id из cookie браузера.
#      st.context.cookies — API, доступный начиная с Streamlit 1.30.
#      AttributeError — страховка для старых версий.
#   2. Если cookie найдена → ищем файл сессии на диске.
#      Нашли → восстанавливаем историю (пользователь нажал F5).
#      Не нашли → cookie устарела/файл удалён → удаляем cookie и создаём новую сессию.
#   3. Если cookie не найдена → новая вкладка или закрытый браузер →
#      генерируем UUID4, создаём файл, устанавливаем cookie.

if "session_initialized" not in st.session_state:
    # Попытка получить UUID из cookie браузера
    sid_from_cookie: str | None = None
    try:
        sid_from_cookie = st.context.cookies.get("session_id")
    except AttributeError:
        # st.context.cookies недоступен (Streamlit < 1.30) — продолжаем без него
        sid_from_cookie = None

    if sid_from_cookie:
        # Cookie есть — проверяем наличие файла сессии
        session_data = load_session(sid_from_cookie)
        if session_data:
            # Файл найден — восстанавливаем состояние (сценарий F5)
            st.session_state.sid = sid_from_cookie
            st.session_state.messages = session_data["messages"]
            st.session_state.start_time = session_data["start_time"]
        else:
            # Cookie есть, файл не найден (устарел / удалён вручную) → сброс
            delete_cookie("session_id")
            sid_from_cookie = None  # переходим к созданию новой сессии ниже

    if not sid_from_cookie:
        # Создаём совершенно новую сессию с уникальным UUID4
        # uuid.uuid4() генерирует случайный UUID: вероятность коллизии ≈ 0
        new_sid = str(uuid.uuid4())
        initial_messages = _build_initial_messages()
        # Порядок важен: сначала сохраняем файл, потом ставим cookie.
        # Если браузер заблокирует cookie — файл всё равно останется на диске.
        save_session(new_sid, initial_messages)
        set_session_cookie("session_id", new_sid)
        st.session_state.sid = new_sid
        st.session_state.messages = initial_messages
        st.session_state.start_time = time.time()

    # Флаг: блок инициализации выполнен, при следующих rerun пропускаем его
    st.session_state.session_initialized = True

# Страховка на случай нестандартного сброса session_state:
# если messages каким-то образом не проинициализированы — создаём заново
if "messages" not in st.session_state:
    st.session_state.messages = _build_initial_messages()


# ---------------------------------------------------------------------------
# ОСНОВНАЯ ОБЛАСТЬ: ЗАГОЛОВОК И ПОДСКАЗКА
# ---------------------------------------------------------------------------
st.title("⚙️ Ассистент по Технологии машиностроения")

# Информационный блок с советом — выделен оранжевой рамкой для заметности.
# unsafe_allow_html=True необходим, так как блок написан в виде HTML-div.
# Без этого флага Streamlit выведет HTML как обычный текст.
st.markdown("""
<div class="advice-box">
    <span style="font-size: 1.5rem;">✨</span>
    <div>
        <strong>Совет:</strong> Задайте вопрос так, как спросили бы преподавателя. Я найду ответ в проверенных лекциях и глоссарии.
    </div>
</div>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# БОКОВАЯ ПАНЕЛЬ (SIDEBAR)
# ---------------------------------------------------------------------------
# with st.sidebar — контекстный менеджер: всё внутри него рендерится
# в боковой панели, а не в основной области контента.
with st.sidebar:
    # Шапка с emoji-аватаром ассистента и его названием
    # filter: drop-shadow() — CSS-эффект свечения вокруг emoji
    st.markdown("""
    <div class="assistant-header">
        <span style="font-size: 52px; filter: drop-shadow(0 0 12px rgba(221,107,32,0.5));">🤖</span>
        <h3>Ваш ИИ‑помощник</h3>
    </div>
    """, unsafe_allow_html=True)

    # Карточка с кратким описанием назначения ассистента
    st.markdown("""
    <div class="greeting-card">
        <p>
            ⚙️ Привет! Я твой напарник по специальности «Технология машиностроения». 
            Отвечаю быстро, ссылаюсь на материалы и не придумываю лишнего.
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Кнопка очистки истории диалога.
    # При нажатии: перезаписываем messages одним приветственным сообщением,
    # сохраняем в файл сессии (перезаписываем старую историю), вызываем rerun.
    # st.rerun() — перезапускает скрипт с начала, обновляя интерфейс.
    # use_container_width=True — кнопка растягивается на всю ширину сайдбара.
    if st.button("🧹 Очистить историю", use_container_width=True):
        st.session_state.messages = [
            {"role": "assistant", "content": "История очищена. Задайте новый вопрос."}
        ]
        if "sid" in st.session_state:
            save_session(st.session_state.sid, st.session_state.messages)
        st.rerun()

    st.divider()  # горизонтальный разделитель (из CSS: градиентная линия)

    # Список возможностей ассистента — краткая справка для пользователя
    st.subheader("🚀 Что я умею")
    st.markdown("""
    - 📖 Объяснять термины из глоссария  
    - 🧪 Разбирать технологические процессы  
    - 📚 Опираться только на твои лекции  
    - ⚡ Давать мгновенные ответы с источниками  
    """)
    st.divider()

    # Блок обратной связи через Яндекс Формы.
    # Заголовок с HTML-разметкой (статус-индикатор) рендерится через st.markdown,
    # сама форма — через components.html() (iframe не поддерживается в st.markdown).
    st.markdown("""
    <div class="feedback-module">
        <div class="feedback-title-wrapper">
            <h3>📝 Обратная связь</h3>
            <div class="status-indicator">
                <div class="status-dot"></div> Online
            </div>
        </div>
        <p class="feedback-desc">Помоги мне стать лучше! Оставь пожелание или сообщи об ошибке в форме ниже.</p>
    </div>
    """, unsafe_allow_html=True)

    # iframe с формой Яндекс Форм.
    # height=630 — высота iframe в пикселях (подобрана под размер формы).
    # scrolling="yes" — позволяет прокручивать форму если она не умещается.
    # Параметр ?iframe=1 в URL сообщает Яндекс Формам, что форма встроена
    # в iframe — это убирает лишние отступы и ненужные элементы страницы.
    # &theme=dark — тёмная тема формы (соответствует общему дизайну интерфейса).
    components.html(
        """
        <iframe src="https://forms.yandex.ru/u/69a964ed6d2d73372c353b06?iframe=1&theme=dark"
                width="100%"
                height="630"
                scrolling="yes"
                style="background-color: #0b0f13; border-radius: 0 0 8px 8px; border: 1px solid #2d3748; border-top: none;">
        </iframe>
        """,
        height=630,
    )


# ---------------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ АССИСТЕНТА (КЕШИРУЕТСЯ МЕЖДУ RERUN)
# ---------------------------------------------------------------------------
# @st.cache_resource — декоратор Streamlit для кеширования «тяжёлых» объектов.
# Без него MachineryAssistant() создавался бы заново при каждом rerun:
#   — повторная загрузка модели эмбеддингов (~3-5 сек)
#   — повторное подключение к ChromaDB
#   — повторная инициализация GigaChat-клиента
# С декоратором объект создаётся один раз и живёт всё время работы сервера,
# разделяясь между всеми пользователями (потокобезопасно для read-only операций).
@st.cache_resource
def load_assistant() -> MachineryAssistant:
    """Создаёт и кеширует единственный экземпляр RAG-ассистента."""
    return MachineryAssistant()


# st.spinner — контекстный менеджер, отображающий анимированный индикатор загрузки.
# Spinner виден только при первом запуске (пока @cache_resource создаёт объект).
# При повторных rerun load_assistant() возвращает кешированный объект мгновенно,
# и spinner исчезает раньше, чем успевает отрисоваться.
with st.spinner("⚙️ Загружаем базу знаний и подключаемся к GigaChat..."):
    assistant = load_assistant()


# ---------------------------------------------------------------------------
# ОТОБРАЖЕНИЕ ИСТОРИИ ЧАТА
# ---------------------------------------------------------------------------
# Проходим по всем сообщениям в st.session_state.messages и рендерим каждое.
# st.chat_message(role) — создаёт «пузырь» сообщения с аватаром.
#   role="user"      → аватар пользователя (человечек)
#   role="assistant" → аватар ассистента (робот)
#
# Перед рендерингом каждое сообщение проходит через XSS-фильтр.
# Это важно для сообщений из истории (загруженных из файла) —
# на случай если в файле оказался вредоносный контент.
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        safe_content = sanitize_markdown_links(message["content"])
        st.markdown(safe_content)


# ---------------------------------------------------------------------------
# ОБРАБОТКА НОВОГО СООБЩЕНИЯ ОТ ПОЛЬЗОВАТЕЛЯ
# ---------------------------------------------------------------------------
# st.chat_input() — поле ввода в нижней части экрана (стиль ChatGPT).
# Возвращает строку если пользователь отправил сообщение, иначе None.
# Оператор := (walrus) присваивает и проверяет в одном выражении.
#
# Полный сценарий обработки одного сообщения:
#   1. Получаем текст вопроса от пользователя.
#   2. Фильтруем XSS в тексте вопроса.
#   3. Добавляем вопрос в session_state и отображаем в чате.
#   4. Открываем «пузырь» ассистента и показываем spinner «Думаю...».
#   5. Отправляем вопрос в RAG-ядро (assistant.ask()).
#   6. Форматируем ответ: добавляем список источников если они есть.
#   7. Фильтруем XSS в ответе ассистента.
#   8. Рендерим ответ через st.markdown().
#   9. Добавляем ответ в session_state.
#  10. Сохраняем обновлённую историю в JSON-файл сессии.
if prompt := st.chat_input("Введите ваш вопрос..."):

    # Шаг 2-3: XSS-фильтрация вопроса + добавление в историю + отображение
    safe_prompt = sanitize_markdown_links(prompt)
    st.session_state.messages.append({"role": "user", "content": safe_prompt})
    with st.chat_message("user"):
        st.markdown(safe_prompt)

    # Шаг 4-9: формирование ответа ассистента
    with st.chat_message("assistant"):
        with st.spinner("Думаю..."):
            # assistant.ask() — единственный вызов к RAG-ядру.
            # Внутри: ретривер ChromaDB → контекст → GigaChat → ответ.
            # Возвращает dict: {"answer": str, "sources": list[str]}
            response = assistant.ask(prompt)
            answer = response["answer"]

            # Если ретривер нашёл источники — добавляем их список к ответу.
            # response.get("sources") безопаснее response["sources"] —
            # не упадёт если ключ отсутствует (при ошибках ретривера).
            if response.get("sources"):
                sources_text = "\n\n📚 **Источники:**\n"
                for src in response["sources"]:
                    sources_text += f"- {src}\n"
                answer += sources_text

            # XSS-фильтрация ответа ассистента перед рендерингом
            safe_answer = sanitize_markdown_links(answer)
            st.markdown(safe_answer)

            # Добавляем отфильтрованный ответ в историю
            st.session_state.messages.append({"role": "assistant", "content": safe_answer})

    # Шаг 10: персистируем историю — после каждого обмена данные на диске актуальны.
    # Если пользователь нажмёт F5 сейчас — увидит полную историю включая этот ответ.
    if "sid" in st.session_state:
        save_session(st.session_state.sid, st.session_state.messages)
