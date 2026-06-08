"""
app_streamlit.py — веб-интерфейс RAG-ассистента на Streamlit.

Архитектура интерфейса:
  • Сессии: UUID-файлы в sessions/ + сессионная cookie в браузере.
    F5 → чат сохраняется. Закрытие вкладки → cookie исчезает → при
    следующем открытии начинается новая сессия с чистой историей.
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
from pathlib import Path

# ---------------------------------------------------------------------------
# Настройка папки хранения сессий
# ---------------------------------------------------------------------------
# Каждая активная вкладка браузера соответствует одному JSON-файлу в sessions/.
# Это позволяет нескольким пользователям работать одновременно изолированно.
SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)  # создаём папку если не существует

# ---------------------------------------------------------------------------
# XSS-ЗАЩИТА
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# УПРАВЛЕНИЕ СЕССИОННЫМИ КУКАМИ
# ---------------------------------------------------------------------------
# Streamlit не предоставляет нативного API для установки cookie.
# Обходим это через components.html() — встраиваем минимальный JS в iframe.
# Ключевые параметры cookie:
#   • path=/        — кука доступна на всех путях сайта
#   • SameSite=Lax  — защита от CSRF (кука не отправляется при cross-site POST)
#   • Secure        — только по HTTPS (добавляем динамически если сайт на HTTPS)
#
# Почему сессионная кука (без max-age):
#   Браузер удаляет сессионные куки при закрытии вкладки/окна. Это обеспечивает
#   поведение "закрыл → новая история при следующем открытии".

def set_session_cookie(name: str, value: str) -> None:
    """Устанавливает сессионную cookie (без max-age — браузер удалит при закрытии вкладки)."""
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
    """Удаляет cookie установкой отрицательного max-age."""
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
# Конфигурация страницы Streamlit
# ---------------------------------------------------------------------------
# set_page_config ОБЯЗАН быть первым вызовом Streamlit в скрипте.
st.set_page_config(
    page_title="Ассистент по Технологии машиностроения",
    page_icon="⚙️",
    layout="centered",
)

# ---------------------------------------------------------------------------
# Кастомные стили (CSS)
# ---------------------------------------------------------------------------
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
        transform: translateY(1px);
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
        box-shadow: 0 0 0 3px rgba(221, 107, 32, 0.25);
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
    @keyframes pulse {
        0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(72, 187, 120, 0.7); }
        70% { transform: scale(1.1); box-shadow: 0 0 0 5px rgba(72, 187, 120, 0); }
        100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(72, 187, 120, 0); }
    }
    .feedback-desc { color: #8b949e; font-size: 0.85rem; margin: 0; line-height: 1.4; }

    /* Скрываем стандартный хедер Streamlit */
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# РАБОТА С ФАЙЛАМИ СЕССИЙ
# ---------------------------------------------------------------------------
# Структура хранения:
#   sessions/
#     session_<uuid>.json   ← один файл на каждую активную вкладку
#
# Содержимое JSON-файла:
#   {
#     "session_id":  "uuid4-строка",
#     "start_time":  1718000000.0,
#     "messages":    [{"role": "assistant", "content": "..."}, ...]
#   }
#
# Жизненный цикл:
#   Создан  → при первом открытии вкладки
#   Обновлён → после каждого сообщения (save_session)
#   Прочитан → при F5 (load_session)
#   Удалён  → при очистке истории или вручную

def _session_file(sid: str) -> Path:
    """Возвращает путь к JSON-файлу сессии по её UUID."""
    return SESSIONS_DIR / f"session_{sid}.json"


def load_session(sid: str) -> dict | None:
    """
    Загружает данные сессии из файла.

    Возвращает dict с ключами session_id, start_time, messages
    или None если файл отсутствует / повреждён.
    """
    f = _session_file(sid)
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_session(sid: str, messages: list[dict]) -> None:
    """
    Сохраняет текущее состояние чата в JSON-файл.
    Вызывается после каждого сообщения — история не теряется при F5.
    """
    data = {
        "session_id": sid,
        "start_time": st.session_state.get("start_time", time.time()),
        "messages": messages,
    }
    with open(_session_file(sid), "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)


def delete_session(sid: str) -> None:
    """Удаляет файл сессии."""
    f = _session_file(sid)
    if f.exists():
        f.unlink()


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


# ---------------------------------------------------------------------------
# ВОССТАНОВЛЕНИЕ / СОЗДАНИЕ СЕССИИ ПРИ ЗАГРУЗКЕ СТРАНИЦЫ
# ---------------------------------------------------------------------------
# При первом запуске (нет session_initialized в session_state):
#   1. Ищем session_id в cookie браузера.
#   2. Если cookie есть и файл существует → восстанавливаем историю (F5).
#   3. Если нет → создаём новый UUID, новый файл, новую историю.
#
# При закрытии вкладки браузер удаляет сессионную куку →
# при следующем открытии шаг 2 не срабатывает → новая чистая сессия.

if "session_initialized" not in st.session_state:
    sid_from_cookie: str | None = None
    try:
        sid_from_cookie = st.context.cookies.get("session_id")
    except AttributeError:
        sid_from_cookie = None

    if sid_from_cookie:
        session_data = load_session(sid_from_cookie)
        if session_data:
            # Восстанавливаем существующую сессию
            st.session_state.sid = sid_from_cookie
            st.session_state.messages = session_data["messages"]
            st.session_state.start_time = session_data["start_time"]
        else:
            # Cookie есть, но файл не найден/повреждён → создаём новую сессию
            delete_cookie("session_id")
            sid_from_cookie = None

    if not sid_from_cookie:
        # Создаём абсолютно новую сессию
        new_sid = str(uuid.uuid4())
        initial_messages = _build_initial_messages()
        save_session(new_sid, initial_messages)
        set_session_cookie("session_id", new_sid)
        st.session_state.sid = new_sid
        st.session_state.messages = initial_messages
        st.session_state.start_time = time.time()

    st.session_state.session_initialized = True

# Страховка: если messages всё же не проинициализированы
if "messages" not in st.session_state:
    st.session_state.messages = _build_initial_messages()


# ---------------------------------------------------------------------------
# ОСНОВНОЙ ИНТЕРФЕЙС
# ---------------------------------------------------------------------------
st.title("⚙️ Ассистент по Технологии машиностроения")

# Совет-подсказка над чатом
st.markdown("""
<div class="advice-box">
    <span style="font-size: 1.5rem;">✨</span>
    <div>
        <strong>Совет:</strong> Задайте вопрос так, как спросили бы преподавателя. Я найду ответ в проверенных лекциях и глоссарии.
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# БОКОВАЯ ПАНЕЛЬ
# ---------------------------------------------------------------------------
with st.sidebar:
    # Шапка с аватаром
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

    # Кнопка очистки истории
    if st.button("🧹 Очистить историю", use_container_width=True):
        st.session_state.messages = [
            {"role": "assistant", "content": "История очищена. Задайте новый вопрос."}
        ]
        if "sid" in st.session_state:
            save_session(st.session_state.sid, st.session_state.messages)
        st.rerun()

    st.divider()
    st.subheader("🚀 Что я умею")
    st.markdown("""
    - 📖 Объяснять термины из глоссария  
    - 🧪 Разбирать технологические процессы  
    - 📚 Опираться только на твои лекции  
    - ⚡ Давать мгновенные ответы с источниками  
    """)
    st.divider()

    # Блок обратной связи
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


# ---------------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ АССИСТЕНТА
# ---------------------------------------------------------------------------
@st.cache_resource
def load_assistant():
    return MachineryAssistant()


with st.spinner("⚙️ Загружаем базу знаний и подключаемся к GigaChat..."):
    assistant = load_assistant()


# ---------------------------------------------------------------------------
# ИСТОРИЯ ЧАТА
# ---------------------------------------------------------------------------
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        safe_content = sanitize_markdown_links(message["content"])
        st.markdown(safe_content)


# ---------------------------------------------------------------------------
# ОБРАБОТКА НОВОГО СООБЩЕНИЯ
# ---------------------------------------------------------------------------
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

    # Персистируем историю после каждого сообщения
    if "sid" in st.session_state:
        save_session(st.session_state.sid, st.session_state.messages)