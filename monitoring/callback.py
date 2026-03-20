"""
monitoring/callback.py

CostTracker：繼承 LangChain BaseCallbackHandler，
在不修改任何 agent 邏輯的前提下，攔截每次 LLM 呼叫的 token 用量與延遲。

GPT-4o 計費單價（2024）：
  Input:  $2.50 / 1M tokens
  Output: $10.00 / 1M tokens
"""
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from monitoring.storage import init_db, insert_llm_call, insert_run

# GPT-4o 單價（每 token 的美元價格）
PRICE_INPUT_PER_TOKEN  = 2.50  / 1_000_000
PRICE_OUTPUT_PER_TOKEN = 10.00 / 1_000_000


class CostTracker(BaseCallbackHandler):
    """
    攔截 LangGraph 執行過程中的 LLM 呼叫，即時計算 token 用量與費用，
    任務結束時將彙總數據寫入 SQLite。

    使用方式（在 agent_runner.py 注入）：
        tracker = CostTracker(run_id=..., input_message=..., budget=...)
        await app.astream(inputs, config={"callbacks": [tracker]})
    """

    def __init__(self, run_id: str, input_message: str, budget: int):
        super().__init__()
        init_db()   # 確保資料表存在

        self.run_id        = run_id
        self.input_message = input_message
        self.budget        = budget

        # 任務開始時間（用來算端對端 latency）
        self._task_start   = time.monotonic()

        # 單次 LLM 呼叫的開始時間（on_llm_start 設定，on_llm_end 使用）
        self._call_start: float | None = None

        # 累計數據
        self._call_sequence   = 0
        self._total_input_tok = 0
        self._total_output_tok = 0
        self._total_cost      = 0.0

        # 節點執行路徑（依序記錄每個步驟的類型）
        self._node_path: list[str] = []

    # ──────────────────────────────────────────
    # LLM 呼叫 hooks
    # ──────────────────────────────────────────

    def on_llm_start(self, serialized: dict, prompts: list, **kwargs) -> None:
        """LLM 開始執行時記錄開始時間。"""
        self._call_start = time.monotonic()
        self._node_path.append("llm_call")

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """LLM 執行完成時，計算 token 用量、費用、latency，寫入 llm_calls。"""
        latency_ms = int((time.monotonic() - self._call_start) * 1000) if self._call_start else 0
        self._call_start = None
        self._call_sequence += 1

        # 從 response 取得 token 用量
        usage = {}
        if response.generations and response.llm_output:
            usage = response.llm_output.get("token_usage", {})

        input_tokens  = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost          = (input_tokens  * PRICE_INPUT_PER_TOKEN +
                         output_tokens * PRICE_OUTPUT_PER_TOKEN)

        # 累加到任務總計
        self._total_input_tok  += input_tokens
        self._total_output_tok += output_tokens
        self._total_cost       += cost

        insert_llm_call({
            "run_id":        self.run_id,
            "node_name":     "agent",
            "sequence":      self._call_sequence,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "cost_usd":      round(cost, 8),
            "latency_ms":    latency_ms,
        })

    def on_llm_error(self, error: Exception, **kwargs) -> None:
        """LLM 發生錯誤時重置計時器。"""
        self._call_start = None

    # ──────────────────────────────────────────
    # 節點路徑追蹤 hooks
    # ──────────────────────────────────────────

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs) -> None:
        """工具開始執行。"""
        tool_name = serialized.get("name", "unknown_tool")
        self._node_path.append(f"tool:{tool_name}")

    # ──────────────────────────────────────────
    # 任務結束：彙總寫入 runs
    # ──────────────────────────────────────────

    def finalize(self, revision_count: int, status: str) -> None:
        """
        任務結束時由 agent_runner 主動呼叫，寫入任務彙總紀錄。

        Args:
            revision_count: 被 compliance 攔截並修正的次數
            status: 'success' | 'intercepted' | 'error'
        """
        total_latency_ms = int((time.monotonic() - self._task_start) * 1000)

        insert_run({
            "run_id":               self.run_id,
            "timestamp":            datetime.now(timezone.utc).isoformat(),
            "input_message":        self.input_message,
            "budget":               self.budget,
            "status":               status,
            "revision_count":       revision_count,
            "total_input_tokens":   self._total_input_tok,
            "total_output_tokens":  self._total_output_tok,
            "total_cost_usd":       round(self._total_cost, 8),
            "total_latency_ms":     total_latency_ms,
        })
