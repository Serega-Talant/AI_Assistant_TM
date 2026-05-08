"""
Единая конфигурация эмбеддингов для ingest.py и rag_engine.py.
Меняйте модель только здесь — изменения применятся везде.
"""
from langchain_huggingface import HuggingFaceEmbeddings

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def get_embeddings(device: str = "cpu") -> HuggingFaceEmbeddings:
    """
    Возвращает экземпляр локальных эмбеддингов.

    Args:
        device: 'cpu' или 'cuda' (при наличии GPU).
    """
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True},
    )
