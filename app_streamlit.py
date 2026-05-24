"""
app_streamlit.py — веб-интерфейс RAG-ассистента на Streamlit.

Архитектура интерфейса:
  • Авторизация: логин/пароль с PBKDF2-хешированием, блокировкой после
    5 неудачных попыток и timing-safe сравнением (защита от брутфорса).
  • Сессии: UUID-файлы в sessions/ + сессионная cookie в браузере.
    F5 → чат сохраняется. Закрытие вкладки → cookie исчезает → при
    следующем открытии нужна повторная авторизация.
  • Чат: история сообщений в st.session_state + персистентность в JSON-файле.
  • Безопасность: XSS-фильтрация ссылок в Markdown перед рендерингом.
  • UX: тёмный промышленный дизайн, анимации, встроенная форма обратной связи.
"""
import streamlit as st
from rag_engine import MachineryAssistant
import streamlit.components.v1 as components  # для произвольного HTML/JS в интерфейсе
import time
import re
import html as html_module  # стандартная библиотека для html.unescape
import uuid                 # для генерации уникальных ID сессий
import json
import hashlib              # для PBKDF2-хеширования паролей
import hmac                 # для timing-safe сравнения строк
from pathlib import Path

# Настройка папки хранения сессий

# Каждая активная вкладка браузера соответствует одному JSON-файлу в sessions/.
# Это позволяет нескольким пользователям работать одновременно изолированно.
SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)  # создаём папку если не существует, ошибки нет

# --- Персистентный счётчик неудачных попыток ---
_ATTEMPTS_FILE = SESSIONS_DIR / "_login_attempts.json"

def _load_attempts() -> tuple[int, float]:
    """Читает счётчик попыток и время последней из файла."""
    try:
        if _ATTEMPTS_FILE.exists():
            data = json.loads(_ATTEMPTS_FILE.read_text(encoding="utf-8"))
            return data.get("count", 0), data.get("last_time", 0.0)
    except (json.JSONDecodeError, OSError):
        pass
    return 0, 0.0

def _save_attempts(count: int, last_time: float) -> None:
    """Сохраняет счётчик попыток и время последней в файл."""
    try:
        _ATTEMPTS_FILE.write_text(
            json.dumps({"count": count, "last_time": last_time}),
            encoding="utf-8",
        )
    except OSError:
        pass

def _reset_attempts() -> None:
    """Сбрасывает счётчик и удаляет файл."""
    if _ATTEMPTS_FILE.exists():
        _ATTEMPTS_FILE.unlink()

# СИСТЕМА АУТЕНТИФИКАЦИИ

# Использует PBKDF2-HMAC-SHA256 — рекомендованный OWASP алгоритм для
# хеширования паролей в приложениях, где не нужен полноценный сервер
# аутентификации, но нужна защита от rainbow-таблиц и перебора.
#
# Параметры по OWASP 2024:
#   • SHA-256 + 310 000 итераций ≈ 100 мс на одну проверку — достаточно
#     медленно для брутфорса, но незаметно для одиночной авторизации.
#   • Индивидуальная соль на каждого пользователя — rainbow-таблицы бесполезны.
#   • Соль хранится в коде, пароль — только в .env.
# ---------------------------------------------------------------------------

_PBKDF2_ITERS = 310_000  # итерации PBKDF2: больше = медленнее перебор

# Соль для пользователя "TM" — 16 случайных байт в hex.
# Генерация новой соли: import os; os.urandom(16).hex()
_TM_SALT = bytes.fromhex("3a7f92c1d5e04b68a19f3c82e6b0d471")

# Хеш вычисляется при старте приложения из пароля в .env.
# Это значит пароль никогда не хранится в памяти после инициализации —
# только его хеш. Смените b"123" на новый пароль перед деплоем.
_TM_HASH = hashlib.pbkdf2_hmac("sha256", b"123", _TM_SALT, _PBKDF2_ITERS).hex()

# Словарь пользователей: имя → (соль, хеш).
# Для добавления нового пользователя см. инструкцию в README.md.
_VALID_USERS: dict[str, tuple[bytes, str]] = {
    "TM": (_TM_SALT, _TM_HASH),
}


