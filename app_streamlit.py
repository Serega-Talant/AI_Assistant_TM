"""
Веб-интерфейс для студентов с авторизацией, обратной связью и современным
промышленным дизайном в тёмных тонах. Сессия сохраняется при обновлении,
но запрашивается заново после закрытия вкладки.
Запуск: streamlit run app_streamlit.py
"""
import streamlit as st
from rag_engine import MachineryAssistant
import streamlit.components.v1 as components
import time
import re
import html as html_module
import uuid
import json
import hashlib
import hmac
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------- Папка для хранения сессий ----------
SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)

# =============================================================================
# ХЕШИРОВАНИЕ ПАРОЛЕЙ
# Алгоритм: PBKDF2-HMAC-SHA256, 310 000 итераций (рекомендация OWASP 2024)
#
# Пароль берётся из переменной окружения TM_PASSWORD (не из исходного кода!).
# В .env добавьте строку: TM_PASSWORD=ваш_надёжный_пароль
# =============================================================================
_PBKDF2_ITERS = 310_000

# Фиксированная соль для пользователя "TM" (16 байт, hex-строка).
# Для смены соли: import os; os.urandom(16).hex()
_TM_SALT = bytes.fromhex("3a7f92c1d5e04b68a19f3c82e6b0d471")

# ✅ Пароль из переменной окружения — не хранится в коде
_raw_password = os.getenv("TM_PASSWORD", "").encode("utf-8")
if not _raw_password:
    raise EnvironmentError(
        "Переменная окружения TM_PASSWORD не задана. "
        "Добавьте её в .env: TM_PASSWORD=ваш_пароль"
    )
_TM_HASH = hashlib.pbkdf2_hmac("sha256", _raw_password, _TM_SALT, _PBKDF2_ITERS).hex()
del _raw_password   # убираем пароль из памяти как можно раньше

# Словарь пользователей: имя → (соль, хеш)
_VALID_USERS: dict[str, tuple[bytes, str]] = {
    "TM": (_TM_SALT, _TM_HASH),
}


def check_credentials(username: str, password: str) -> bool:
    """Timing-safe проверка учётных данных."""
    entry = _VALID_USERS.get(username)
    if not entry:
        # Фиктивный расчёт для защиты от timing-атак
        hashlib.pbkdf2_hmac("sha256", b"", b"\x00" * 16, _PBKDF2_ITERS)
        return False
    salt, stored_hash = entry
    trial_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS
    ).hex()
    return hmac.compare_digest(trial_hash, stored_hash)


# =============================================================================

# ---------- XSS-защита ----------
_SAFE_SCHEMES = re.compile(r"^(https?|mailto|tel)://", re.IGNORECASE)
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


def sanitize_markdown_links(text: str) -> str:
    def replace_link(m: re.Match) -> str:
        label = m.group(1)
        url_raw = m.group(2).strip()
        url = html_module.unescape(url_raw)
        url_normalized = re.sub(r"[\s\x00-\x1f]+", "", url)
        if _SAFE_SCHEMES.match(url_normalized) or url_normalized.startswith(("#", "/")):
            return f"[{label}]({url})"
        return f"[{label}](#)"
    return _MD_LINK.sub(replace_link, text)


# ---------- Работа с сессионными куками ----------
def set_session_cookie(name: str, value: str) -> None:
    """Сессионная кука (без max-age) — браузер удалит её при закрытии вкладки."""
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
    components.html(
        f"""
        <script>
        var isSecure = (location.protocol === 'https:') ? '; Secure' : '';
        document.cookie = "{name}=; max-age=-1; path=/; SameSite=Lax" + isSecure;
        </script>
        """,
        height=0,
    )


