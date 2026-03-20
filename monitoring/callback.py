"""
monitoring/callback.py

CostTracker：繼承 LangChain BaseCallbackHandler，
在不修改任何 agent 邏輯的前提下，攔截每次 LLM 呼叫的 token 用量與延遲。

GPT-4o 計費單價（2024）：
  Input:  $2.50 / 1M tokens
  Output: $10.00 / 1M tokens
"""
import time
from datetime import datetime, timezone

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from monitoring.storage import init_db, insert_llm_call, insert_run

PRICE_INPUT_PER_TOKEN  = 2.50  / 1_000_000
PRICE_OUTPUT_PER_TOKEN = 10.00 / 1_000_000

# 呼叫原因對照：從 response 的 tool_calls 判斷這次 LLM 在做什麼
_TOOL_REASON_MAP = {
    "check_item_price": "查詢商品價格",
    "place_order":      "執行下單",
}


def _detect_call_reason(response: LLMResult, sequence: int, prev_was_compliance_error: bool) -> str:
    """
    從 LLMResult 判斷這次 LLM 呼叫的原因：
    - 有 tool_calls → 依工具名稱對應
    - 沒有 tool_calls，但前一次有 compliance error → 修正下單計算
    - 沒有 tool_calls，且不是修正 → 產出最終回應
    """
    try:
        generations = response.generations
        if generations and generations[0]:
            gen = generations[0][0]
            # ChatGeneration 有 message 屬性（AIMessage）
            msg = getattr(gen, "message", None)
            if msg and hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_name = msg.tool_calls[0].get("name", "")
                if tool_name in _TOOL_REASON_MAP:
                    # 若是 place_order 且前一次被攔截，標記為修正下單
                    if tool_name == "place_order" and prev_was_compliance_error:
                        return "修正下單"
                    return _TOOL_REASON_MAP[tool_name]
    except Exception:
        pass

    return "產出最終回應"


class CostTracker(BaseCallbackHandler):
    """
    攔截 LangGraph 執行過程中的 LLM 呼叫，即時計算 token 用量與費用，
    任務結束時將彙總數據寫入 SQLite。
    """

    def __init__(self, run_id: str, input_message: str, budget: int):
        super().__init__()
        init_db()

        self.run_id        = run_id
        self.input_message = input_message
        self.budget        = budget

        self._task_start   = time.monotonic()
        self._call_start: float | None = None

        self._call_sequence            = 0
        self._total_input_tok          = 0
        self._total_output_tok         = 0
        self._total_cost               = 0.0
        self._prev_was_compliance_error = False  # 追蹤上一次是否被 compliance 攔截

    def on_llm_start(self, serialized: dict, prompts: list, **kwargs) -> None:
        self._call_start = time.monotonic()

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        latency_ms = int((time.monotonic() - self._call_start) * 1000) if self._call_start else 0
        self._call_start = None
        self._call_sequence += 1

        usage = {}
        if response.llm_output:
            usage = response.llm_output.get("token_usage", {})

        input_tokens  = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost          = (input_tokens  * PRICE_INPUT_PER_TOKEN +
                         output_tokens * PRICE_OUTPUT_PER_TOKEN)

        self._total_input_tok  += input_tokens
        self._total_output_tok += output_tokens
        self._total_cost       += cost

        call_reason = _detect_call_reason(
            response,
            self._call_sequence,
            self._prev_was_compliance_error,
        )
        # 呼叫完成後重置 compliance error 旗標
        self._prev_was_compliance_error = False

        insert_llm_call({
            "run_id":        self.run_id,
            "node_name":     "agent",
            "sequence":      self._call_sequence,
            "call_reason":   call_reason,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "cost_usd":      round(cost, 8),
            "latency_ms":    latency_ms,
        })

    def on_llm_error(self, error: Exception, **kwargs) -> None:
        self._call_start = None

    def on_tool_end(self, output: str, **kwargs) -> None:
        """工具執行完成：若是 compliance error，設旗標讓下一次 LLM 呼叫標記為「修正下單」。"""
        if isinstance(output, str) and "COMPLIANCE_ERROR" in output:
            self._prev_was_compliance_error = True

    def finalize(self, revision_count: int, status: str) -> None:
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
