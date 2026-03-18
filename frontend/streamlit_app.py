"""
frontend/streamlit_app.py

自主採購代理人的聊天介面。
呼叫 FastAPI SSE endpoint，將 agent 每個執行步驟即時顯示在頁面上。

啟動指令：streamlit run frontend/streamlit_app.py
"""

import json
import os

import requests
import streamlit as st

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────
API_URL = os.getenv("API_URL", "http://localhost:8000")
PROCURE_ENDPOINT = f"{API_URL}/api/procure"
HEALTH_ENDPOINT = f"{API_URL}/api/health"

# 各事件類型的顯示設定
EVENT_CONFIG = {
    "tool_call":       {"icon": "🔧", "label": "工具呼叫",  "color": "#4A90D9"},
    "tool_result":     {"icon": "📦", "label": "工具回傳",  "color": "#7B68EE"},
    "compliance_error":{"icon": "❌", "label": "審核攔截",  "color": "#E05252"},
    "agent_reply":     {"icon": "🤖", "label": "Agent 回應","color": "#555"},
    "done":            {"icon": "✅", "label": "完成",      "color": "#27AE60"},
    "error":           {"icon": "🚨", "label": "系統錯誤",  "color": "#E05252"},
}


# ──────────────────────────────────────────────
# 頁面設定
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="自主採購代理人",
    page_icon="🤖",
    layout="wide",
)

st.title("🤖 自主採購代理人")
st.caption("以自然語言描述採購需求，Agent 將自動解析意圖、查詢價格、審核預算並完成下單。")


# ──────────────────────────────────────────────
# Sidebar：設定區
# ──────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 設定")

    budget = st.number_input(
        "預算上限（元）",
        min_value=1,
        value=500,
        step=100,
        help="Agent 下單前會自動檢查總金額是否超過此預算。",
    )

    st.divider()

    # API 連線狀態
    st.subheader("連線狀態")
    if st.button("🔄 檢查 API 連線"):
        try:
            resp = requests.get(HEALTH_ENDPOINT, timeout=3)
            if resp.status_code == 200:
                st.success("API 連線正常 ✅")
            else:
                st.error(f"API 回應異常：{resp.status_code}")
        except Exception:
            st.error("無法連線到 API，請確認 FastAPI server 已啟動。")

    st.divider()
    st.caption(f"API 位址：`{API_URL}`")

    if st.button("🗑️ 清除對話記錄"):
        st.session_state.messages = []
        st.rerun()


# ──────────────────────────────────────────────
# Session state 初始化
# ──────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []


# ──────────────────────────────────────────────
# 顯示歷史對話
# ──────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.markdown(msg["content"])
        else:
            # assistant 訊息包含 steps + 最終結果
            for step in msg.get("steps", []):
                render_step(step["type"], step["content"])

            if msg.get("summary"):
                st.success(msg["summary"])
            if msg.get("revision_count", 0) > 0:
                st.caption(f"🔄 自動修正次數：{msg['revision_count']}")


def render_step(event_type: str, content: str) -> None:
    """將單一 agent step 渲染為帶有 icon 和色彩的訊息列。"""
    cfg = EVENT_CONFIG.get(event_type, {"icon": "ℹ️", "label": event_type, "color": "#888"})
    st.markdown(
        f"""<div style="
            padding: 6px 12px;
            margin: 4px 0;
            border-left: 3px solid {cfg['color']};
            border-radius: 4px;
            background: rgba(0,0,0,0.03);
            font-size: 0.9em;
        ">
        <span style="color:{cfg['color']};font-weight:600;">{cfg['icon']} {cfg['label']}</span>
        &nbsp;{content}
        </div>""",
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────────
# 使用者輸入
# ──────────────────────────────────────────────
if user_input := st.chat_input("請描述您的採購需求，例如：我需要買一些開會用的設備..."):

    # 顯示使用者訊息
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

    # 呼叫 API 並串流顯示結果
    with st.chat_message("assistant"):
        steps_container = st.container()
        collected_steps = []
        final_content = ""
        revision_count = 0

        try:
            with requests.post(
                PROCURE_ENDPOINT,
                json={"message": user_input, "budget": budget},
                stream=True,
                timeout=120,
            ) as resp:

                if resp.status_code != 200:
                    st.error(f"API 錯誤：{resp.status_code}")
                else:
                    # 逐行解析 SSE
                    for raw_line in resp.iter_lines():
                        if not raw_line:
                            continue

                        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                        if not line.startswith("data: "):
                            continue

                        try:
                            payload = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue

                        event_type = payload.get("type", "")
                        content    = payload.get("content", "")

                        if event_type == "done":
                            final_content  = content
                            revision_count = payload.get("revision_count", 0)
                        else:
                            # 即時顯示每個 step
                            with steps_container:
                                render_step(event_type, content)
                            collected_steps.append({"type": event_type, "content": content})

                    # 顯示最終結果
                    if final_content:
                        st.success(final_content)
                    if revision_count > 0:
                        st.caption(f"🔄 自動修正次數：{revision_count}")

        except requests.exceptions.ConnectionError:
            st.error("❌ 無法連線到 API Server，請確認 FastAPI 已啟動（`uvicorn app.main:app --reload`）。")
        except requests.exceptions.Timeout:
            st.error("❌ 請求逾時，Agent 執行時間過長。")
        except Exception as e:
            st.error(f"❌ 發生錯誤：{e}")

    # 儲存到 session state（含 steps 摘要供歷史顯示）
    st.session_state.messages.append({
        "role": "assistant",
        "steps": collected_steps,
        "summary": final_content,
        "revision_count": revision_count,
    })
