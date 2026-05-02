import os
import re
import glob
from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings  # Локальные эмбеддинги
import docx2txt

load_dotenv()

DATA_DIR = "./data"
VECTOR_DB_DIR = "./vector_db"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# ✅ Бесплатные локальные эмбеддинги (работают офлайн)
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': True}
)

def load_documents(data_dir: str):
    documents = []
    
    txt_loader = DirectoryLoader(data_dir, glob="*.txt", loader_cls=TextLoader, show_progress=True)
    txt_docs = txt_loader.load()
    documents.extend(txt_docs)
    print(f"✅ Загружено .txt: {len(txt_docs)}")

    pdf_loader = DirectoryLoader(data_dir, glob="*.pdf", loader_cls=PyPDFLoader, show_progress=True)
    pdf_docs = pdf_loader.load()
    documents.extend(pdf_docs)
    print(f"✅ Загружено .pdf: {len(pdf_docs)}")

    docx_files = glob.glob(os.path.join(data_dir, "*.docx"))
    for file in docx_files:
        text = docx2txt.process(file)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1F\x7F]', '', text)
        documents.append(Document(page_content=text, metadata={"source": file}))
    print(f"✅ Загружено .docx: {len(docx_files)}")
    
    return documents

def split_documents(documents):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = text_splitter.split_documents(documents)
    print(f"✂️ Документы разбиты на {len(chunks)} чанков")
    return chunks

def create_vector_store(chunks, persist_dir: str):
    vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=persist_dir,
        collection_name="machinery_technology",
    )
    print(f"💾 Векторное хранилище сохранено в {persist_dir}")
    return vector_store

def main():
    print("🚀 Начинаем индексацию базы знаний...")
    docs = load_documents(DATA_DIR)
    if not docs:
        print("❌ Не найдено документов для индексации!")
        return
    chunks = split_documents(docs)
    create_vector_store(chunks, VECTOR_DB_DIR)
    print("🎉 Индексация завершена успешно!")

if __name__ == "__main__":
    main()