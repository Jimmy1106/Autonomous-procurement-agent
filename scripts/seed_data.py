"""
seed_data.py

插入一批上週的模擬採購任務資料，讓監控頁面的「與上週同期比較」可以正常呈現。
執行一次即可。

執行方式：
    python seed_data.py
"""
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from monitoring.storage import init_db, insert_llm_call, insert_run

# ──────────────────────────────────────────────
# 模擬情境
# ──────────────────────────────────────────────
SEED_COUNT = 20

SCENARIOS = [
    # (input_message,                budget, item_price, req_qty)
    ("我要買 3 個滑鼠",              500,  120, 3),   # 合規
    ("幫我買 5 個 Pro Mouse",        500,  120, 5),   # 超預算 → 修正為 4 個
    ("我需要 2 個無線滑鼠",          500,  120, 2),   # 合規
    ("採購 10 個滑鼠",               500,  120, 10),  # 超預算 → 修正為 4 個
    ("幫部門買 4 個滑鼠",            500,  120, 4),   # 合規，剛好壓線
    ("我要買 1 個滑鼠",              500,  120, 1),   # 合規
    ("請幫我採購 6 個 Mouse",        500,  120, 6),   # 超預算 → 修正為 4 個
    ("買 2 個辦公用滑鼠",            300,  120, 2),   # 合規
    ("需要 3 個會議室用滑鼠",        300,  120, 3),   # 超預算 → 修正為 2 個
    ("採購 5 個無線鍵盤",            500,   50, 5),   # 合規
]

TZ_UTC = timezone.utc


def _make_timestamp(days_ago: float) -> str:
    """產生指定天數前的隨機時間點（UTC ISO 字串）。"""
    now = datetime.now(TZ_UTC)
    dt  = now - timedelta(
        days=int(days_ago),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    return dt.replace(second=0, microsecond=0).isoformat()


def _build_run(scenario: tuple, days_ago: float) -> tuple[dict, list[dict]]:
    """依情境產生一筆任務與對應的 LLM 呼叫明細。"""
    msg, budget, item_price, req_qty = scenario

    original_total = item_price * req_qty
    is_over        = original_total > budget

    if is_over:
        final_qty      = budget // item_price
        final_total    = item_price * final_qty
        status         = "intercepted"
        revision_count = 1
        call_reasons   = ["查詢商品價格", "執行下單", "修正下單", "產出最終回應"]
    else:
        final_qty      = req_qty
        final_total    = original_total
        status         = "success"
        revision_count = 0
        call_reasons   = ["查詢商品價格", "執行下單", "產出最終回應"]

    # token / 費用
    total_input  = sum(random.randint(800, 1400) for _ in call_reasons)
    total_output = sum(random.randint(150, 350)  for _ in call_reasons)
    total_cost   = (total_input  * 2.50 / 1_000_000 +
                    total_output * 10.00 / 1_000_000)

    run_id = str(uuid.uuid4())

    run = {
        "run_id":               run_id,
        "timestamp":            _make_timestamp(days_ago),
        "input_message":        msg,
        "budget":               budget,
        "status":               status,
        "revision_count":       revision_count,
        "item_price":           item_price,
        "original_quantity":    req_qty,
        "original_total":       original_total,
        "final_quantity":       final_qty,
        "final_total":          final_total,
        "total_input_tokens":   total_input,
        "total_output_tokens":  total_output,
        "total_cost_usd":       round(total_cost, 8),
        "total_latency_ms":     random.randint(1800, 4500),
    }

    llm_calls = [
        {
            "run_id":        run_id,
            "node_name":     "agent",
            "sequence":      i + 1,
            "call_reason":   reason,
            "input_tokens":  random.randint(800, 1400),
            "output_tokens": random.randint(150, 350),
            "cost_usd":      round(
                random.randint(800, 1400) * 2.50 / 1_000_000 +
                random.randint(150, 350) * 10.00 / 1_000_000, 8
            ),
            "latency_ms":    random.randint(400, 1500),
        }
        for i, reason in enumerate(call_reasons)
    ]

    return run, llm_calls


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────
def seed():
    random.seed(42)   # 固定 seed，讓每次執行結果一致
    init_db()

    print(f"插入 {SEED_COUNT} 筆上週模擬資料...\n")

    for i in range(SEED_COUNT):
        days_ago         = random.uniform(7, 14)   # 上週 7~14 天前
        scenario         = SCENARIOS[i % len(SCENARIOS)]
        run, llm_calls   = _build_run(scenario, days_ago)

        insert_run(run)
        for call in llm_calls:
            insert_llm_call(call)

        icon = "✅" if run["status"] == "success" else "⚠️"
        print(f"  {icon} [{i+1:02d}] {run['input_message']:<28} "
              f"status={run['status']:<12} "
              f"revision={run['revision_count']}  "
              f"cost=${run['total_cost_usd']:.6f}")

    print(f"\n✅ 完成：插入 {SEED_COUNT} 筆任務")
    print("監控頁面選「近 7 天」可看本週資料；「近 30 天」可同時看到上週模擬資料。")
    print("「與上週同期比較」在選「近 7 天」時會自動計算上週同期的比較結果。")


if __name__ == "__main__":
    seed()
