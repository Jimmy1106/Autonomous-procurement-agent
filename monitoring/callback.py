"""
monitoring/callback.py

CostTracker：繼承 LangChain BaseCallbackHandler，
在不修改任何 agent 邏輯的前提下，攔截每次 LLM 呼叫的 token 用量與延遲，
同時追蹤採購金額明細（查價結果、原始下單、最終下單）。

GPT-4o 計費單價（2024）：
  Input:  $2.50 / 1M tokens
  Output: $10.00 / 1M tokens

採購金額的擷取策略：
  - place_order 的參數從 on_llm_end 的 response.generations 讀取
    （在 compliance 攔截之前，能捕捉到原始的超預算方案）
  - check_item_price 的結果從 on_tool_end 讀取
    （工具實際執行後才有回傳值）
"""
import time
from datetime import datetime, timezone

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from monitoring.storage import init_db, insert_llm_call, insert_run

PRICE_INPUT_PER_TOKEN  = 2.50  / 1_000_000
PRICE_OUTPUT_PER_TOKEN = 10.00 / 1_000_000

_TOOL_REASON_MAP = {
    "check_item_price": "查詢商品價格",
    "place_order":      "執行下單",
}


def _get_tool_calls(response: LLMResult) -> list:
    """從 LLMResult 取出 tool_calls 清單（若無則回傳空串列）。"""
    try:
        gen = response.generations[0][0]
        msg = getattr(gen, "message", None)
        if msg and hasattr(msg, "tool_calls") and msg.tool_calls:
            return msg.tool_calls
    except Exception:
        pass
    return []


def _detect_call_reason(tool_calls: list, prev_was_compliance_error: bool) -> str:
    """依 tool_calls 判斷這次 LLM 呼叫的原因。"""
    if not tool_calls:
        return "產出最終回應"
    tool_name = tool_calls[0].get("name", "")
    if tool_name == "place_order" and prev_was_compliance_error:
        return "修正下單"
    return _TOOL_REASON_MAP.get(tool_name, tool_name)


class CostTracker(BaseCallbackHandler):

    def __init__(self, run_id: str, input_message: str, budget: int):
        super().__init__()
        init_db()

        self.run_id        = run_id
        self.input_message = input_message
        self.budget        = budget

        self._task_start               = time.monotonic()
        self._call_start: float | None = None

        # LLM 累計
        self._call_sequence             = 0
        self._total_input_tok           = 0
        self._total_output_tok          = 0
        self._total_cost                = 0.0
        self._prev_was_compliance_error = False

        # 採購金額追蹤
        self._item_price        = None
        self._original_quantity = None   # 第一次 place_order 的數量（可能超預算）
        self._original_total    = None
        self._final_quantity    = None   # 最後一次 place_order 的數量（最終成交）
        self._final_total       = None

    # ──────────────────────────────────────────
    # LLM hooks
    # ──────────────────────────────────────────

    def on_llm_start(self, serialized: dict, prompts: list, **kwargs) -> None:
        self._call_start = time.monotonic()

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        latency_ms = int((time.monotonic() - self._call_start) * 1000) if self._call_start else 0
        self._call_start = None
        self._call_sequence += 1

        # Token 與費用
        usage = response.llm_output.get("token_usage", {}) if response.llm_output else {}
        input_tokens  = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost = input_tokens * PRICE_INPUT_PER_TOKEN + output_tokens * PRICE_OUTPUT_PER_TOKEN

        self._total_input_tok  += input_tokens
        self._total_output_tok += output_tokens
        self._total_cost       += cost

        # 採購金額：從 tool_calls 讀取 place_order 的參數
        # 這裡在 compliance 攔截之前發生，所以能捕捉到原始的超預算方案
        tool_calls = _get_tool_calls(response)
        for tc in tool_calls:
            if tc.get("name") == "place_order":
                args  = tc.get("args", {})
                qty   = args.get("quantity", 0)
                total = args.get("total_price", 0)
                if self._original_quantity is None:
                    # 第一次呼叫 place_order = 原始方案
                    self._original_quantity = qty
                    self._original_total    = total
                # 每次都更新 final，最後一次就是最終成交方案
                self._final_quantity = qty
                self._final_total    = total
                # 從 total / quantity 反推單價（比依賴 on_tool_end 更可靠）
                if qty and total and self._item_price is None:
                    self._item_price = total // qty

        call_reason = _detect_call_reason(tool_calls, self._prev_was_compliance_error)
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

    # ──────────────────────────────────────────
    # Tool hooks
    # ──────────────────────────────────────────

    def on_tool_end(self, output, **kwargs) -> None:
        """
        工具執行完成後的 hook。
        - check_item_price 回傳單價數字 → 記錄 item_price
        - compliance error → 設旗標，讓下一次 LLM 呼叫標記為「修正下單」
        """
        output_str = str(output).strip()

        if "COMPLIANCE_ERROR" in output_str:
            self._prev_was_compliance_error = True
        else:
            # check_item_price 回傳純數字（例如 "120"）
            try:
                self._item_price = int(output_str)
            except ValueError:
                pass  # place_order 的回傳是文字，不是數字，略過

    # ──────────────────────────────────────────
    # 任務結束
    # ──────────────────────────────────────────

    def finalize(self, revision_count: int, status: str) -> None:
        total_latency_ms = int((time.monotonic() - self._task_start) * 1000)

        insert_run({
            "run_id":               self.run_id,
            "timestamp":            datetime.now(timezone.utc).isoformat(),
            "input_message":        self.input_message,
            "budget":               self.budget,
            "status":               status,
            "revision_count":       revision_count,
            "item_price":           self._item_price,
            "original_quantity":    self._original_quantity,
            "original_total":       self._original_total,
            "final_quantity":       self._final_quantity,
            "final_total":          self._final_total,
            "total_input_tokens":   self._total_input_tok,
            "total_output_tokens":  self._total_output_tok,
            "total_cost_usd":       round(self._total_cost, 8),
            "total_latency_ms":     total_latency_ms,
        })