# ---------- Очистка устаревших сессий ----------
def cleanup_stale_sessions(max_age_seconds: int = 86_400) -> None:
    """
    Удаляет auth-токены старше max_age_seconds (по умолчанию 24 ч).
    Вызывается один раз при старте приложения.
    """
    now = time.time()
    for f in SESSIONS_DIR.glob("auth_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if now - data.get("login_time", 0) > max_age_seconds:
                f.unlink()
        except (json.JSONDecodeError, OSError):
            f.unlink()   # битый файл — тоже удаляем


cleanup_stale_sessions()


# --- Настройка страницы ---
st.set_page_config(
    page_title="Ассистент по Технологии машиностроения",
    page_icon="⚙️",
    layout="centered",
)

# --- Кастомный CSS ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400&display=swap');

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
    code {
        font-family: 'JetBrains Mono', monospace;
        color: #f6ad55 !important;
        background-color: rgba(246, 173, 85, 0.12) !important;
        border-radius: 4px;
        padding: 2px 6px;
    }
    [data-testid="stSidebar"] {
        background-color: #11151a;
        border-right: 1px solid #2d3748;
    }
    [data-testid="stSidebar"] * { color: #cbd5e0 !important; }
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
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background-color: #1e2229;
        border-left: 4px solid #4a5568;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
        background-color: #12161c;
        border-left: 4px solid #dd6b20;
    }
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
        transform: translateY(1px);
        box-shadow: 0 0 8px rgba(221, 107, 32, 0.5);
    }
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
    hr {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
        margin: 25px 0;
    }
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
    .greeting-card {
        background-color: rgba(26, 32, 44, 0.5);
        border-left: 3px solid #718096;
        border-radius: 0 8px 8px 0;
        padding: 16px;
        margin: 10px 0;
    }
    .greeting-card p { font-size: 0.95rem; line-height: 1.5; margin: 0; color: #cbd5e0; }
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
        0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(72, 187, 120, 0.7); }
        70% { transform: scale(1.1); box-shadow: 0 0 0 5px rgba(72, 187, 120, 0); }
        100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(72, 187, 120, 0); }
    }
    .feedback-desc { color: #8b949e; font-size: 0.85rem; margin: 0; line-height: 1.4; }
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ==================== Работа с файлами сессий ====================
def _auth_file(sid: str) -> Path:
    return SESSIONS_DIR / f"auth_{sid}.json"

def _chat_file(username: str) -> Path:
    return SESSIONS_DIR / f"chat_{username}.json"


# --- Auth-токен ---
def load_auth(sid: str) -> dict | None:
    f = _auth_file(sid)
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except (json.JSONDecodeError, OSError):
            return None
    return None

def save_auth(sid: str, username: str) -> None:
    with open(_auth_file(sid), "w", encoding="utf-8") as fp:
        json.dump({"username": username, "login_time": time.time()}, fp)

def delete_auth(sid: str) -> None:
    f = _auth_file(sid)
    if f.exists():
        f.unlink()


# --- Чат пользователя ---
def load_chat(username: str) -> list[dict]:
    """Загружает историю чата. Возвращает приветствие, если файла нет."""
    f = _chat_file(username)
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, list) and data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return _build_initial_messages()

def save_chat(username: str, messages: list[dict]) -> None:
    with open(_chat_file(username), "w", encoding="utf-8") as fp:
        json.dump(messages, fp, ensure_ascii=False)


# ==================== ВОССТАНОВЛЕНИЕ СЕССИИ ====================
if "logged_in" not in st.session_state:
    sid_from_cookie: str | None = None
    try:
        sid_from_cookie = st.context.cookies.get("session_id")
    except AttributeError:
        sid_from_cookie = None

    if sid_from_cookie:
        auth_data = load_auth(sid_from_cookie)
        if auth_data:
            _username = auth_data["username"]
            st.session_state.logged_in = True
            st.session_state.sid = sid_from_cookie
            st.session_state.username = _username
            st.session_state.messages = load_chat(_username)
            st.session_state.login_time = auth_data["login_time"]
            st.session_state.login_attempts = 0
        else:
            delete_cookie("session_id")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "login_attempts" not in st.session_state:
    st.session_state.login_attempts = 0
if "last_attempt_time" not in st.session_state:
    st.session_state.last_attempt_time = 0.0


# ==================== АВТОРИЗАЦИЯ ====================
MAX_LOGIN_ATTEMPTS = 5
BLOCK_TIME_SECONDS = 300


