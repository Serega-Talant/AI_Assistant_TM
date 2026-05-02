"""
Веб-интерфейс для студентов.
Запуск: streamlit run app_streamlit.py
"""
import streamlit as st
from rag_engine import MachineryAssistant

# --- Настройка страницы ---
st.set_page_config(
    page_title="Ассистент по Технологии машиностроения",
    page_icon="🔧",
    layout="centered",
)

# --- Заголовок и описание ---
st.title("🔧 Ассистент по Технологии машиностроения")
st.markdown("""
Задайте вопрос по специальности — ассистент ответит, опираясь на лекции и глоссарий.
""")

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
    # Добавляем вопрос пользователя в историю
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Генерируем ответ
    with st.chat_message("assistant"):
        with st.spinner("Думаю..."):
            response = assistant.ask(prompt)
            answer = response["answer"]
            
            # Если есть источники, добавляем их к ответу
            if response.get("sources"):
                sources_text = "\n\n📚 **Источники:**\n"
                for src in response["sources"]:
                    sources_text += f"- {src}\n"
                answer += sources_text
            
            st.markdown(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})

# --- Боковая панель ---
with st.sidebar:
    st.header("ℹ️ О проекте")
    st.markdown("""
    **Назначение:** помощь студентам специальности «Технология машиностроения».
    
    **Принцип работы:**
    1. Вопрос преобразуется в вектор (локальная модель).
    2. Система находит 4 наиболее релевантных фрагмента из лекций.
    3. GigaChat генерирует ответ только на основе этих фрагментов.
    
    **Модели:**
    - Эмбеддинги: sentence-transformers (локально)
    - LLM: GigaChat (Freemium)
    """)
    
    st.divider()
    
    if st.button("🧹 Очистить историю"):
        st.session_state.messages = [
            {"role": "assistant", "content": "История очищена. Задайте новый вопрос."}
        ]
        st.rerun()