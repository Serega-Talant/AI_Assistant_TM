"""
Веб-интерфейс для студентов с авторизацией и обратной связью.
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

# ==================== АВТОРИЗАЦИЯ ====================
def check_credentials(username, password):
    """Проверка логина и пароля (можно вынести в переменные окружения)."""
    return username == "TM" and password == "123"

def logout():
    """Полный сброс сессии."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# Инициализируем флаг авторизации
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# Если не авторизован — показываем форму входа
if not st.session_state.logged_in:
    st.title("🔒 Вход в систему")
    with st.form("login_form"):
        username = st.text_input("Логин")
        password = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button("Войти")
        if submitted:
            if check_credentials(username, password):
                st.session_state.logged_in = True
                st.session_state.login_time = time.time()  # для тайм-аута
                st.success("Вход выполнен успешно!")
                st.rerun()
            else:
                st.error("Неверный логин или пароль. Попробуйте ещё раз.")
    st.stop()  # Прерываем выполнение, чат не отображается

# Небольшая защита: тайм-аут сессии (раскомментируйте при необходимости)
# if "login_time" in st.session_state:
#     if time.time() - st.session_state.login_time > 1800:  # 30 минут
#         logout()

# ==================== ОСНОВНОЙ ИНТЕРФЕЙС ====================

# --- Заголовок и описание ---
st.title("🔧 Ассистент по Технологии машиностроения")
st.markdown("""
Задайте вопрос по специальности — ассистент ответит, опираясь на лекции и глоссарий.
""")

# --- Боковая панель ---
with st.sidebar:
    st.header("ℹ️ О проекте")
    st.markdown("""
    **Назначение:** помощь студентам специальности «Технология машиностроения».
    
    **Модели:**
    - Эмбеддинги: sentence-transformers (локально)
    - LLM: GigaChat (Freemium)
    """)

    st.divider()

    # --- Форма обратной связи через iframe ---
    st.subheader("📝 Обратная связь")
    components.html(
        """
        <script src="https://forms.yandex.ru/_static/embed.js"></script>
        <iframe src="https://forms.yandex.ru/u/69a964ed6d2d73372c353b06?iframe=1"
                frameborder="0"
                name="ya-form-69a964ed6d2d73372c353b06"
                width="100%"
                height="400">
        </iframe>
        """,
        height=450,
    )

    st.divider()

    # Кнопка выхода из системы
    if st.button("🚪 Выйти"):
        logout()

    st.divider()

    # Очистка истории чата (не затрагивает авторизацию)
    if st.button("🧹 Очистить историю"):
        if "messages" in st.session_state:
            st.session_state.messages = [
                {"role": "assistant", "content": "История очищена. Задайте новый вопрос."}
            ]
        st.rerun()

# --- Инициализация ассистента (кэшируем) ---
@st.cache_resource
def load_assistant():
    return MachineryAssistant()

with st.spinner("Загружаем базу знаний и подключаемся к GigaChat..."):
    assistant = load_assistant()

# --- Инициализация истории сообщений ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Здравствуйте! Я — ассистент по технологии машиностроения. Задайте ваш вопрос."}
    ]

# --- Отображение истории чата ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- Поле ввода вопроса ---
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