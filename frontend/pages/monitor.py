"""
frontend/pages/monitor.py

LLM 監控儀表板：
- 子分頁：總覽 / 任務紀錄與明細
- 台灣時間顯示
- 時間篩選器（今日 / 近 7 天 / 近 30 天 / 自訂）
- 與上週同期比較分析
- LLM 呼叫次數統計
- 呼叫原因明細
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from monitoring.storage import (
    get_llm_calls_by_run,
    get_revision_distribution,
    get_runs_by_date_range,
    get_status_distribution,
    get_summary_stats,
    init_db,
)

# ──────────────────────────────────────────────
# 工具函式
# ──────────────────────────────────────────────
TZ_TAIPEI = timezone(timedelta(hours=8))


def to_taipei(utc_str: str) -> datetime:
    dt = datetime.fromisoformat(utc_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_TAIPEI)


def now_taipei() -> datetime:
    return datetime.now(TZ_TAIPEI)


def taipei_to_utc_range(start: datetime, end: datetime) -> tuple[str, str]:
    return (
        start.astimezone(timezone.utc).isoformat(),
        end.astimezone(timezone.utc).isoformat(),
    )


def delta_arrow(current, previous) -> str:
    """回傳文字格式的漲跌幅（供比較表格用）。"""
    if not previous or previous == 0:
        return ""
    pct = (current - previous) / previous * 100
    arrow = "▲" if pct > 0 else "▼"
    return f"{arrow} {abs(pct):.1f}% vs 上週同期"


def delta_pct(current, previous) -> str | None:
    """
    回傳帶正負號的 % 字串（供 st.metric delta 參數用）。
    傳字串時 Streamlit 依正負號決定顏色，搭配 delta_color 可正確顯示。
    """
    if not previous or previous == 0:
        return None
    pct = (current - previous) / previous * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


# ──────────────────────────────────────────────
# 頁面設定
# ──────────────────────────────────────────────
st.set_page_config(page_title="LLM 監控", page_icon="📊", layout="wide")
st.title("📊 LLM 監控儀表板")
st.caption("即時追蹤 token 用量、API 成本、執行延遲與 Agent 行為分析。")

init_db()

# ──────────────────────────────────────────────
# Sidebar：時間篩選器
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("⏱️ 時間範圍")

    period = st.radio(
        "快速選擇",
        ["今日", "近 7 天", "近 30 天", "自訂日期"],
        index=1,
    )

    now = now_taipei()

    if period == "今日":
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt   = now
    elif period == "近 7 天":
        start_dt = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt   = now
    elif period == "近 30 天":
        start_dt = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt   = now
    else:
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("開始日期", value=(now - timedelta(days=7)).date())
        with col2:
            end_date = st.date_input("結束日期", value=now.date())
        start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=TZ_TAIPEI)
        end_dt   = datetime(end_date.year, end_date.month, end_date.day,
                            hour=23, minute=59, second=59, tzinfo=TZ_TAIPEI)

    days_in_range = max((end_dt - start_dt).days + 1, 1)
    prev_end_dt   = start_dt - timedelta(seconds=1)
    prev_start_dt = (prev_end_dt - timedelta(days=days_in_range - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    st.divider()
    st.caption(f"📅 {start_dt.strftime('%Y/%m/%d')} ～ {end_dt.strftime('%Y/%m/%d')}")
    st.caption(f"🔁 比較期間：{prev_start_dt.strftime('%m/%d')} ～ {prev_end_dt.strftime('%m/%d')}")

    st.divider()
    if st.button("🔄 重新整理"):
        st.rerun()
    if st.checkbox("每 30 秒自動更新"):
        import time
        time.sleep(30)
        st.rerun()

# ──────────────────────────────────────────────
# 取得資料
# ──────────────────────────────────────────────
start_utc, end_utc           = taipei_to_utc_range(start_dt, end_dt)
prev_start_utc, prev_end_utc = taipei_to_utc_range(prev_start_dt, prev_end_dt)

stats      = get_summary_stats(start_utc, end_utc)
prev_stats = get_summary_stats(prev_start_utc, prev_end_utc)

if not stats or stats.get("total_runs") == 0:
    st.info("選取的時間區間內尚無資料。請先在採購頁面送出需求，或調整時間範圍。")
    st.stop()

# ──────────────────────────────────────────────
# 子分頁
# ──────────────────────────────────────────────
tab1, tab2 = st.tabs(["📈 總覽", "🕐 任務紀錄與明細"])

# ══════════════════════════════════════════════
# TAB 1：總覽
# ══════════════════════════════════════════════
with tab1:

    st.subheader("區間總覽")
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    # delta_color:
    #   "normal"  → 上升綠、下降紅（任務數：越多越好）
    #   "inverse" → 上升紅、下降綠（費用/延遲/修正次數：越低越好）
    c1.metric("總任務數",       stats.get("total_runs", 0),
              delta=delta_pct(stats.get("total_runs", 0), prev_stats.get("total_runs", 0)),
              delta_color="normal")
    c2.metric("Input Tokens",  f"{stats.get('total_input_tokens', 0):,}")
    c3.metric("Output Tokens", f"{stats.get('total_output_tokens', 0):,}")
    c4.metric("累計費用 (USD)", f"${stats.get('total_cost_usd', 0):.6f}",
              delta=delta_pct(stats.get("total_cost_usd", 0), prev_stats.get("total_cost_usd", 0)),
              delta_color="inverse")
    c5.metric("平均 Latency",  f"{int(stats.get('avg_latency_ms', 0))} ms",
              delta=delta_pct(stats.get("avg_latency_ms", 0), prev_stats.get("avg_latency_ms", 0)),
              delta_color="inverse")
    c6.metric("平均修正次數",   f"{stats.get('avg_revision_count', 0):.2f}",
              delta=delta_pct(stats.get("avg_revision_count", 0), prev_stats.get("avg_revision_count", 0)),
              delta_color="inverse")
    c7.metric("平均 LLM 呼叫/任務", f"{stats.get('avg_llm_calls_per_run', 0):.1f}",
              delta=delta_pct(stats.get("avg_llm_calls_per_run", 0), prev_stats.get("avg_llm_calls_per_run", 0)),
              delta_color="inverse")

    st.divider()

    # 與上週同期比較
    with st.expander("📊 與上週同期比較分析", expanded=True):
        if not prev_stats or prev_stats.get("total_runs", 0) == 0:
            st.info("上週同期尚無資料，無法比較。")
        else:
            metrics_to_compare = [
                ("總任務數",           "total_runs",            "",   False),
                ("累計費用 (USD)",      "total_cost_usd",        "$",  True),
                ("平均 Latency (ms)",  "avg_latency_ms",         "ms", True),
                ("平均修正次數",        "avg_revision_count",    "",   True),
                ("平均 LLM 呼叫次數",  "avg_llm_calls_per_run", "",   True),
            ]
            rows = []
            for label, key, unit, lower_is_better in metrics_to_compare:
                curr = stats.get(key, 0) or 0
                prev = prev_stats.get(key, 0) or 0
                if prev == 0:
                    change_str = "—"
                else:
                    pct = (curr - prev) / prev * 100
                    direction = "▲" if pct > 0 else "▼"
                    is_bad = (pct > 0 and lower_is_better) or (pct < 0 and not lower_is_better)
                    sign = "🔴" if is_bad else "🟢"
                    change_str = f"{sign} {direction} {abs(pct):.1f}%"
                curr_str = f"${curr:.4g}" if unit == "$" else f"{curr:.4g}{unit}"
                prev_str = f"${prev:.4g}" if unit == "$" else f"{prev:.4g}{unit}"
                rows.append({"指標": label, "本期": curr_str, "上週同期": prev_str, "變化": change_str})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()

    # 圖表
    left, right = st.columns(2)

    with left:
        st.subheader("🔄 自動修正次數分布")
        rev_data = get_revision_distribution(start_utc, end_utc)
        if rev_data:
            df_rev = pd.DataFrame(rev_data)
            df_rev["revision_count"] = df_rev["revision_count"].astype(str) + " 次"
            st.bar_chart(df_rev.set_index("revision_count")["count"])
            st.caption("0 次 = 一次通過；≥1 次 = 被 Compliance 攔截並自動修正")
        else:
            st.info("尚無資料")

    with right:
        st.subheader("✅ 任務結果分布")
        status_data = get_status_distribution(start_utc, end_utc)
        if status_data:
            df_status = pd.DataFrame(status_data)
            status_labels = {
                "success":     "✅ 成功",
                "intercepted": "⚠️ 攔截後修正",
                "error":       "❌ 錯誤",
            }
            df_status["status"] = df_status["status"].map(lambda s: status_labels.get(s, s))
            st.bar_chart(df_status.set_index("status")["count"])
        else:
            st.info("尚無資料")


# ══════════════════════════════════════════════
# TAB 2：任務紀錄與明細
# ══════════════════════════════════════════════
with tab2:

    runs = get_runs_by_date_range(start_utc, end_utc)
    if not runs:
        st.info("此區間無任務紀錄")
        st.stop()

    # ── 任務列表 ──
    st.subheader("任務紀錄")

    df_runs = pd.DataFrame(runs)
    df_runs["timestamp"]        = df_runs["timestamp"].apply(
        lambda s: to_taipei(s).strftime("%Y-%m-%d %H:%M:%S")
    )
    df_runs["total_cost_usd"]   = df_runs["total_cost_usd"].apply(lambda x: f"${x:.6f}")
    df_runs["total_latency_ms"] = df_runs["total_latency_ms"].apply(lambda x: f"{x} ms")

    # 格式化採購金額欄位（None / NaN / 0 顯示為 —）
    def fmt_price(val):
        try:
            return f"${int(val):,}" if val and str(val) != "nan" else "—"
        except (ValueError, TypeError):
            return "—"

    df_runs["item_price"]      = df_runs["item_price"].apply(fmt_price)
    df_runs["original_total"]  = df_runs.apply(
        lambda r: f"{int(r['original_quantity'])} 個 × {fmt_price(r['item_price'].replace('$','').replace(',','') if r['item_price'] != '—' else 0)} = {fmt_price(r['original_total'])}"
        if r["original_total"] and r["original_total"] != 0 else "—", axis=1
    )
    df_runs["final_total"]     = df_runs.apply(
        lambda r: f"{int(r['final_quantity'])} 個 = {fmt_price(r['final_total'])}"
        if r["final_total"] and r["final_total"] != 0 else "—", axis=1
    )

    display_cols = {
        "timestamp":            "時間（台灣）",
        "input_message":        "輸入需求",
        "budget":               "預算",
        "status":               "結果",
        "revision_count":       "修正次數",
        "item_price":           "商品單價",
        "original_total":       "原始方案",
        "final_total":          "最終方案",
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

    # ── 單次任務明細 ──
    st.subheader("🔍 單次任務明細")

    run_options = {
        f"{to_taipei(r['timestamp']).strftime('%m/%d %H:%M')}  |  {r['input_message'][:25]}...": r["run_id"]
        for r in runs
    }
    selected_label  = st.selectbox("選擇任務：", list(run_options.keys()))
    selected_run_id = run_options[selected_label]
    selected_run    = next(r for r in runs if r["run_id"] == selected_run_id)

    # 採購金額摘要
    def fmt_price_val(val):
        try:
            return f"${int(val):,}" if val and str(val) != "nan" else "—"
        except (ValueError, TypeError):
            return "—"

    pm1, pm2, pm3, pm4, pm5 = st.columns(5)
    pm1.metric("預算上限",       f"${selected_run['budget']:,}")
    pm2.metric("商品單價",       fmt_price_val(selected_run.get("item_price")))
    pm3.metric("原始下單總額",   fmt_price_val(selected_run.get("original_total")))
    pm4.metric("最終下單總額",   fmt_price_val(selected_run.get("final_total")))
    pm5.metric("修正次數",       selected_run.get("revision_count", 0))

    # 原始 vs 最終的差異說明
    orig_qty  = selected_run.get("original_quantity")
    final_qty = selected_run.get("final_quantity")
    if orig_qty and final_qty and orig_qty != final_qty:
        orig_total  = selected_run.get("original_total") or 0
        final_total = selected_run.get("final_total") or 0
        st.caption(
            f"⚠️ 原始方案：{orig_qty} 個（總額 {int(orig_total):,} 元）"
            f" → 超出預算，自動修正為 {final_qty} 個"
            f"（總額 {int(final_total):,} 元）"
        )

    st.divider()

    llm_calls = get_llm_calls_by_run(selected_run_id)

    if not llm_calls:
        st.info("此任務無 LLM 呼叫明細")
    else:
        lm1, lm2, lm3 = st.columns(3)
        lm1.metric("LLM 呼叫次數",   len(llm_calls))
        lm2.metric("Input Tokens",  sum(c["input_tokens"]  for c in llm_calls))
        lm3.metric("Output Tokens", sum(c["output_tokens"] for c in llm_calls))

        df_calls = pd.DataFrame(llm_calls)
        df_calls["cost_usd"]    = df_calls["cost_usd"].apply(lambda x: f"${x:.8f}")
        df_calls["latency_ms"]  = df_calls["latency_ms"].apply(lambda x: f"{x} ms")
        df_calls["call_reason"] = df_calls["call_reason"].fillna("—")

        display_call_cols = {
            "sequence":      "第幾次",
            "call_reason":   "呼叫原因",
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

        # 節點執行路徑
        st.subheader("🗺️ 節點執行路徑")
        revision_count = selected_run["revision_count"]
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
