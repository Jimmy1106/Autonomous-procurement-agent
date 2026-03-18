from typing import Annotated, List, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    revision_count: int
    budget: int
