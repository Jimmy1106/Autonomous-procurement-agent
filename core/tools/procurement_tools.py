from langchain_core.tools import tool


@tool
def check_item_price(item_name: str) -> int:
    """查詢商品的單價。"""
    print(f"  [工具執行] 正在查詢 {item_name} 的價格...")
    if "mouse" in item_name.lower():
        return 120
    return 50


@tool
def place_order(item_name: str, quantity: int, total_price: int):
    """執行最終下單。"""
    return f"SUCCESS: 已下單 {quantity} 個 {item_name}，總金額 ${total_price}。"


# 統一匯出，graph.py 和 nodes 都從這裡取用
tools = [check_item_price, place_order]
