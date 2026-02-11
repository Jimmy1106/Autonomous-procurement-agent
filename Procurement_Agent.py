import os
from typing import Annotated, TypedDict, List
from dotenv import load_dotenv

# 1. 載入環境變數
load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END, START, add_messages
from langgraph.prebuilt import ToolNode

# ==========================================
# 2. 定義狀態
# ==========================================
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    revision_count: int
    budget: int  # 新增：明確的預算欄位

# ==========================================
# 3. 定義工具
# ==========================================
@tool
def check_item_price(item_name: str) -> int:
    """查詢商品的單價。"""
    print(f"  [工具執行] 正在查詢 {item_name} 的價格...")
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
    """推理節點：分析當前狀況並決定下一個 Action"""
    messages = state["messages"]
    
    # 如果是第一次執行，加入系統提示
    if len(messages) == 1:
        system_prompt = SystemMessage(
            content=f"你是一個採購助理。當前預算限制為 ${state['budget']}。"
                    "你需要：1) 先查詢價格 2) 確認總價不超過預算 3) 再下單。"
        )
        messages = [system_prompt] + messages
    
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

def compliance_check_node(state: AgentState):
    """
    審核節點 (關鍵改動)：
    - 在工具執行「之前」攔截並檢查 tool_calls
    - 如果發現違規，返回 ToolMessage 表示執行失敗
    """
    messages = state["messages"]
    last_message = messages[-1]
    current_count = state.get("revision_count", 0)
    budget = state.get("budget", 500)
    
    # 只處理 AI 要呼叫工具的情況
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            # 攔截下單工具的呼叫
            if tool_call["name"] == "place_order":
                total = tool_call["args"].get("total_price", 0)
                quantity = tool_call["args"].get("quantity", 0)
                item = tool_call["args"].get("item_name", "未知商品")
                
                print(f"\n🔍 [審核節點] 檢測到下單意圖：{quantity} 個 {item}，總額 ${total}")
                
                # 預算檢查
                if total > budget:
                    print(f"❌ [審核攔截] 總額 ${total} 超過預算 ${budget}！")
                    print(f"📧 [審核節點] 將錯誤訊息返回給 Agent，要求修正...")
                    
                    error_msg = (
                        f"COMPLIANCE_ERROR: 下單請求被拒絕。\n"
                        f"原因：總價 ${total} 超過預算限制 ${budget}。\n"
                        f"詳情：你計畫購買 {quantity} 個 {item}，總價 ${total}。\n"
                        f"要求：請重新計算在預算 ${budget} 內最多可以購買多少個，並重新下單。"
                    )
                    
                    # 關鍵修正：使用 ToolMessage 回應被攔截的 tool_call
                    # 這樣才符合 OpenAI API 的要求
                    tool_message = ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_call["id"]  # 必須對應原本的 tool_call_id
                    )
                    
                    return {
                        "messages": [tool_message], 
                        "revision_count": current_count + 1
                    }
                else:
                    print(f"✅ [審核通過] 總額 ${total} 符合預算 ${budget}")
    
    # 沒問題，繼續執行
    return {"revision_count": current_count}

# ==========================================
# 5. 定義流程控制 (Edges)
# ==========================================
def route_after_agent(state: AgentState):
    """Agent 節點後的路由：決定下一步去哪"""
    last_message = state["messages"][-1]
    
    # 如果 AI 想呼叫工具 → 先去審核
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "compliance"
    
    # 如果是普通回覆 → 結束
    return END

def route_after_compliance(state: AgentState):
    """Compliance 節點後的路由：決定是執行工具還是退回 Agent"""
    last_message = state["messages"][-1]
    
    # 如果 Compliance 發現問題，會塞入一個 ToolMessage (COMPLIANCE_ERROR)
    if isinstance(last_message, ToolMessage) and "COMPLIANCE_ERROR" in last_message.content:
        print("🔄 [路由] 審核未通過，退回 Agent 重新思考\n")
        return "agent"
    
    # 審核通過 → 執行工具
    print("➡️  [路由] 審核通過，執行工具\n")
    return "tools"

# ==========================================
# 6. 建構 Graph (關鍵修改)
# ==========================================
workflow = StateGraph(AgentState)

# 添加節點
workflow.add_node("agent", reasoning_node)
workflow.add_node("compliance", compliance_check_node)
workflow.add_node("tools", ToolNode(tools))

# 設定流程
workflow.add_edge(START, "agent")

# Agent 之後：可能去 Compliance 或結束
workflow.add_conditional_edges(
    "agent", 
    route_after_agent,
    {
        "compliance": "compliance",
        END: END
    }
)

# Compliance 之後：可能執行 Tools 或退回 Agent
workflow.add_conditional_edges(
    "compliance",
    route_after_compliance,
    {
        "agent": "agent",
        "tools": "tools"
    }
)

# Tools 執行完後回到 Agent 看結果
workflow.add_edge("tools", "agent")

app = workflow.compile()

# ==========================================
# 7. 啟動選單與輔助方法
# ==========================================
def save_graph_image(app):
    """繪製架構圖"""
    try:
        png_data = app.get_graph().draw_mermaid_png()
        with open("procurement_architecture_fixed.png", "wb") as f:
            f.write(png_data)
        print(f"\n✅ 架構圖已成功儲存至: {os.getcwd()}/procurement_architecture_fixed.png")
    except Exception:
        print("\n💡 提示：本機環境缺少繪圖組件，已為您生成 Mermaid 代碼。")
        print("請複製下方代碼到 https://mermaid.live 查看流程圖：\n")
        print(app.get_graph().draw_mermaid())

if __name__ == "__main__":
    print("="*60)
    print("   修正版：Stage 1-3 自主採購代理人 (審核前置)")
    print("="*60)
    print("1. [架構確認] 產出流程圖檔")
    print("2. [超標測試] 模擬購買 5 個 Mouse (會被攔截)")
    print("3. [合規測試] 模擬購買 4 個 Mouse (應該通過)")
    
    choice = input("\n請選擇操作 (1/2/3): ")
    
    if choice == "1":
        save_graph_image(app)
    
    elif choice in ["2", "3"]:
        quantity = 5 if choice == "2" else 4
        print(f"\n🚀 任務啟動：購買 {quantity} 個 Pro Mouse (預算 $500)...")
        print("="*60)
        
        inputs = {
            "messages": [
                HumanMessage(
                    content=f"我要買 {quantity} 個 Pro Mouse。請先查價，確認總價後下單。"
                )
            ],
            "revision_count": 0,
            "budget": 500
        }
        
        # 使用 stream 觀察每個節點的執行
        step = 0
        for event in app.stream(inputs, stream_mode="values"):
            step += 1
            if "messages" in event:
                msg = event["messages"][-1]
                
                # 顯示節點動作
                if isinstance(msg, AIMessage):
                    if msg.tool_calls:
                        print(f"\n[Step {step}] Agent 決定：呼叫 {msg.tool_calls[0]['name']}")
                    elif msg.content:
                        print(f"\n[Step {step}] Agent 回應：{msg.content[:80]}...")
                
                elif isinstance(msg, ToolMessage) and "COMPLIANCE_ERROR" in msg.content:
                    print(f"\n[Step {step}] Compliance 攔截：{msg.content.split('詳情：')[0]}...")
                
                elif isinstance(msg, ToolMessage):
                    print(f"\n[Step {step}] Tool 執行結果：{msg.content[:80]}...")
        
        print("\n" + "="*60)
        print("🎯 最終結果：")
        print(event["messages"][-1].content)
        print(f"🔄 修正次數：{event['revision_count']}")
        print("="*60)