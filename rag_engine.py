"""
rag_engine.py — ядро RAG-системы (Retrieval-Augmented Generation) «генерация, дополненная поиском».

Что такое RAG:
  Классические LLM (большие языковые модели) знают только то, что было
  в их обучающих данных. RAG расширяет это: перед генерацией ответа система
  ищет релевантные фрагменты в собственной базе знаний и передаёт их
  модели как дополнительный контекст. Модель отвечает "опираясь на документ",
  а не по памяти — это снижает галлюцинации и позволяет работать с
  любыми специализированными данными без дорогостоящего дообучения.

Поток данных в этом файле:
  Вопрос → [ретривер ChromaDB] → 4 релевантных чанка →
  → [промпт + GigaChat] → ответ с источниками

Зависимости:
  • embeddings.py  — модель для векторизации вопроса
  • vector_db/     — ChromaDB с проиндексированными чанками (создаётся ingest.py)
  • GigaChat API   — LLM для генерации ответа по найденному контексту
"""

import os
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_gigachat.chat_models import GigaChat

# ChatPromptTemplate — шаблон промпта, поддерживающий роли (system/human/ai)
# и переменные-подстановки в фигурных скобках {context}, {question}
from langchain_core.prompts import ChatPromptTemplate

# StrOutputParser — финальный элемент цепочки: извлекает текст из объекта
# AIMessage, который возвращает GigaChat, и отдаёт чистую строку
from langchain_core.output_parsers import StrOutputParser

from embeddings import get_embeddings

# Загружаем .env — нужен GIGACHAT_CREDENTIALS для аутентификации в API
load_dotenv()