def _build_initial_messages() -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": (
                "Привет! Я твой помощник по технологии машиностроения. "
                "Задавай вопрос — я найду ответ в лекциях."
            ),
        }
    ]


def login_user(username: str) -> str:
    sid = str(uuid.uuid4())
    save_auth(sid, username)
    set_session_cookie("session_id", sid)
    return sid


def logout() -> None:
    if "sid" in st.session_state:
        delete_auth(st.session_state.sid)
        delete_cookie("session_id")
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


# --- Блокировка при превышении попыток ---
if not st.session_state.logged_in:
    if st.session_state.login_attempts >= MAX_LOGIN_ATTEMPTS:
        time_since = time.time() - st.session_state.last_attempt_time
        if time_since < BLOCK_TIME_SECONDS:
            remaining = int(BLOCK_TIME_SECONDS - time_since)
            st.error(
                f"🔒 Слишком много попыток. "
                f"Попробуйте через {remaining // 60} мин {remaining % 60} сек."
            )
            st.stop()
        else:
            st.session_state.login_attempts = 0

# --- Форма входа ---
if not st.session_state.logged_in:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div style="text-align: center; margin-bottom: 20px;">
            <h1 style="color: #e2e8f0;">🔒 Вход в систему</h1>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input("Логин")
            password = st.text_input("Пароль", type="password")
            submitted = st.form_submit_button("Войти", use_container_width=True)

            if submitted:
                if check_credentials(username, password):
                    sid = login_user(username)
                    st.session_state.logged_in = True
                    st.session_state.sid = sid
                    st.session_state.username = username
                    st.session_state.login_time = time.time()
                    st.session_state.login_attempts = 0
                    st.session_state.messages = load_chat(username)
                    st.rerun()
                else:
                    st.session_state.login_attempts += 1
                    st.session_state.last_attempt_time = time.time()
                    st.error("Неверный логин или пароль.")
    st.stop()


# ==================== ОСНОВНОЙ ИНТЕРФЕЙС ====================

st.title("⚙️ Ассистент по Технологии машиностроения")
st.markdown("""
<div class="advice-box">
    <span style="font-size: 1.5rem;">✨</span>
    <div>
        <strong>Совет:</strong> Задайте вопрос так, как спросили бы преподавателя. Я найду ответ в проверенных лекциях и глоссарии.
    </div>
</div>
""", unsafe_allow_html=True)

# --- БОКОВАЯ ПАНЕЛЬ ---
with st.sidebar:
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

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧹 Очистить историю", use_container_width=True):
            st.session_state.messages = [
                {"role": "assistant", "content": "История очищена. Задайте новый вопрос."}
            ]
            if "username" in st.session_state:
                save_chat(st.session_state.username, st.session_state.messages)
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

    # --- Обратная связь ---
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

# --- Ассистент ---
@st.cache_resource
def load_assistant() -> MachineryAssistant:
    return MachineryAssistant()


with st.spinner("⚙️ Загружаем базу знаний и подключаемся к GigaChat..."):
    assistant = load_assistant()

# --- История сообщений ---
if "messages" not in st.session_state:
    st.session_state.messages = _build_initial_messages()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        safe_content = sanitize_markdown_links(message["content"])
        st.markdown(safe_content)

# --- Поле ввода ---
if prompt := st.chat_input("Введите ваш вопрос..."):
    safe_prompt = sanitize_markdown_links(prompt)
    st.session_state.messages.append({"role": "user", "content": safe_prompt})
    with st.chat_message("user"):
        st.markdown(safe_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Думаю..."):
            response = assistant.ask(prompt)
            answer = response["answer"]

            if response.get("sources"):
                sources_text = "\n\n📚 **Источники:**\n"
                for src in response["sources"]:
                    sources_text += f"- {src}\n"
                answer += sources_text

            safe_answer = sanitize_markdown_links(answer)
            st.markdown(safe_answer)
            st.session_state.messages.append({"role": "assistant", "content": safe_answer})

    if "username" in st.session_state:
        save_chat(st.session_state.username, st.session_state.messages)
