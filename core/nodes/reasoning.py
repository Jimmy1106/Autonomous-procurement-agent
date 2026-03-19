from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

from core.state import AgentState
from core.tools.procurement_tools import tools

# Lazy initialization：避免 import 時就需要 OPENAI_API_KEY
_llm_with_tools = None


def _get_llm():
    global _llm_with_tools
    if _llm_with_tools is None:
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        _llm_with_tools = llm.bind_tools(tools)
    return _llm_with_tools


def reasoning_node(state: AgentState) -> dict:
    """推理節點：分析當前狀況並決定下一個 Action。"""
    messages = state["messages"]

    if len(messages) == 1:
        system_prompt = SystemMessage(
            content=f"""你是一個自主採購代理人。當前預算限制為 ${state['budget']}。

核心規則：
1. 先使用 check_item_price 查詢價格
2. 計算總價，確保不超過預算
3. 直接使用 place_order 下單（不需要詢問用戶確認）

重要：如果你的下單請求因為超過預算而被拒絕，你必須：
- 立即重新計算：預算內最多可購買數量 = floor(預算 / 單價)
- 直接呼叫 place_order 下單新的數量
- 不要詢問用戶，直接執行修正後的下單

範例：
- 用戶要 5 個，單價 $120，預算 $500
- 第一次嘗試：place_order(5, $600) → 被拒絕
- 自動修正：$500 ÷ $120 = 4.16，取整數 = 4
- 立即執行：place_order(4, $480) → 成功"""
        )
        messages = [system_prompt] + messages

    response = _get_llm().invoke(messages)
    return {"messages": [response]}
