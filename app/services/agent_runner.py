"""
agent_runner.py

負責：接收自然語言輸入 → 執行 LangGraph agent → 以 async generator yield 每個 step。

FastAPI route 和 Streamlit 都從這裡取用執行邏輯，
不重複實作、也不依賴 HTTP 層的細節。
"""
import json
from typing import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import build_graph

# 每次呼叫都 build 一個新的 graph instance
# 未來若改為有 memory 的版本，可在此注入 checkpointer
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

    inputs = {
        "messages": [HumanMessage(content=message)],
        "revision_count": 0,
        "budget": budget,
    }

    final_event = None

    async for event in app.astream(inputs, stream_mode="values"):
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
                # 只取第一行（標題），避免把整段指令都吐給前端
                first_line = msg.content.split("\n")[0]
                yield _sse({"type": "compliance_error", "content": first_line})
            else:
                yield _sse({"type": "tool_result", "content": msg.content})

    # 最後送出 done 事件，附上修正次數
    if final_event:
        final_msg = final_event["messages"][-1]
        yield _sse({
            "type": "done",
            "content": final_msg.content if hasattr(final_msg, "content") else "",
            "revision_count": final_event.get("revision_count", 0),
        })


def _sse(payload: dict) -> str:
    """將 dict 序列化為 SSE data 格式的單行字串。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
