-- 每次採購任務的彙總紀錄
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,          -- ISO 8601 格式
    input_message   TEXT NOT NULL,          -- 使用者輸入的自然語言
    budget          INTEGER NOT NULL,
    status          TEXT NOT NULL,          -- 'success' | 'intercepted' | 'error'
    revision_count  INTEGER DEFAULT 0,
    total_input_tokens  INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_cost_usd  REAL DEFAULT 0.0,
    total_latency_ms INTEGER DEFAULT 0      -- 整個任務端對端時間
);

-- 每次 LLM 呼叫的明細
CREATE TABLE IF NOT EXISTS llm_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    node_name       TEXT,                   -- 'agent'（目前只有 agent 節點呼叫 LLM）
    sequence        INTEGER,                -- 這是該任務的第幾次 LLM 呼叫
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cost_usd        REAL DEFAULT 0.0,
    latency_ms      INTEGER DEFAULT 0
);
