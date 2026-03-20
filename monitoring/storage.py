"""
monitoring/storage.py

SQLite 讀寫邏輯。
所有監控數據的存取都透過這個模組，不直接在其他地方操作資料庫。
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", "data/monitoring.db"))


def init_db() -> None:
    """初始化資料庫：建立資料夾、資料表，並執行 schema migration。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).parent / "schema.sql"

    with _get_conn() as conn:
        conn.executescript(schema_path.read_text())
        # Migration：為舊版資料庫補上新欄位（若已存在則忽略）
        try:
            conn.execute("ALTER TABLE llm_calls ADD COLUMN call_reason TEXT")
        except sqlite3.OperationalError:
            pass  # 欄位已存在，略過


@contextmanager
def _get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO llm_calls
                (run_id, node_name, sequence, call_reason,
                 input_tokens, output_tokens, cost_usd, latency_ms)
            VALUES
                (:run_id, :node_name, :sequence, :call_reason,
                 :input_tokens, :output_tokens, :cost_usd, :latency_ms)
            """,
            call,
        )


# ──────────────────────────────────────────────
# 讀取
# ──────────────────────────────────────────────

def get_runs_by_date_range(start_utc: str, end_utc: str) -> list[dict]:
    """依 UTC 時間區間查詢任務紀錄。"""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM runs
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp DESC
            """,
            (start_utc, end_utc),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_runs(limit: int = 50) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_llm_calls_by_run(run_id: str) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_calls WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_summary_stats(start_utc: str | None = None, end_utc: str | None = None) -> dict:
    """
    取得統計數字。可傳入時間區間做篩選，不傳則統計全部。
    新增 avg_llm_calls_per_run（平均每任務 LLM 呼叫次數）。
    """
    where = ""
    params: tuple = ()
    if start_utc and end_utc:
        where = "WHERE timestamp >= ? AND timestamp <= ?"
        params = (start_utc, end_utc)

    with _get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT
                COUNT(*)                        AS total_runs,
                SUM(total_input_tokens)         AS total_input_tokens,
                SUM(total_output_tokens)        AS total_output_tokens,
                ROUND(SUM(total_cost_usd), 6)   AS total_cost_usd,
                ROUND(AVG(total_latency_ms), 0) AS avg_latency_ms,
                ROUND(AVG(revision_count), 2)   AS avg_revision_count
            FROM runs {where}
            """,
            params,
        ).fetchone()

        # 平均每任務 LLM 呼叫次數：從 llm_calls join runs 計算
        llm_row = conn.execute(
            f"""
            SELECT ROUND(AVG(call_count), 2) AS avg_llm_calls_per_run
            FROM (
                SELECT r.run_id, COUNT(l.id) AS call_count
                FROM runs r
                LEFT JOIN llm_calls l ON r.run_id = l.run_id
                {where}
                GROUP BY r.run_id
            )
            """,
            params,
        ).fetchone()

    result = dict(row) if row else {}
    result["avg_llm_calls_per_run"] = dict(llm_row).get("avg_llm_calls_per_run", 0) if llm_row else 0
    return result


def get_revision_distribution(start_utc: str | None = None, end_utc: str | None = None) -> list[dict]:
    where = ""
    params: tuple = ()
    if start_utc and end_utc:
        where = "WHERE timestamp >= ? AND timestamp <= ?"
        params = (start_utc, end_utc)

    with _get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT revision_count, COUNT(*) AS count
            FROM runs {where}
            GROUP BY revision_count
            ORDER BY revision_count
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_status_distribution(start_utc: str | None = None, end_utc: str | None = None) -> list[dict]:
    where = ""
    params: tuple = ()
    if start_utc and end_utc:
        where = "WHERE timestamp >= ? AND timestamp <= ?"
        params = (start_utc, end_utc)

    with _get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT status, COUNT(*) AS count
            FROM runs {where}
            GROUP BY status
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]
