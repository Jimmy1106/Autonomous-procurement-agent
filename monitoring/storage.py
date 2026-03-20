"""
monitoring/storage.py

SQLite 讀寫邏輯。
所有監控數據的存取都透過這個模組，不直接在其他地方操作資料庫。
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# 資料庫檔案放在專案根目錄的 data/ 資料夾
# Docker 環境下可透過 volume 掛載，確保重啟後資料不消失
DB_PATH = Path(os.getenv("DB_PATH", "data/monitoring.db"))


def init_db() -> None:
    """初始化資料庫：建立資料夾與資料表（若不存在）。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).parent / "schema.sql"

    with _get_conn() as conn:
        conn.executescript(schema_path.read_text())


@contextmanager
def _get_conn():
    """取得 SQLite 連線的 context manager，自動 commit / rollback。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row       # 讓查詢結果可以用欄位名稱存取
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────────
# 寫入
# ──────────────────────────────────────────────

def insert_run(run: dict) -> None:
    """新增一筆任務紀錄。"""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO runs
                (run_id, timestamp, input_message, budget, status,
                 revision_count, total_input_tokens, total_output_tokens,
                 total_cost_usd, total_latency_ms)
            VALUES
                (:run_id, :timestamp, :input_message, :budget, :status,
                 :revision_count, :total_input_tokens, :total_output_tokens,
                 :total_cost_usd, :total_latency_ms)
            """,
            run,
        )


def insert_llm_call(call: dict) -> None:
    """新增一筆 LLM 呼叫明細。"""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO llm_calls
                (run_id, node_name, sequence,
                 input_tokens, output_tokens, cost_usd, latency_ms)
            VALUES
                (:run_id, :node_name, :sequence,
                 :input_tokens, :output_tokens, :cost_usd, :latency_ms)
            """,
            call,
        )


# ──────────────────────────────────────────────
# 讀取（監控頁面用）
# ──────────────────────────────────────────────

def get_recent_runs(limit: int = 50) -> list[dict]:
    """取得最近 N 筆任務紀錄，最新的在前。"""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_llm_calls_by_run(run_id: str) -> list[dict]:
    """取得某次任務的所有 LLM 呼叫明細。"""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_calls WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_summary_stats() -> dict:
    """取得全域統計數字，供監控頁面頂部 metric 卡片使用。"""
    with _get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*)                        AS total_runs,
                SUM(total_input_tokens)         AS total_input_tokens,
                SUM(total_output_tokens)        AS total_output_tokens,
                ROUND(SUM(total_cost_usd), 6)   AS total_cost_usd,
                ROUND(AVG(total_latency_ms), 0) AS avg_latency_ms,
                ROUND(AVG(revision_count), 2)   AS avg_revision_count
            FROM runs
            """
        ).fetchone()
    return dict(row) if row else {}


def get_revision_distribution() -> list[dict]:
    """取得 revision_count 的分布，供長條圖使用。"""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT revision_count, COUNT(*) AS count
            FROM runs
            GROUP BY revision_count
            ORDER BY revision_count
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_status_distribution() -> list[dict]:
    """取得任務結果（success/intercepted/error）的分布。"""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM runs
            GROUP BY status
            """
        ).fetchall()
    return [dict(r) for r in rows]
