"""
agent_runner.py

負責：接收自然語言輸入 → 執行 LangGraph agent → 以 async generator yield 每個 step。

FastAPI route 和 Streamlit 都從這裡取用執行邏輯，
不重複實作、也不依賴 HTTP 層的細節。
"""
import json
import uuid
from typing import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from core.graph import build_graph
from monitoring.callback import CostTracker

_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def run_agent_stream(message: str, budget: int) -> AsyncGenerator[str, None]:
    """
    接收自然語言採購需求，執行 agent，以 SSE 格式逐步 yield 每個 step 的事件。

    每個 yield 都是一行 JSON 字串，格式：
    {
        "type": "tool_call" | "compliance_error" | "tool_result" | "agent_reply" | "done",
        "content": str,
        "revision_count": int   # 僅 done 事件包含
    }
    """
    app = _get_graph()

    # 每次任務產生唯一 run_id，貫穿整個執行過程
    run_id = str(uuid.uuid4())
    tracker = CostTracker(run_id=run_id, input_message=message, budget=budget)

    inputs = {
        "messages": [HumanMessage(content=message)],
        "revision_count": 0,
        "budget": budget,
    }

    final_event = None
    status = "success"

    try:
        async for event in app.astream(
            inputs,
            stream_mode="values",
            config={"callbacks": [tracker]},   # ← 注入 CostTracker
        ):
            final_event = event

            if "messages" not in event:
                continue

            msg = event["messages"][-1]

            if isinstance(msg, AIMessage):
                if msg.tool_calls:
                    tool_name = msg.tool_calls[0]["name"]
                    tool_args = msg.tool_calls[0]["args"]
                    yield _sse({"type": "tool_call", "content": f"呼叫工具：{tool_name}，參數：{tool_args}"})

                elif msg.content:
                    yield _sse({"type": "agent_reply", "content": msg.content})

            elif isinstance(msg, ToolMessage):
                if "COMPLIANCE_ERROR" in msg.content:
                    first_line = msg.content.split("\n")[0]
                    yield _sse({"type": "compliance_error", "content": first_line})
                    status = "intercepted"
                else:
                    yield _sse({"type": "tool_result", "content": msg.content})

    except Exception as e:
        status = "error"
        tracker.finalize(revision_count=0, status=status)
        yield _sse({"type": "error", "content": str(e)})
        return

    # 任務結束：送出 done 事件，同時讓 tracker 寫入彙總紀錄
    if final_event:
        revision_count = final_event.get("revision_count", 0)
        final_msg = final_event["messages"][-1]

        # 有被攔截但最終成功，status 記為 intercepted（已修正並成功下單）
        tracker.finalize(revision_count=revision_count, status=status)

        yield _sse({
            "type": "done",
            "content": final_msg.content if hasattr(final_msg, "content") else "",
            "revision_count": revision_count,
            "run_id": run_id,   # 傳給前端，未來可用來查詢該次任務的明細
        })


def _sse(payload: dict) -> str:
    """將 dict 序列化為 SSE data 格式的單行字串。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