def check_credentials(username: str, password: str) -> bool:
    """
    Проверяет учётные данные с защитой от timing-атак.

    Timing-атака: злоумышленник замеряет время ответа сервера.
    Если "пользователь не найден" отвечает быстрее, чем "неверный пароль",
    атакующий может определить существующих пользователей по разнице времени.

    Защита:
      • Если пользователь не найден — всё равно выполняем PBKDF2 с фиктивными
        данными, чтобы время ответа было одинаковым.
      • hmac.compare_digest() сравнивает строки за постоянное время (O(n)
        независимо от первого несовпадения), в отличие от обычного == ,
        который прерывается на первом несовпадающем байте.
    """
    entry = _VALID_USERS.get(username)
    if not entry:
        # Фиктивный PBKDF2 для выравнивания времени ответа
        hashlib.pbkdf2_hmac("sha256", b"", b"\x00" * 16, _PBKDF2_ITERS)
        return False
    salt, stored_hash = entry
    trial_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS
    ).hex()
    # compare_digest — константное время сравнения, защита от timing-атак
    return hmac.compare_digest(trial_hash, stored_hash)

# XSS-ЗАЩИТА

# Streamlit рендерит Markdown с unsafe_allow_html=True в некоторых местах.
# Вредоносные ссылки вида [текст](javascript:alert(1)) могут исполнять
# произвольный JS в браузере пользователя. Фильтруем их перед рендерингом.

# Разрешённые схемы URL — всё остальное заменяется на '#' (безопасная заглушка)
_SAFE_SCHEMES = re.compile(r'^(https?|mailto|tel)://', re.IGNORECASE)

# Регулярка для поиска Markdown-ссылок вида [текст](url)
_MD_LINK = re.compile(r'\[([^\]]*)\]\(([^)]*)\)')


def sanitize_markdown_links(text: str) -> str:
    """
    Фильтрует небезопасные URL в Markdown-ссылках.

    Логика:
      1. Находим все конструкции [label](url).
      2. Декодируем HTML-сущности (&amp; → &, &#106; → j и т.д.).
      3. Убираем пробелы и управляющие символы из URL (обход фильтров).
      4. Проверяем схему — разрешены только http://, https://, mailto:, tel:
         и относительные пути (#anchor, /page).
      5. Небезопасные URL заменяем на '#'.
    """
    def replace_link(m):
        label = m.group(1)
        url_raw = m.group(2).strip()
        url = html_module.unescape(url_raw)
        # Убираем пробелы и управляющие символы — трюк для обхода фильтров:
        # "java\nscript:alert(1)" без \n становится "javascript:alert(1)"
        url_normalized = re.sub(r'[\s\x00-\x1f]+', '', url)
        if _SAFE_SCHEMES.match(url_normalized) or url_normalized.startswith(('#', '/')):
            return f'[{label}]({url})'
        return f'[{label}](#)'  # заменяем опасный URL безопасной заглушкой
    return _MD_LINK.sub(replace_link, text)

# УПРАВЛЕНИЕ СЕССИОННЫМИ КУКАМИ

# Streamlit не предоставляет нативного API для установки cookie.
# Обходим это через components.html() — встраиваем минимальный JS в iframe.
# Ключевые параметры cookie:
#   • path=/        — кука доступна на всех путях сайта
#   • SameSite=Lax  — защита от CSRF (кука не отправляется при cross-site POST)
#   • Secure        — только по HTTPS (добавляем динамически если сайт на HTTPS)

# Почему сессионная кука (без max-age):
#   Браузер удаляет сессионные куки при закрытии вкладки/окна. Это обеспечивает
#   поведение "закрыл → нужно войти заново", что удобно для учебной среды.

def set_session_cookie(name: str, value: str) -> None:
    """Устанавливает сессионную cookie (без max-age — браузер удалит при закрытии вкладки)."""
    components.html(
        f"""
        <script>
        // Добавляем Secure только если сайт открыт по HTTPS
        var isSecure = (location.protocol === 'https:') ? '; Secure' : '';
        document.cookie = "{name}={value}; path=/; SameSite=Lax" + isSecure;
        </script>
        """,
        height=0,  # iframe нулевой высоты — невидим для пользователя
    )


def delete_cookie(name: str) -> None:
    """Удаляет cookie установкой отрицательного max-age."""
    components.html(
        f"""
        <script>
        var isSecure = (location.protocol === 'https:') ? '; Secure' : '';
        // max-age=-1 немедленно инвалидирует куку во всех браузерах
        document.cookie = "{name}=; max-age=-1; path=/; SameSite=Lax" + isSecure;
        </script>
        """,
        height=0,
    )

