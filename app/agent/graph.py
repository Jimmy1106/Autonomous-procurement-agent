from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agent.state import AgentState
from app.nodes.compliance import compliance_check_node
from app.nodes.reasoning import reasoning_node
from app.tools.procurement_tools import tools


# ==========================================
# 路由函式 (Edges)
# ==========================================

def route_after_agent(state: AgentState) -> str:
    """Agent 節點後的路由：有 tool_calls 去審核，否則結束。"""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "compliance"
    return END


def route_after_compliance(state: AgentState) -> str:
    """Compliance 節點後的路由：審核失敗退回 Agent，通過則執行工具。"""
    last_message = state["messages"][-1]
    if isinstance(last_message, ToolMessage) and "COMPLIANCE_ERROR" in last_message.content:
        print("🔄 [路由] 審核未通過，退回 Agent 重新思考\n")
        return "agent"
    print("➡️  [路由] 審核通過，執行工具\n")
    return "tools"


# ==========================================
# Graph 建構
# ==========================================

def build_graph():
    """建立並編譯 LangGraph workflow，回傳可執行的 app。"""
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", reasoning_node)
    workflow.add_node("compliance", compliance_check_node)
    workflow.add_node("tools", ToolNode(tools))

    workflow.add_edge(START, "agent")

    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {"compliance": "compliance", END: END}
    )

    workflow.add_conditional_edges(
        "compliance",
        route_after_compliance,
        {"agent": "agent", "tools": "tools"}
    )

    workflow.add_edge("tools", "agent")

    return workflow.compile()
