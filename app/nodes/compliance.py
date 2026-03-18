from langchain_core.messages import AIMessage, ToolMessage

from app.agent.state import AgentState


def compliance_check_node(state: AgentState) -> dict:
    """
    審核節點：在工具執行「之前」攔截並檢查 tool_calls。
    若發現違規，返回 ToolMessage 表示執行失敗，迫使 Agent 重新思考。
    """
    messages = state["messages"]
    last_message = messages[-1]
    current_count = state.get("revision_count", 0)
    budget = state.get("budget", 500)

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            if tool_call["name"] == "place_order":
                total = tool_call["args"].get("total_price", 0)
                quantity = tool_call["args"].get("quantity", 0)
                item = tool_call["args"].get("item_name", "未知商品")

                print(f"\n🔍 [審核節點] 檢測到下單意圖：{quantity} 個 {item}，總額 ${total}")

                if total > budget:
                    print(f"❌ [審核攔截] 總額 ${total} 超過預算 ${budget}！")
                    print(f"📧 [審核節點] 將錯誤訊息返回給 Agent，要求修正...")

                    max_quantity = budget // (total // quantity)

                    error_msg = (
                        f"COMPLIANCE_ERROR: 下單請求被拒絕。\n"
                        f"原因：總價 ${total} 超過預算 ${budget}。\n"
                        f"你嘗試購買 {quantity} 個 {item}。\n\n"
                        f"⚠️ 強制要求：立即重新計算並下單。\n"
                        f"- 在預算 ${budget} 內，最多可購買 {max_quantity} 個\n"
                        f"- 你必須立即呼叫 place_order 下單 {max_quantity} 個\n"
                        f"- 不要詢問用戶，直接執行下單操作"
                    )

                    tool_message = ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_call["id"]
                    )

                    return {
                        "messages": [tool_message],
                        "revision_count": current_count + 1
                    }
                else:
                    print(f"✅ [審核通過] 總額 ${total} 符合預算 ${budget}")

    return {"revision_count": current_count}
