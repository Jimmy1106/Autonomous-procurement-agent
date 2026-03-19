"""
app/main.py

FastAPI 應用程式進入點。
啟動指令：uvicorn app.main:app --reload --port 8000
"""
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from api.routes.procure import router as procure_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服務啟動時預先 build graph，避免第一個 request 有冷啟動延遲。"""
    from api.services.agent_runner import _get_graph
    _get_graph()
    print("✅ LangGraph compiled and ready.")
    yield


app = FastAPI(
    title="Autonomous Procurement Agent API",
    description=(
        "以自然語言驅動的自主採購代理人。"
        "使用者輸入模糊需求，agent 自動解析意圖、查詢價格、審核預算並下單。"
    ),
    version="0.2.0",
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
