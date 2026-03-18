"""
routes/procure.py

採購相關的 API endpoints。
input 為純自然語言，意圖解析由 agent 內部處理。
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.agent_runner import run_agent_stream

router = APIRouter(prefix="/api", tags=["procurement"])


class ProcureRequest(BaseModel):
    message: str = Field(
        description="使用者的自然語言採購需求",
        examples=["我需要幫部門買一些滑鼠，大概五個左右，預算有限"]
    )
    budget: int = Field(
        default=500,
        description="採購預算上限（單位：元）",
        gt=0
    )


@router.post(
    "/procure",
    summary="送出採購需求",
    description=(
        "接收自然語言採購請求，透過 LangGraph agent 自動解析意圖、查詢價格、"
        "進行預算審核並下單。以 Server-Sent Events (SSE) 串流回傳每個執行步驟。"
    ),
)
async def procure(request: ProcureRequest):
    return StreamingResponse(
        run_agent_stream(request.message, request.budget),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # 避免 nginx 緩衝 SSE
        },
    )


@router.get("/health", summary="健康檢查")
async def health():
    return {"status": "ok"}
