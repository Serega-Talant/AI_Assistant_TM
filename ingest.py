import os
import re
import glob
from functools import partial
from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_core.documents import Document
import docx2txt

from embeddings import get_embeddings   # ← единая конфигурация, без дублирования

load_dotenv()

DATA_DIR = "./data"
VECTOR_DB_DIR = "./vector_db"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# Эмбеддинги из общего модуля
embeddings = get_embeddings()


def load_documents(data_dir: str) -> list[Document]:
    documents: list[Document] = []

    # ✅ Явная UTF-8 кодировка — иначе на Windows кириллица ломается
    TextLoaderUTF8 = partial(TextLoader, encoding="utf-8")
    txt_loader = DirectoryLoader(
        data_dir, glob="*.txt", loader_cls=TextLoaderUTF8, show_progress=True
    )
    txt_docs = txt_loader.load()
    documents.extend(txt_docs)
    print(f"✅ Загружено .txt: {len(txt_docs)}")

    pdf_loader = DirectoryLoader(
        data_dir, glob="*.pdf", loader_cls=PyPDFLoader, show_progress=True
    )
    pdf_docs = pdf_loader.load()
    documents.extend(pdf_docs)
    print(f"✅ Загружено .pdf: {len(pdf_docs)}")

    docx_files = glob.glob(os.path.join(data_dir, "*.docx"))
    for file in docx_files:
        text = docx2txt.process(file)
        # Убираем управляющие символы, сохраняя \n и \t
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        documents.append(Document(page_content=text, metadata={"source": file}))
    print(f"✅ Загружено .docx: {len(docx_files)}")

    return documents


def split_documents(documents: list[Document]) -> list[Document]:
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = text_splitter.split_documents(documents)
    print(f"✂️  Документы разбиты на {len(chunks)} чанков")
    return chunks


def create_vector_store(chunks: list[Document], persist_dir: str) -> Chroma:
    vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=persist_dir,
        collection_name="machinery_technology",
    )
    print(f"💾 Векторное хранилище сохранено в {persist_dir}")
    return vector_store


def main() -> None:
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
