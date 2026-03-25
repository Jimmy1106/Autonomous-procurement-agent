"""
app/main.py

FastAPI 應用程式進入點。
啟動指令：uvicorn api.main:app --reload --port 8000
"""
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from api.routes.procure import router as procure_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服務啟動時：預先 compile graph，並在文件有異動時自動重新 ingest。"""
    # RAG：偵測文件異動，有變更才重新 ingest（幾乎不花時間）
    try:
        from rag.ingest import ingest, is_changed
        if is_changed():
            print("📚 偵測到文件異動，自動重新建立知識庫...")
            ingest()
        else:
            print("✅ 知識庫已是最新版本。")
    except Exception as e:
        print(f"⚠️  RAG ingest 失敗（服務仍可正常啟動）：{e}")

    # Graph：預先 compile，避免第一個 request 有冷啟動延遲
    from api.services.agent_runner import _get_graph
    _get_graph()
    print("✅ LangGraph compiled and ready.")
    yield


app = FastAPI(
    title="Autonomous Procurement Agent API",
    description=(
        "以自然語言驅動的自主採購代理人。"
        "使用者輸入模糊需求，agent 自動解析意圖、查詢價格、審核預算並下單。"
        "支援採購規範、商品目錄與系統說明的知識庫查詢（RAG）。"
    ),
    version="0.3.0",
    lifespan=lifespan,
)

# CORS：開發環境允許所有來源，上線時改為指定前端 domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(procure_router)
