from langchain_core.tools import tool

from rag.retriever import retrieve


@tool
def check_item_price(item_name: str) -> int:
    """查詢商品的單價。"""
    print(f"  [工具執行] 正在查詢 {item_name} 的價格...")
    if "mouse" in item_name.lower() or "滑鼠" in item_name:
        return 120
    if "keyboard" in item_name.lower() or "鍵盤" in item_name:
        return 350
    if "webcam" in item_name.lower():
        return 800
    return 50


@tool
def place_order(item_name: str, quantity: int, total_price: int):
    """執行最終下單。"""
    return f"SUCCESS: 已下單 {quantity} 個 {item_name}，總金額 ${total_price}。"


@tool
def search_knowledge_base(query: str) -> str:
    """
    查詢採購相關知識庫，包含採購規範、商品目錄與系統使用說明。
    當使用者詢問採購規範、商品資訊、系統操作說明時使用此工具。
    不適用於實際下單或查詢商品即時價格。
    """
    print(f"  [工具執行] 正在查詢知識庫：{query}")
    return retrieve(query)


# 統一匯出，graph.py 和 nodes 都從這裡取用
tools = [check_item_price, place_order, search_knowledge_base]
