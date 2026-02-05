import os
from typing import Annotated, TypedDict, List
from dotenv import load_dotenv

# 1. 載入環境變數
load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END, START, add_messages  # 修正導入路徑
from langgraph.prebuilt import ToolNode

# ==========================================
# 2. 定義狀態 (Stage 1)
# ==========================================
class AgentState(TypedDict):
    # add_messages 是一個 Reducer，它會自動處理對話紀錄的追加與 ID 去重
    messages: Annotated[List[BaseMessage], add_messages]
    revision_count: int

# ==========================================
# 3. 定義工具 (Stage 3)
# ==========================================
@tool
def check_item_price(item_name: str) -> int:
    """查詢商品的單價。"""
    print(f"  [工具執法] 正在查詢 {item_name} 的價格...")
    # 模擬資料庫：Mouse 120, 其他 50
    if "mouse" in item_name.lower():
        return 120
    return 50

@tool
def place_order(item_name: str, quantity: int, total_price: int):
    """執行最終下單。"""
    return f"SUCCESS: 已下單 {quantity} 個 {item_name}，總金額 ${total_price}。"

tools = [check_item_price, place_order]
llm = ChatOpenAI(model="gpt-4o", temperature=0)
llm_with_tools = llm.bind_tools(tools)

# ==========================================
# 4. 定義節點邏輯 (Nodes)
# ==========================================

def reasoning_node(state: AgentState):
    """大腦節點：分析當前狀況並決定下一個 Action"""
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

def compliance_check_node(state: AgentState):
    """審核節點 (Stage 2)：攔截並修正錯誤"""
    messages = state["messages"]
    last_message = messages[-1]
    current_count = state.get("revision_count", 0)
    
    # 檢查 AI 是否有呼叫工具的意圖
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            if tool_call["name"] == "place_order":
                total = tool_call["args"]["total_price"]
                budget = 500
                if total > budget:
                    print(f"\n⚠️  [Stage 2 攔截] 總額 ${total} 超標！(預算: ${budget}) 要求 AI 修正...")
                    error_msg = f"ERROR: Total price ${total} exceeds budget ${budget}. Please reduce quantity and try again."
                    # 返回一個給 AI 看的訊息，讓它知道錯在哪
                    return {
                        "messages": [HumanMessage(content=error_msg)], 
                        "revision_count": current_count + 1
                    }
    return {"revision_count": current_count}

# ==========================================
# 5. 定義流程控制 (Edges)
# ==========================================
def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    
    # AI 如果要叫工具
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    
    # AI 剛被我們(HumanMessage)糾正，需要重回大腦思考
    if isinstance(last_message, HumanMessage) and "ERROR" in last_message.content:
        return "agent"
    
    return END

# ==========================================
# 6. 建構 Graph
# ==========================================
workflow = StateGraph(AgentState)

workflow.add_node("agent", reasoning_node)
workflow.add_node("tools", ToolNode(tools))
workflow.add_node("compliance", compliance_check_node)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges(
    "agent", 
    should_continue, 
    {"tools": "tools", "agent": "agent", END: END}
)
workflow.add_edge("tools", "compliance")
workflow.add_edge("compliance", "agent")

app = workflow.compile()

# ==========================================
# 7. 啟動選單與輔助方法
# ==========================================
def save_graph_image(app):
    """繪製架構圖"""
    try:
        # 需安裝 pygraphviz 或相關繪圖包，否則會跳入 except
        png_data = app.get_graph().draw_mermaid_png()
        with open("poc_architecture.png", "wb") as f:
            f.write(png_data)
        print(f"\n✅ 架構圖已成功儲存至: {os.getcwd()}/poc_architecture.png")
    except Exception:
        print("\n💡 提示：本機環境缺少繪圖組件，已為您生成 Mermaid 代碼。")
        print("請複製下方代碼到 https://mermaid.live 查看流程圖：\n")
        print(app.get_graph().draw_mermaid())

if __name__ == "__main__":
    print("="*45)
    print("   Stage 1-3 自主採購代理人 (Agentic PoC)")
    print("="*45)
    print("1. [架構確認] 僅產出流程圖檔")
    print("2. [正式模擬] 執行採購任務 (包含自動糾錯)")
    
    choice = input("\n請選擇操作 (1/2): ")
    
    if choice == "1":
        save_graph_image(app)
    elif choice == "2":
        print("\n🚀 任務啟動中...")
        # 模擬一個會爆預算的請求
        inputs = {
            "messages": [HumanMessage(content="我要買 5 個 Pro Mouse，預算 $500。請幫我查價後直接下單。")],
            "revision_count": 0
        }
        
        # 使用 stream 模式觀察節點跳轉
        for event in app.stream(inputs, stream_mode="values"):
            if "messages" in event:
                msg = event["messages"][-1]
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    print(f"-> Node [Agent]: 決定呼叫工具 {msg.tool_calls[0]['name']}")
                elif isinstance(msg, HumanMessage) and "ERROR" in msg.content:
                    print(f"-> Node [Compliance]: 發現預算衝突，已發送糾正指令。")
        
        print("\n" + "="*45)
        print("✅ 最終決策結果：")
        print(event["messages"][-1].content)
        print("="*45)