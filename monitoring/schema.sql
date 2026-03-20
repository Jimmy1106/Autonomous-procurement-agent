-- 每次採購任務的彙總紀錄
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    timestamp           TEXT NOT NULL,          -- ISO 8601 UTC 格式，顯示時轉台灣時間
    input_message       TEXT NOT NULL,
    budget              INTEGER NOT NULL,
    status              TEXT NOT NULL,          -- 'success' | 'intercepted' | 'error'
    revision_count      INTEGER DEFAULT 0,
    total_input_tokens  INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_cost_usd      REAL DEFAULT 0.0,
    total_latency_ms    INTEGER DEFAULT 0
);

-- 每次 LLM 呼叫的明細
CREATE TABLE IF NOT EXISTS llm_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    node_name       TEXT,                       -- 'agent'
    sequence        INTEGER,                    -- 該任務的第幾次 LLM 呼叫
    call_reason     TEXT,                       -- 呼叫原因：查價 / 下單 / 修正下單 / 最終回應
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cost_usd        REAL DEFAULT 0.0,
    latency_ms      INTEGER DEFAULT 0
);
