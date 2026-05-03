"""
Веб-интерфейс для студентов с авторизацией, обратной связью в боковой панели и современным дизайном.
Запуск: streamlit run app_streamlit.py
"""
import streamlit as st
from rag_engine import MachineryAssistant
import streamlit.components.v1 as components
import time

# --- Настройка страницы ---
st.set_page_config(
    page_title="Ассистент по Технологии машиностроения",
    page_icon="🔧",
    layout="centered",
)

# --- Кастомный CSS ---
st.markdown("""
<style>
    /* Общий фон */
    .main {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    }
    .stApp {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    /* Карточки сообщений (общие) */
    .stChatMessage {
        border-radius: 15px;
        padding: 10px;
        margin: 8px 0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        transition: all 0.2s ease;
    }
    .stChatMessage:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        transform: translateY(-1px);
    }
    
    /* Сообщения пользователя – тёмный фон */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background-color: #1e3c72;  /* тёмно-синий */
        color: #ecf0f1;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) .stMarkdown {
        color: #ecf0f1;
    }
    
    /* Сообщения ассистента – тёмная тема */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
        background-color: #2c3e50;
        color: #ecf0f1;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) .stMarkdown {
        color: #ecf0f1;
    }
    
    /* Заголовок "Ваш ИИ‑помощник" – светлый текст на тёмном фоне */
    .assistant-header {
        background: linear-gradient(135deg, #2c3e50, #1a252f);
        border-radius: 12px;
        padding: 12px;
        margin: 10px 0;
        text-align: center;
    }
    .assistant-header h3 {
        color: #ffffff;
        margin: 0;
        font-weight: 600;
        text-shadow: 1px 1px 3px rgba(0,0,0,0.5);
    }
    
    /* Кнопки */
    .stButton > button {
        border-radius: 10px;
        background: #4CAF50;
        color: white;
        font-weight: 600;
        border: none;
        padding: 8px 16px;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        background: #45a049;
        box-shadow: 0 4px 12px rgba(76, 175, 80, 0.3);
        transform: translateY(-2px);
    }
    
    /* Разделитель */
    hr {
        border: none;
        height: 2px;
        background: linear-gradient(90deg, #4CAF50, #2196F3);
        margin: 20px 0;
    }
    
    /* Поле ввода */
    .stChatInput input {
        border-radius: 20px;
        border: 2px solid #e0e0e0;
        padding: 12px 20px;
    }
    .stChatInput input:focus {
        border-color: #4CAF50;
        box-shadow: 0 0 10px rgba(76, 175, 80, 0.2);
    }
</style>
""", unsafe_allow_html=True)

# ==================== АВТОРИЗАЦИЯ ====================
def check_credentials(username, password):
    return username == "TM" and password == "123"

def logout():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🔒 Вход в систему")
    with st.form("login_form"):
        username = st.text_input("Логин")
        password = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button("Войти")
        if submitted:
            if check_credentials(username, password):
                st.session_state.logged_in = True
                st.session_state.login_time = time.time()
                st.success("Вход выполнен успешно!")
                st.rerun()
            else:
                st.error("Неверный логин или пароль. Попробуйте ещё раз.")
    st.stop()

# ==================== ОСНОВНОЙ ИНТЕРФЕЙС ====================

st.title("🔧 Ассистент по Технологии машиностроения")
st.markdown("""
<div style="background: rgba(76, 175, 80, 0.1); border-left: 5px solid #4CAF50; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
    <strong>✨ Совет:</strong> Задайте вопрос так, как спросили бы преподавателя. Я найду ответ в проверенных лекциях и глоссарии.
</div>
""", unsafe_allow_html=True)

# --- БОКОВАЯ ПАНЕЛЬ ---
with st.sidebar:
    # Приветствие с тёмным фоном и светлым текстом
    st.markdown("""
    <div class="assistant-header">
        <span style="font-size: 40px;">🤖</span>
        <h3>Ваш ИИ‑помощник</h3>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div style="background: linear-gradient(135deg, #e0f7fa, #e8f5e9); padding: 15px; border-radius: 12px; margin: 10px 0;">
        <p style="color: #1e3c72; font-weight: 500; margin: 0;">
            Привет! Я твой напарник по специальности «Технология машиностроения». 
            Отвечаю быстро, ссылаюсь на материалы и не придумываю лишнего.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # --- Кнопки управления ---
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧹 Очистить историю", use_container_width=True):
            st.session_state.messages = [
                {"role": "assistant", "content": "История очищена. Задайте новый вопрос."}
            ]
            st.rerun()
    with col2:
        if st.button("🚪 Выйти", use_container_width=True):
            logout()
    
    st.divider()
    
    # Возможности
    st.subheader("🚀 Что я умею")
    st.markdown("""
    - 📖 Объяснять термины из глоссария  
    - 🧪 Разбирать технологические процессы  
    - 📚 Опираться только на твои лекции  
    - ⚡ Давать мгновенные ответы с источниками  
    """)
    
    st.divider()
    
    # Обратная связь
    st.subheader("📝 Обратная связь")
    st.markdown("""
    <p style="color: #999; font-size: 14px;">
        Помоги мне стать лучше! Оставь пожелание или сообщи об ошибке.
    </p>
    """, unsafe_allow_html=True)
    components.html(
        """
        <iframe src="https://forms.yandex.ru/u/69a964ed6d2d73372c353b06?iframe=1&theme=light"
                frameborder="0"
                width="100%"
                height="600"
                scrolling="yes"
                style="background-color: #ffffff; border-radius: 8px;">
        </iframe>
        """,
        height=620,
    )

# --- Ассистент ---
@st.cache_resource
def load_assistant():
    return MachineryAssistant()

with st.spinner("⚙️ Загружаем базу знаний и подключаемся к GigaChat..."):
    assistant = load_assistant()

# --- История сообщений ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Привет! Я твой помощник по технологии машиностроения. Задавай вопрос — я найду ответ в лекциях."}
    ]

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- Поле ввода ---
if prompt := st.chat_input("Введите ваш вопрос..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Думаю..."):
            response = assistant.ask(prompt)
            answer = response["answer"]

            if response.get("sources"):
                sources_text = "\n\n📚 **Источники:**\n"
                for src in response["sources"]:
                    sources_text += f"- {src}\n"
                answer += sources_text

            st.markdown(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})