class MachineryAssistant:
    """
    Инкапсулирует всю логику RAG-ассистента.

    Инициализация (метод __init__) создаёт все компоненты один раз.
    Streamlit кеширует экземпляр через @st.cache_resource, поэтому
    __init__ вызывается только при первом запуске, а не при каждом запросе.
    """

    def __init__(self, vector_db_dir: str = "./vector_db"):
        # 1. Языковая модель GigaChat
    
        # verify_ssl_certs=False — отключает проверку SSL-сертификата при
        # обращении к API. Необходимо, так как у Сбера используются
        # российские сертификаты, которые не входят в стандартные цепочки
        # доверия западных ОС.
        #
        # temperature=0.2 — "температура" управляет случайностью генерации:
        #   0.0 — детерминированный ответ (всегда одно и то же)
        #   1.0 — максимальное разнообразие (модель "фантазирует")
        #   0.2 — низкая температура, ответы точные и предсказуемые,
        #         что важно для учебного ассистента с опорой на контекст.
        self.llm = GigaChat(
            credentials=os.getenv("GIGACHAT_CREDENTIALS"),
            scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            verify_ssl_certs=False,
            model="GigaChat",
            temperature=0.2,
            timeout=30,       # секунды ожидания ответа от API до TimeoutError
        )

        # 2. Модель эмбеддингов-
        self.embeddings = get_embeddings()

        # 3. Подключение к существующему векторному хранилищу
        # Chroma() открывает уже существующую БД из persist_directory.
        self.vector_store = Chroma(
            persist_directory=vector_db_dir,
            embedding_function=self.embeddings,
            collection_name="machinery_technology",  # должно совпадать с ingest.py
        )

        # 4. MMR-ретривер (Maximum Marginal Relevance)
        # Зачем MMR вместо обычного top-k поиска:
        #   Обычный поиск вернёт k наиболее похожих векторов — но они могут
        #   оказаться почти идентичными фрагментами из одного абзаца.
        #   MMR балансирует релевантность и разнообразие: из fetch_k кандидатов
        #   выбирает k штук так, чтобы они были релевантны вопросу И
        #   отличались друг от друга. Это даёт модели более широкий контекст.
        #
        # Параметры:
        #   k=4          — итоговое число чанков, попадающих в промпт.
        #                  4 × ~1000 символов ≈ 4000 символов контекста
        #   fetch_k=12   — кандидатов для MMR-отбора. Правило: k × 3.
        #                  Чем больше fetch_k, тем лучше выборка, но медленнее.
        #   lambda_mult  — 1.0 = только релевантность (как обычный top-k),
        #                  0.0 = только разнообразие, 0.65 — немного больше
        #                  веса у релевантности, но с хорошим разнообразием.
        self.retriever = self.vector_store.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 4, "fetch_k": 12, "lambda_mult": 0.65},
        )

        # 5. Цепочка генерации ответа (LangChain Expression Language)
        # Цепочка принимает готовый контекст и вопрос — она НЕ вызывает
        # ретривер самостоятельно. Это намеренное решение: в методе ask()
        # мы вызываем ретривер явно один раз, сохраняем результат и
        # используем его дважды — для контекста И для метаданных источников.
        # Если бы ретривер был внутри цепочки (как в типичном RetrievalQA),
        # мы бы не могли получить метаданные без второго вызова к ChromaDB.
        self.answer_chain = self._create_answer_chain()

    # Внутренние вспомогательные методы
    def _format_docs(self, docs: list) -> str:
        """
        Объединяет список Document-объектов в одну строку для промпта.

        Двойной перенос строки (\n\n) между чанками помогает модели
        визуально разделять фрагменты из разных мест документа.
        """
        return "\n\n".join(doc.page_content for doc in docs)

    def _create_answer_chain(self):
        """
        Собирает LCEL-цепочку: промпт → LLM → парсер вывода.

        LCEL (LangChain Expression Language) использует оператор |
        ("pipe") для соединения компонентов — каждый компонент
        принимает вывод предыдущего как входные данные.

        Итоговая цепочка:
          dict(context, question)
            → ChatPromptTemplate → ChatPromptValue
            → GigaChat → AIMessage
            → StrOutputParser → str
        """
        # Системный промпт задаёт роль ассистента и правила поведения.
        # {context} — место подстановки найденных чанков.
        system_prompt = (
            "Ты — ИИ-ассистент для студентов специальности «Технология машиностроения».\n"
            "Правила:\n"
            "1. Отвечай ТОЛЬКО на основе предоставленного контекста из лекций и глоссария.\n"
            "2. Структура ответа: краткий вывод (1–2 предложения), затем подробное объяснение.\n"
            "3. Если в контексте нет нужной информации — честно сообщи об этом и предложи переформулировать вопрос.\n"
            "4. Не придумывай факты и не используй знания вне контекста.\n\n"
            "Контекст:\n{context}"
        )

        # ChatPromptTemplate.from_messages — создаёт шаблон в формате диалога.
        # "system" — инструкции для модели (не видны пользователю).
        # "human"  — сообщение от пользователя, {question} — переменная.
        # Такой формат лучше воспринимается чат-моделями, чем плоский текст.
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{question}"),
        ])

        # Цепочка | — LCEL pipe:
        #   prompt        → принимает dict, возвращает ChatPromptValue
        #   self.llm      → принимает ChatPromptValue, возвращает AIMessage
        #   StrOutputParser → принимает AIMessage, возвращает str
        return prompt | self.llm | StrOutputParser()


    # Публичный API
    def ask(self, question: str) -> dict:
        """
        Обрабатывает вопрос пользователя и возвращает ответ с источниками.

        Алгоритм:
          1. Ретривер векторизует вопрос и ищет 4 релевантных чанка в ChromaDB.
          2. Чанки объединяются в строку-контекст.
          3. Контекст + вопрос передаются в LLM через промпт-шаблон.
          4. LLM генерирует ответ, строго опираясь на контекст.
          5. Из метаданных чанков извлекаются пути к исходным файлам.

        Возвращает:
          dict с ключами:
            "answer"  — строка с ответом модели (или сообщение об ошибке)
            "sources" — список уникальных путей к файлам-источникам
                        (пустой при ошибке или если метаданные отсутствуют)
        """
        try:
            # Шаг 1: единственный вызов ретривера.
            docs = self.retriever.invoke(question)

            # Шаг 2: формируем строку-контекст из найденных чанков
            context = self._format_docs(docs)

            # Шаг 3-4: генерируем ответ через цепочку промпт → LLM → парсер
            answer = self.answer_chain.invoke({"context": context, "question": question})

            # Шаг 5: извлекаем уникальные имена файлов-источников.
            sources = list({doc.metadata.get("source", "неизвестно") for doc in docs})

            return {"answer": answer, "sources": sources}

        except Exception as exc:
            # Перехватываем любое исключение: сетевые ошибки GigaChat,
            # ошибки ChromaDB, неожиданные форматы данных и т.д.
            return {
                "answer": (
                    f"⚠️ Не удалось получить ответ: {exc}.\n\n"
                    "Попробуйте повторить запрос или перефразируйте вопрос."
                ),
                "sources": [],
            }



# Режим командной строки для быстрого тестирования

# Позволяет проверить RAG без запуска Streamlit:
#   python rag_engine.py

if __name__ == "__main__":
    assistant = MachineryAssistant()
    print("💬 Ассистент готов! Задавайте вопросы (для выхода введите 'exit')")

    while True:
        question = input("\n🤔 Ваш вопрос: ").strip()

        # Выход по нескольким командам — удобнее, чем одна фиксированная строка
        if question.lower() in ("exit", "quit", "выход"):
            break

        # Игнорируем пустой ввод (нажатие Enter без текста)
        if not question:
            continue

        response = assistant.ask(question)
        print(f"\n🎓 Ответ: {response['answer']}")

        # Источники показываем только если они есть (при ошибках список пуст)
        if response["sources"]:
            print("📚 Источники:", ", ".join(response["sources"]))
