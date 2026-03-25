"""
rag/ingest.py

讀取 rag/documents/ 下的所有 .md 文件，切段、向量化後存入 ChromaDB。

執行方式：
    python rag/ingest.py                    # 本機
    docker compose exec api python rag/ingest.py  # Docker

觸發時機：
    - 第一次建立知識庫
    - 新增或修改 rag/documents/ 下的文件後
    - 服務啟動時若偵測到文件有異動，會自動呼叫此模組
"""
import hashlib
import json
import sys
from pathlib import Path

# 確保可以 import 專案模組
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
os.environ.setdefault("CHROMA_PATH", "data/chroma")

from langchain_chroma import Chroma
from langchain_community.document_loaders import TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter

DOCUMENTS_PATH = Path(__file__).parent / "documents"
CHROMA_PATH    = Path(os.getenv("CHROMA_PATH", "data/chroma"))
HASH_FILE      = CHROMA_PATH / ".doc_hash"   # 記錄上次 ingest 的文件 hash

# Markdown 依標題切段，保留段落的語意完整性
HEADERS_TO_SPLIT = [
    ("#",  "h1"),
    ("##", "h2"),
    ("###","h3"),
]


def _compute_hash() -> str:
    """計算所有文件內容的合併 hash，用來偵測文件是否有異動。"""
    combined = ""
    for md_file in sorted(DOCUMENTS_PATH.glob("*.md")):
        combined += md_file.read_text(encoding="utf-8")
    return hashlib.md5(combined.encode()).hexdigest()


def is_changed() -> bool:
    """比對目前文件的 hash 和上次 ingest 時的 hash，判斷是否需要重新 ingest。"""
    if not HASH_FILE.exists():
        return True
    return HASH_FILE.read_text().strip() != _compute_hash()


def ingest(force: bool = False) -> bool:
    """
    讀取文件、向量化並存入 ChromaDB。

    Args:
        force: 強制重新 ingest，忽略 hash 比對

    Returns:
        True = 有執行 ingest；False = 文件未異動，略過
    """
    if not force and not is_changed():
        print("✅ 文件未異動，略過 ingest。")
        return False

    print(f"📂 讀取文件：{DOCUMENTS_PATH}")
    md_files = list(DOCUMENTS_PATH.glob("*.md"))
    if not md_files:
        print("⚠️  找不到任何 .md 文件，請確認 rag/documents/ 資料夾。")
        return False

    # 切段
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=HEADERS_TO_SPLIT,
        strip_headers=False,
    )

    all_docs = []
    for md_file in md_files:
        print(f"   處理：{md_file.name}")
        text    = md_file.read_text(encoding="utf-8")
        chunks  = splitter.split_text(text)

        # 在 metadata 加入來源文件名稱，查詢時顯示給使用者
        source_name = {
            "procurement_policy.md": "採購規範",
            "product_catalog.md":    "商品目錄",
            "user_guide.md":         "系統使用說明",
        }.get(md_file.name, md_file.stem)

        for chunk in chunks:
            chunk.metadata["source"] = source_name
        all_docs.extend(chunks)

    print(f"\n✂️  共切出 {len(all_docs)} 個段落，開始向量化...")

    # 清除舊的向量資料庫，重新建立
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    if CHROMA_PATH.exists():
        import shutil
        # 只清除 chroma 的資料檔，保留 HASH_FILE
        for item in CHROMA_PATH.iterdir():
            if item.name != HASH_FILE.name:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

    Chroma.from_documents(
        documents=all_docs,
        embedding=OpenAIEmbeddings(model="text-embedding-3-small"),
        persist_directory=str(CHROMA_PATH),
    )

    # 儲存這次的 hash
    HASH_FILE.write_text(_compute_hash())

    print(f"✅ Ingest 完成：{len(all_docs)} 個段落已存入 {CHROMA_PATH}")
    return True


if __name__ == "__main__":
    force = "--force" in sys.argv
    ingest(force=force)
