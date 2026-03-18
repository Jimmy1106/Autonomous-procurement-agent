"""
進入點：保留原本的互動式選單，功能與原程式完全相同。
第二步（FastAPI）完成後，此檔案可退役或保留作為本機除錯用途。
"""
import os

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

load_dotenv()

from app.agent.graph import build_graph


def save_graph_image(app):
    """繪製架構圖並儲存，或輸出 Mermaid 原始碼。"""
    try:
        png_data = app.get_graph().draw_mermaid_png()
        with open("procurement_architecture.png", "wb") as f:
            f.write(png_data)
        print(f"\n✅ 架構圖已成功儲存至: {os.getcwd()}/procurement_architecture.png")
    except Exception:
        print("\n💡 提示：本機環境缺少繪圖組件，已為您生成 Mermaid 代碼。")
        print("請複製下方代碼到 https://mermaid.live 查看流程圖：\n")
        print(app.get_graph().draw_mermaid())


def run_interactive(app, quantity: int, budget: int = 500):
    """執行採購流程並串流顯示每個 step。"""
    print(f"\n🚀 任務啟動：購買 {quantity} 個 Pro Mouse (預算 ${budget})...")
    print("=" * 60)

    inputs = {
        "messages": [
            HumanMessage(content=f"我要買 {quantity} 個 Pro Mouse。請先查價，確認總價後下單。")
        ],
        "revision_count": 0,
        "budget": budget,
    }

    step = 0
    for event in app.stream(inputs, stream_mode="values"):
        step += 1
        if "messages" in event:
            msg = event["messages"][-1]

            if isinstance(msg, AIMessage):
                if msg.tool_calls:
                    print(f"\n[Step {step}] Agent 決定：呼叫 {msg.tool_calls[0]['name']}")
                elif msg.content:
                    print(f"\n[Step {step}] Agent 回應：{msg.content[:80]}...")

            elif isinstance(msg, ToolMessage) and "COMPLIANCE_ERROR" in msg.content:
                print(f"\n[Step {step}] Compliance 攔截：{msg.content.split(chr(10))[0]}...")

            elif isinstance(msg, ToolMessage):
                print(f"\n[Step {step}] Tool 執行結果：{msg.content[:80]}...")

    print("\n" + "=" * 60)
    print("🎯 最終結果：")
    print(event["messages"][-1].content)
    print(f"🔄 修正次數：{event['revision_count']}")
    print("=" * 60)


if __name__ == "__main__":
    print("=" * 60)
    print("   自主採購代理人")
    print("=" * 60)
    print("1. [架構確認] 產出流程圖檔")
    print("2. [超標測試] 模擬購買 5 個 Mouse（會被攔截）")
    print("3. [合規測試] 模擬購買 4 個 Mouse（應該通過）")

    choice = input("\n請選擇操作 (1/2/3): ")
    app = build_graph()

    if choice == "1":
        save_graph_image(app)
    elif choice in ["2", "3"]:
        quantity = 5 if choice == "2" else 4
        run_interactive(app, quantity)
