import os
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_gigachat.chat_models import GigaChat
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from embeddings import get_embeddings

load_dotenv()


class MachineryAssistant:
    def __init__(self, vector_db_dir: str = "./vector_db"):
        # 1. Модель GigaChat
        self.llm = GigaChat(
            credentials=os.getenv("GIGACHAT_CREDENTIALS"),
            scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            verify_ssl_certs=False,
            model="GigaChat",
            temperature=0.2,   # ниже → меньше «фантазии» при ответах по контексту
            timeout=30,
        )

        # 2. Локальные эмбеддинги (общий модуль)
        self.embeddings = get_embeddings()

        # 3. Векторное хранилище
        self.vector_store = Chroma(
            persist_directory=vector_db_dir,
            embedding_function=self.embeddings,
            collection_name="machinery_technology",
        )

        # 4. MMR-ретривер: разнообразные фрагменты вместо однотипных top-k
        #    fetch_k=12 — кандидаты, k=4 — финальные чанки, lambda_mult — баланс
        #    релевантность/разнообразие (0 = max разнообразие, 1 = max релевантность)
        self.retriever = self.vector_store.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 4, "fetch_k": 12, "lambda_mult": 0.65},
        )

        # 5. Цепочка ответа (принимает готовый context, НЕ дёргает ретривер сама)
        self.answer_chain = self._create_answer_chain()

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _format_docs(self, docs: list) -> str:
        return "\n\n".join(doc.page_content for doc in docs)

    def _create_answer_chain(self):
        system_prompt = (
            "Ты — ИИ-ассистент для студентов специальности «Технология машиностроения».\n"
            "Правила:\n"
            "1. Отвечай ТОЛЬКО на основе предоставленного контекста из лекций и глоссария.\n"
            "2. Структура ответа: краткий вывод (1–2 предложения), затем подробное объяснение.\n"
            "3. Если в контексте нет нужной информации — честно сообщи об этом "
            "и предложи переформулировать вопрос.\n"
            "4. Не придумывай факты и не используй знания вне контекста.\n\n"
            "Контекст:\n{context}"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{question}"),
        ])

        return prompt | self.llm | StrOutputParser()

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def ask(self, question: str) -> dict:
        """
        Возвращает словарь {"answer": str, "sources": list[str]}.
        При любой ошибке возвращает человекочитаемое сообщение — не бросает исключение.
        """
        try:
            # Один вызов ретривера — результат переиспользуется и для контекста, и для источников
            docs = self.retriever.invoke(question)
            context = self._format_docs(docs)
            answer = self.answer_chain.invoke({"context": context, "question": question})
            sources = list({doc.metadata.get("source", "неизвестно") for doc in docs})
            return {"answer": answer, "sources": sources}

        except Exception as exc:
            return {
                "answer": (
                    f"⚠️ Не удалось получить ответ: {exc}.\n\n"
                    "Попробуйте повторить запрос или перефразируйте вопрос."
                ),
                "sources": [],
            }


# ------------------------------------------------------------------
# Быстрая проверка из командной строки
# ------------------------------------------------------------------
if __name__ == "__main__":
    assistant = MachineryAssistant()
    print("💬 Ассистент готов! Задавайте вопросы (для выхода введите 'exit')")
    while True:
        question = input("\n🤔 Ваш вопрос: ").strip()
        if question.lower() in ("exit", "quit", "выход"):
            break
        if not question:
            continue
        response = assistant.ask(question)
        print(f"\n🎓 Ответ: {response['answer']}")
        if response["sources"]:
            print("📚 Источники:", ", ".join(response["sources"]))
