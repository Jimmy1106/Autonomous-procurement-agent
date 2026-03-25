"""
rag/retriever.py

封裝 ChromaDB 的查詢邏輯，供 RAG tool 使用。
向量資料庫由 rag/ingest.py 事先建立，這個模組只負責查詢。
"""
import os
from pathlib import Path

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

# ChromaDB 持久化路徑
CHROMA_PATH = Path(os.getenv("CHROMA_PATH", "data/chroma"))

# 每次查詢回傳的最相關段落數
TOP_K = 3

_vectorstore = None


def _get_vectorstore() -> Chroma:
    """Lazy initialization：第一次查詢時才載入向量資料庫。"""
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = Chroma(
            persist_directory=str(CHROMA_PATH),
            embedding_function=OpenAIEmbeddings(model="text-embedding-3-small"),
        )
    return _vectorstore


def retrieve(query: str) -> str:
    """
    查詢和 query 最相關的文件段落，回傳合併後的文字。
    若向量資料庫不存在或查無結果，回傳提示訊息。
    """
    if not CHROMA_PATH.exists():
        return "知識庫尚未建立，請先執行 python rag/ingest.py。"

    try:
        vectorstore = _get_vectorstore()
        docs = vectorstore.similarity_search(query, k=TOP_K)

        if not docs:
            return "查無相關資料。"

        # 合併檢索到的段落，附上來源文件名稱
        results = []
        for doc in docs:
            source = doc.metadata.get("source", "未知來源")
            results.append(f"【{source}】\n{doc.page_content}")

        return "\n\n".join(results)

    except Exception as e:
        return f"查詢失敗：{e}"