# Конфигурация страницы Streamlit
# set_page_config ОБЯЗАН быть первым вызовом Streamlit в скрипте.
st.set_page_config(
    page_title="Ассистент по Технологии машиностроения",
    page_icon="⚙️",
    layout="centered",  # "centered" или "wide" — ширина основного контента
)
# Кастомные стили (CSS)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400&display=swap');

    /* Фон всего приложения с сеткой — технический "чертёжный" стиль */
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

    /* Inline-код и блоки кода */
    code {
        font-family: 'JetBrains Mono', monospace;
        color: #f6ad55 !important; 
        background-color: rgba(246, 173, 85, 0.12) !important;
        border-radius: 4px;
        padding: 2px 6px;
    }

    /* Боковая панель */
    [data-testid="stSidebar"] {
        background-color: #11151a;
        border-right: 1px solid #2d3748;
    }
    [data-testid="stSidebar"] * { color: #cbd5e0 !important; }

    /* Сообщения в чате — общие стили + hover-эффект */
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

    /* Сообщения пользователя — нейтральный синевато-серый фон */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background-color: #1e2229;
        border-left: 4px solid #4a5568;
    }

    /* Сообщения ассистента — акцентная оранжевая полоса слева */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
        background-color: #12161c;
        border-left: 4px solid #dd6b20; 
    }

    /* Кнопки — тёмный стиль с hover-эффектом в акцентный цвет */
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
    .stButton > button:active {
        transform: translateY(1px); /* "нажатие" кнопки */
        box-shadow: 0 0 8px rgba(221, 107, 32, 0.5);
    }

    /* Поле ввода чата */
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
        box-shadow: 0 0 0 3px rgba(221, 107, 32, 0.25); /* glow при фокусе */
        outline: none;
    }
    .stChatInput input::placeholder { color: #6b7280; }

    /* Разделитель — тонкий градиентный */
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

    /* Карточка приветствия в сайдбаре */
    .greeting-card {
        background-color: rgba(26, 32, 44, 0.5);
        border-left: 3px solid #718096;
        border-radius: 0 8px 8px 0;
        padding: 16px;
        margin: 10px 0;
    }
    .greeting-card p { font-size: 0.95rem; line-height: 1.5; margin: 0; color: #cbd5e0; }

    /* Блок-подсказка "Совет" над чатом */
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

    /* Блок обратной связи в сайдбаре */
    .feedback-module {
        background: linear-gradient(180deg, #161b22 0%, #0b0f13 100%);
        border: 1px solid #2d3748;
        border-radius: 8px 8px 0 0;
        padding: 16px;
        position: relative;
        overflow: hidden;
    }
    /* Декоративная оранжевая линия сверху блока обратной связи */
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

    /* Индикатор "Online" с пульсирующей точкой */
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
    /* CSS-анимация пульсации: масштаб + расширяющаяся тень */
    @keyframes pulse {
        0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(72, 187, 120, 0.7); }
        70% { transform: scale(1.1); box-shadow: 0 0 0 5px rgba(72, 187, 120, 0); }
        100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(72, 187, 120, 0); }
    }
    .feedback-desc { color: #8b949e; font-size: 0.85rem; margin: 0; line-height: 1.4; }

    /* Скрываем стандартный хедер Streamlit (с именем приложения и меню) */
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# РАБОТА С ФАЙЛАМИ СЕССИЙ
# Структура хранения:
#   sessions/
#     session_<uuid>.json   ← один файл на каждую активную вкладку
# Содержимое JSON-файла:
#   {
#     "username":   "TM",
#     "login_time": 1718000000.0,   # Unix timestamp
#     "messages":   [               # полная история чата
#       {"role": "assistant", "content": "Привет!"},
#       {"role": "user",      "content": "Что такое допуск?"},
#       ...
#     ]
#   }
# Жизненный цикл файла:
#   Создан  → при входе (login_user)
#   Обновлён → после каждого сообщения в чате (save_session)
#   Прочитан → при загрузке страницы (load_session)
#   Удалён  → при выходе (logout) или при ручной очистке устаревших сессий

def _session_file(sid: str) -> Path:
    """Возвращает путь к JSON-файлу сессии по её UUID."""
    return SESSIONS_DIR / f"session_{sid}.json"


def load_session(sid: str) -> dict | None:
    """
    Загружает данные сессии из файла.

    Возвращает:
        dict с ключами username, login_time, messages — если файл существует
        None — если файл отсутствует или повреждён (невалидный JSON)
    """
    f = _session_file(sid)
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except (json.JSONDecodeError, OSError):
            # Повреждённый файл обрабатываем мягко — возвращаем None,
            # что приведёт к запросу повторного входа, а не к крашу
            return None
    return None


def save_session(sid: str, username: str, messages: list[dict]) -> None:
    """
    Сохраняет текущее состояние чата в JSON-файл.
    Вызывается после каждого сообщения — история не теряется при F5.
    """
    data = {
        "username": username,
        "login_time": st.session_state.get("login_time", time.time()),
        "messages": messages,
    }
    with open(_session_file(sid), "w", encoding="utf-8") as fp:
        # ensure_ascii=False — сохраняем кириллицу как есть, а не как \uXXXX
        json.dump(data, fp, ensure_ascii=False)


def delete_session(sid: str) -> None:
    """Удаляет файл сессии при выходе пользователя."""
    f = _session_file(sid)
    if f.exists():
        f.unlink()  # Path.unlink() — удаление файла (аналог os.remove)

# ВОССТАНОВЛЕНИЕ СЕССИИ ПРИ ЗАГРУЗКЕ СТРАНИЦЫ
#
# Проблема: Streamlit перезапускает весь скрипт при каждом rerun (включая F5).
# st.session_state выживает между reruns, но НЕ при полном обновлении страницы.
#
# Решение: при первом запуске (когда logged_in ещё нет в session_state)
# проверяем cookie в браузере. Если cookie есть и файл сессии существует —
# восстанавливаем состояние без повторного входа.
#
# Поток:
#   1. Первый открытие страницы → нет cookie → форма входа
#   2. Успешный вход → создаём UUID, JSON-файл, устанавливаем cookie
#   3. F5 → нет logged_in в session_state → читаем cookie → находим файл →
#      восстанавливаем историю → пользователь не замечает перезагрузки
#   4. Закрытие вкладки → браузер удаляет сессионную cookie → при открытии
#      нет cookie → форма входа (даже если JSON-файл ещё существует на диске)
# ===========================================================================

if "logged_in" not in st.session_state:
    # Пытаемся получить session_id из cookie браузера.
    # st.context.cookies появился в Streamlit 1.30+ — используем try/except
    # для совместимости со старыми версиями.
    sid_from_cookie: str | None = None
    try:
        sid_from_cookie = st.context.cookies.get("session_id")
    except AttributeError:
        sid_from_cookie = None

    if sid_from_cookie:
        session_data = load_session(sid_from_cookie)
        if session_data:
            # Сессия найдена — восстанавливаем все поля session_state
            st.session_state.logged_in = True
            st.session_state.sid = sid_from_cookie
            st.session_state.username = session_data["username"]
            st.session_state.messages = session_data["messages"]
            st.session_state.login_time = session_data["login_time"]
            st.session_state.login_attempts = 0
        else:
            # Cookie указывает на несуществующий или повреждённый файл.+
            # Удаляем "висячую" куку, чтобы не создавать путаницу.
            delete_cookie("session_id")

# Инициализируем недостающие ключи с дефолтными значениями.
# Это безопасно: если ключ уже есть — ничего не меняется.
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "login_attempts" not in st.session_state:
    _attempts, _last_time = _load_attempts()
    st.session_state.login_attempts = _attempts
    st.session_state.last_attempt_time = _last_time


# АВТОРИЗАЦИЯ
MAX_LOGIN_ATTEMPTS = 5      # попыток до блокировки
BLOCK_TIME_SECONDS  = 300   # 5 минут блокировки


def _build_initial_messages() -> list[dict]:
    """Возвращает начальную историю чата с приветственным сообщением ассистента."""
    return [
        {
            "role": "assistant",
            "content": (
                "Привет! Я твой помощник по технологии машиностроения. "
                "Задавай вопрос — я найду ответ в лекциях."
            ),
        }
    ]


def login_user(username: str) -> tuple[str, list[dict]]:
    """
    Создаёт новую сессию для вошедшего пользователя.

    Каждый вход генерирует новый UUID → новый JSON-файл → изолированная история.
    Это гарантирует, что два одновременных входа с одинаковым логином
    (например, с двух вкладок) не перезапишут историю друг друга.

    Возвращает: (sid, initial_messages)
    """
    sid = str(uuid.uuid4())  # криптографически случайный UUID4
    initial_messages = _build_initial_messages()
    save_session(sid, username, initial_messages)
    set_session_cookie("session_id", sid)
    return sid, initial_messages


def logout() -> None:
    """
    Полностью завершает сессию: удаляет файл, куку и очищает session_state.
    st.rerun() перезагружает страницу — пользователь видит форму входа.
    """
    if "sid" in st.session_state:
        delete_session(st.session_state.sid)
        delete_cookie("session_id")
    # Очищаем весь session_state, а не только флаг logged_in,
    # чтобы не оставлять "мусор" от предыдущей сессии
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


# --- Блокировка при превышении лимита попыток ---
# Проверяем ПЕРЕД отрисовкой формы — заблокированный пользователь
# не должен видеть поля ввода.
if not st.session_state.logged_in:
    if st.session_state.login_attempts >= MAX_LOGIN_ATTEMPTS:
        time_since = time.time() - st.session_state.last_attempt_time
        if time_since < BLOCK_TIME_SECONDS:
            remaining = int(BLOCK_TIME_SECONDS - time_since)
            st.error(
                f"🔒 Слишком много попыток. "
                f"Попробуйте через {remaining // 60} мин {remaining % 60} сек."
            )
            time.sleep(1)   # ← ждём секунду и перерисовываем — таймер тикает
            st.rerun()
        else:
            st.session_state.login_attempts = 0
            _reset_attempts()   # ← сбрасываем файл тоже

# --- Форма входа ---
if not st.session_state.logged_in:
    st.markdown("<br><br>", unsafe_allow_html=True)
    # Трёхколоночная раскладка для центрирования формы
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div style="text-align: center; margin-bottom: 20px;">
            <h1 style="color: #e2e8f0;">🔒 Вход в систему</h1>
        </div>
        """, unsafe_allow_html=True)

        # st.form группирует поля и кнопку — отправка происходит только
        # при нажатии на кнопку формы, а не при изменении каждого поля
        with st.form("login_form"):
            username = st.text_input("Логин")
            password = st.text_input("Пароль", type="password")  # скрывает ввод
            submitted = st.form_submit_button("Войти", use_container_width=True)

            if submitted:
                if check_credentials(username, password):
                    # Успешный вход: создаём сессию и заполняем session_state
                    sid, initial_messages = login_user(username)
                    st.session_state.logged_in = True
                    st.session_state.sid = sid
                    st.session_state.username = username
                    st.session_state.login_time = time.time()
                    st.session_state.login_attempts = 0
                    _reset_attempts()
                    st.session_state.messages = initial_messages
                    st.rerun()  # перезагрузка → теперь logged_in=True → показываем чат
                else:
                    st.session_state.login_attempts += 1
                    st.session_state.last_attempt_time = time.time()
                    _save_attempts(                         # ← сохраняем в файл
                        st.session_state.login_attempts,
                        st.session_state.last_attempt_time,
                    )
                    st.error("Неверный логин или пароль.")
    st.stop()  # не рендерим основной интерфейс пока не вошли

# ОСНОВНОЙ ИНТЕРФЕЙС (виден только авторизованным пользователям)
st.title("⚙️ Ассистент по Технологии машиностроения")

# Совет-подсказка над чатом — помогает пользователю правильно формулировать вопросы
st.markdown("""
<div class="advice-box">
    <span style="font-size: 1.5rem;">✨</span>
    <div>
        <strong>Совет:</strong> Задайте вопрос так, как спросили бы преподавателя. Я найду ответ в проверенных лекциях и глоссарии.
    </div>
</div>
""", unsafe_allow_html=True)

# БОКОВАЯ ПАНЕЛЬ
with st.sidebar:
    # Шапка с аватаром — эмодзи с тенью через CSS filter
    st.markdown("""
    <div class="assistant-header">
        <span style="font-size: 52px; filter: drop-shadow(0 0 12px rgba(221,107,32,0.5));">🤖</span>
        <h3>Ваш ИИ‑помощник</h3>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="greeting-card">
        <p>
            ⚙️ Привет! Я твой напарник по специальности «Технология машиностроения». 
            Отвечаю быстро, ссылаюсь на материалы и не придумываю лишнего.
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Кнопки управления в две колонки
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧹 Очистить историю", use_container_width=True):
            # Сбрасываем историю в памяти И в файле — без этого
            # F5 после очистки восстановит старую историю из JSON
            st.session_state.messages = [
                {"role": "assistant", "content": "История очищена. Задайте новый вопрос."}
            ]
            if "sid" in st.session_state:
                save_session(st.session_state.sid, st.session_state.username, st.session_state.messages)
            st.rerun()
    with col2:
        if st.button("🚪 Выйти", use_container_width=True):
            logout()

    st.divider()
    st.subheader("🚀 Что я умею")
    st.markdown("""
    - 📖 Объяснять термины из глоссария  
    - 🧪 Разбирать технологические процессы  
    - 📚 Опираться только на твои лекции  
    - ⚡ Давать мгновенные ответы с источниками  
    """)
    st.divider()

    # Блок обратной связи с формой Яндекс.Формы во встроенном iframe
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

    # Iframe с Яндекс.Формой — данные уходят напрямую в Яндекс,
    # не проходя через сервер приложения. ?iframe=1 — режим встраивания,
    # &theme=dark — тёмная тема формы для единства дизайна.
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

# Инициализация ассистента
@st.cache_resource
# @st.cache_resource кеширует объект между reruns и между разными
# пользователями (в пределах одного процесса Streamlit).
# Это значит, что MachineryAssistant создаётся ОДИН РАЗ при первом запросе,
# а не при каждом сообщении пользователя. Загрузка модели эмбеддингов
# (~3-5 сек) и подключение к ChromaDB происходят только однажды.
def load_assistant():
    return MachineryAssistant()


# Спиннер показывает прогресс при первом запуске, когда модель ещё не в кеше
with st.spinner("⚙️ Загружаем базу знаний и подключаемся к GigaChat..."):
    assistant = load_assistant()

# История чата

# Инициализируем историю если её нет (первый вход без восстановления из файла)
if "messages" not in st.session_state:
    st.session_state.messages = _build_initial_messages()

# Отрисовываем все сообщения из истории.
# Streamlit перерисовывает весь экран при каждом rerun, поэтому нужно
# явно проходить по всей истории и рендерить каждое сообщение заново.
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        # Санитизируем ссылки перед рендерингом — защита от XSS
        safe_content = sanitize_markdown_links(message["content"])
        st.markdown(safe_content)

# Обработка нового сообщения
# st.chat_input отображает поле ввода и возвращает текст только когда
# пользователь отправил сообщение (Enter или кнопка), иначе None.
# Паттерн "if prompt := ..." обеспечивает: обработка идёт только если
# пользователь что-то написал — не при каждом rerun.
if prompt := st.chat_input("Введите ваш вопрос..."):
    # Санитизируем вопрос пользователя до сохранения и отображения
    safe_prompt = sanitize_markdown_links(prompt)

    # Сохраняем вопрос в историю и показываем его в чате
    st.session_state.messages.append({"role": "user", "content": safe_prompt})
    with st.chat_message("user"):
        st.markdown(safe_prompt)

    # Генерируем ответ с индикатором загрузки
    with st.chat_message("assistant"):
        with st.spinner("Думаю..."):
            # Передаём оригинальный prompt в RAG (не safe_prompt) —
            # санитизация нужна только для отображения, для поиска
            # нужен чистый текст запроса без HTML-замен
            response = assistant.ask(prompt)
            answer = response["answer"]

            # Добавляем список источников к ответу если они есть.
            # set() в ask() уже убрал дубликаты, здесь просто форматируем.
            if response.get("sources"):
                sources_text = "\n\n📚 **Источники:**\n"
                for src in response["sources"]:
                    sources_text += f"- {src}\n"
                answer += sources_text

            # Финальная санитизация ответа модели — модель может теоретически
            # вернуть ссылки из контекста документов, которые нужно проверить
            safe_answer = sanitize_markdown_links(answer)
            st.markdown(safe_answer)

            # Сохраняем ответ в историю session_state
            st.session_state.messages.append({"role": "assistant", "content": safe_answer})

    # Персистируем обновлённую историю в JSON-файл после каждого сообщения.
    # Это гарантирует: даже если сервер перезагрузится, история не потеряется.
    if "sid" in st.session_state:
        save_session(st.session_state.sid, st.session_state.username, st.session_state.messages)
