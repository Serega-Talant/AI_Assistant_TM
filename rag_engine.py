import os
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_gigachat.chat_models import GigaChat
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

load_dotenv()

class MachineryAssistant:
    def __init__(self, vector_db_dir: str = "./vector_db"):
        # 1. Модель GigaChat
        self.llm = GigaChat(
            credentials=os.getenv("GIGACHAT_CREDENTIALS"),
            scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            verify_ssl_certs=False,
            model="GigaChat",
            temperature=0.3,
            timeout=30,
        )
        
        # 2. Локальные эмбеддинги
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        
        # 3. Векторное хранилище и ретривер
        self.vector_store = Chroma(
            persist_directory=vector_db_dir,
            embedding_function=self.embeddings,
            collection_name="machinery_technology",
        )
        self.retriever = self.vector_store.as_retriever(search_kwargs={"k": 4})
        
        # 4. Создаём RAG-цепочку
        self.rag_chain = self._create_rag_chain()
    
    def _format_docs(self, docs):
        return "\n\n".join(doc.page_content for doc in docs)
    
    def _create_rag_chain(self):
        system_prompt = (
            "Ты — ИИ-ассистент для студентов специальности «Технология машиностроения». "
            "Твоя задача — отвечать на вопросы, ИСПОЛЬЗУЯ ТОЛЬКО ПРЕДОСТАВЛЕННЫЙ КОНТЕКСТ из лекций и глоссария. "
            "Если в контексте нет информации для ответа, вежливо скажи об этом и предложи переформулировать вопрос.\n\n"
            "Контекст:\n{context}"
        )
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{question}"),
        ])
        
        rag_chain = (
            {"context": self.retriever | self._format_docs, "question": RunnablePassthrough()}
            | prompt
            | self.llm
            | StrOutputParser()
        )
        
        return rag_chain
    
    def ask(self, question: str) -> dict:
        # Сначала получаем документы отдельно
        docs = self.retriever.invoke(question)
        # Форматируем контекст
        context = self._format_docs(docs)
        # Генерируем ответ
        answer = self.rag_chain.invoke(question)
        # Собираем уникальные источники
        sources = list({doc.metadata.get("source", "неизвестно") for doc in docs})
        return {
            "answer": answer,
            "sources": sources,
        }

if __name__ == "__main__":
    assistant = MachineryAssistant()
    print("💬 Ассистент готов! Задавайте вопросы (для выхода введите 'exit')")
    while True:
        question = input("\n🤔 Ваш вопрос: ")
        if question.lower() in ["exit", "quit", "выход"]:
            break
        response = assistant.ask(question)
        print(f"\n🎓 Ответ: {response['answer']}")
    