from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

from core.state import AgentState
from core.tools.procurement_tools import tools

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

你有以下三個工具：
1. check_item_price：查詢商品單價，用於實際採購前的詢價
2. place_order：執行下單，確認金額合規後使用
3. search_knowledge_base：查詢採購規範、商品目錄、系統說明等知識庫

工具使用規則：
- 使用者詢問採購規範、流程、限制 → 使用 search_knowledge_base
- 使用者詢問有哪些商品或商品資訊 → 使用 search_knowledge_base
- 使用者詢問系統怎麼使用 → 使用 search_knowledge_base
- 使用者要購買商品 → 先用 check_item_price 查價，再用 place_order 下單

採購核心規則：
1. 先使用 check_item_price 查詢價格
2. 計算總價，確保不超過預算 ${state['budget']}
3. 直接使用 place_order 下單（不需要詢問用戶確認）

重要：如果下單請求因超過預算被拒絕，你必須：
- 立即重新計算：預算內最多可購買數量 = floor(預算 / 單價)
- 直接呼叫 place_order 下單新的數量
- 不要詢問用戶，直接執行修正後的下單"""
        )
        messages = [system_prompt] + messages

    response = _get_llm().invoke(messages)
    return {"messages": [response]}
