"""
frontend/pages/monitor.py

LLM 監控頁面：顯示 token 用量、成本、latency、節點執行路徑、revision_count 分布。
Streamlit 多頁面機制：放在 pages/ 資料夾會自動出現在側邊欄。
"""

import sys
from pathlib import Path

# 確保在 Docker 和本機環境都能正確 import monitoring 模組
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from monitoring.storage import (
    get_llm_calls_by_run,
    get_recent_runs,
    get_revision_distribution,
    get_status_distribution,
    get_summary_stats,
    init_db,
)

# ──────────────────────────────────────────────
# 頁面設定
# ──────────────────────────────────────────────
st.set_page_config(page_title="LLM 監控", page_icon="📊", layout="wide")
st.title("📊 LLM 監控儀表板")
st.caption("即時追蹤 token 用量、API 成本、執行延遲與 Agent 行為分析。")

init_db()

# 自動重新整理
col_refresh, col_auto = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 重新整理"):
        st.rerun()
with col_auto:
    auto_refresh = st.checkbox("每 10 秒自動更新", value=False)
if auto_refresh:
    import time
    time.sleep(10)
    st.rerun()

st.divider()

# ──────────────────────────────────────────────
# 頂部：全域統計 Metrics
# ──────────────────────────────────────────────
stats = get_summary_stats()

if not stats or stats.get("total_runs") == 0:
    st.info("尚無資料。請先在採購頁面送出一筆需求，數據會自動出現在這裡。")
    st.stop()

st.subheader("📈 累計總覽")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("總任務數",       stats.get("total_runs", 0))
c2.metric("Input Tokens",  f"{stats.get('total_input_tokens', 0):,}")
c3.metric("Output Tokens", f"{stats.get('total_output_tokens', 0):,}")
c4.metric("累計費用 (USD)", f"${stats.get('total_cost_usd', 0):.6f}")
c5.metric("平均 Latency",  f"{int(stats.get('avg_latency_ms', 0))} ms")
c6.metric("平均修正次數",   f"{stats.get('avg_revision_count', 0):.2f}")

st.divider()

# ──────────────────────────────────────────────
# 中部：兩欄圖表
# ──────────────────────────────────────────────
left, right = st.columns(2)

# 左：revision_count 分布長條圖
with left:
    st.subheader("🔄 自動修正次數分布")
    rev_data = get_revision_distribution()
    if rev_data:
        df_rev = pd.DataFrame(rev_data)
        df_rev["revision_count"] = df_rev["revision_count"].astype(str) + " 次"
        df_rev = df_rev.set_index("revision_count")
        st.bar_chart(df_rev["count"])
        st.caption("修正 0 次 = 一次通過；≥1 次 = 被 Compliance 攔截並自動修正")
    else:
        st.info("尚無資料")

# 右：任務狀態分布圓餅圖（用 dataframe 代替，Streamlit 原生不支援圓餅）
with right:
    st.subheader("✅ 任務結果分布")
    status_data = get_status_distribution()
    if status_data:
        df_status = pd.DataFrame(status_data).set_index("status")

        # 用顏色區分狀態
        status_labels = {
            "success":     "✅ 成功",
            "intercepted": "⚠️ 攔截後修正",
            "error":       "❌ 錯誤",
        }
        df_status.index = [status_labels.get(s, s) for s in df_status.index]
        st.bar_chart(df_status["count"])
    else:
        st.info("尚無資料")

st.divider()

# ──────────────────────────────────────────────
# 下部：最近任務列表 + 展開明細
# ──────────────────────────────────────────────
st.subheader("🕐 最近任務紀錄")

runs = get_recent_runs(limit=20)
if not runs:
    st.info("尚無任務紀錄")
    st.stop()

# 格式化顯示
df_runs = pd.DataFrame(runs)
df_runs["timestamp"] = pd.to_datetime(df_runs["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
df_runs["total_cost_usd"] = df_runs["total_cost_usd"].apply(lambda x: f"${x:.6f}")
df_runs["total_latency_ms"] = df_runs["total_latency_ms"].apply(lambda x: f"{x} ms")

display_cols = {
    "timestamp":            "時間",
    "input_message":        "輸入需求",
    "budget":               "預算",
    "status":               "結果",
    "revision_count":       "修正次數",
    "total_input_tokens":   "Input Tokens",
    "total_output_tokens":  "Output Tokens",
    "total_cost_usd":       "費用 (USD)",
    "total_latency_ms":     "總延遲",
}
st.dataframe(
    df_runs[list(display_cols.keys())].rename(columns=display_cols),
    use_container_width=True,
    hide_index=True,
)

st.divider()

# ──────────────────────────────────────────────
# 單次任務明細：節點執行路徑 + 每次 LLM 呼叫
# ──────────────────────────────────────────────
st.subheader("🔍 單次任務 LLM 呼叫明細")

run_options = {f"{r['timestamp']}  |  {r['input_message'][:30]}...": r["run_id"] for r in runs}
selected_label = st.selectbox("選擇要查看的任務：", list(run_options.keys()))
selected_run_id = run_options[selected_label]

llm_calls = get_llm_calls_by_run(selected_run_id)

if not llm_calls:
    st.info("此任務無 LLM 呼叫明細（可能是舊版本未啟用監控）")
else:
    df_calls = pd.DataFrame(llm_calls)
    df_calls["cost_usd"] = df_calls["cost_usd"].apply(lambda x: f"${x:.8f}")
    df_calls["latency_ms"] = df_calls["latency_ms"].apply(lambda x: f"{x} ms")

    display_call_cols = {
        "sequence":      "第幾次呼叫",
        "node_name":     "節點",
        "input_tokens":  "Input Tokens",
        "output_tokens": "Output Tokens",
        "cost_usd":      "費用 (USD)",
        "latency_ms":    "延遲",
    }
    st.dataframe(
        df_calls[list(display_call_cols.keys())].rename(columns=display_call_cols),
        use_container_width=True,
        hide_index=True,
    )

    # 節點執行路徑視覺化
    st.subheader("🗺️ 節點執行路徑")
    selected_run = next(r for r in runs if r["run_id"] == selected_run_id)
    revision_count = selected_run["revision_count"]

    # 根據 revision_count 還原路徑
    base_path = ["▶ START", "🤖 agent", "🔍 compliance", "🔧 tools", "🤖 agent"]
    if revision_count > 0:
        intercept_steps = []
        for _ in range(revision_count):
            intercept_steps += ["❌ compliance 攔截", "🤖 agent 重新推理"]
        path = (["▶ START", "🤖 agent", "🔍 compliance"]
                + intercept_steps
                + ["🔍 compliance 通過", "🔧 tools", "🤖 agent", "⏹ END"])
    else:
        path = ["▶ START", "🤖 agent", "🔍 compliance 通過", "🔧 tools", "🤖 agent", "⏹ END"]

    st.markdown(" → ".join(path))
