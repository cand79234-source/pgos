-- Personal Growth OS · 精简版 Schema（3 张表）
PRAGMA journal_mode = WAL;

-- 计划（路线图 + 当前位置合一）
CREATE TABLE IF NOT EXISTS plans (
    id          TEXT PRIMARY KEY,           -- english / fae / exercise / content
    name        TEXT NOT NULL,
    goal        TEXT,
    normal      TEXT,                        -- 正常每日目标（3h / 2h）
    minimum     TEXT,                        -- 最低剂量（仅用户主动要求时启用）
    frequency   TEXT,                        -- 频率
    route       TEXT,                        -- JSON：路线（FAE 24 周 / 英语 12 主题周）
    checkpoints TEXT,                        -- JSON：检查点
    extra       TEXT,                        -- JSON：其他规则（每日结构 / 复习节奏等）
    -- 当前位置（只随真实执行推进，不因日期跳转）
    cur_week    INTEGER,
    cur_day     INTEGER,
    cur_topic   TEXT,
    cur_unit    TEXT,
    pending     TEXT,                        -- JSON：待完成单元列表
    next_cp     TEXT,                        -- 下一个检查点
    start_date  TEXT,                        -- 起点日期（部署日自动写入），用于计算剩余天数
    updated_at  TEXT
);

-- 任务
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,           -- t_YYYYMMDD_NNN
    title       TEXT NOT NULL,
    type        TEXT NOT NULL,              -- long_term / temporary
    plan_id     TEXT,
    task_date   TEXT NOT NULL,              -- YYYY-MM-DD
    due_date    TEXT,
    scheduled   TEXT,                        -- HH:MM
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending / in_progress / completed / postponed
    priority    TEXT DEFAULT 'normal',
    duration    TEXT,
    level       TEXT,                        -- completed 时：normal / minimum
    notes       TEXT,
    raw_input   TEXT,                        -- 添加时的用户原话
    created_at  TEXT NOT NULL,
    completed_at TEXT,
    advanced    INTEGER DEFAULT 0          -- 已推进过计划位置（防撤销后重复推进）
);
CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks(task_date);

-- 周报
CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start  TEXT UNIQUE,
    content_md  TEXT,
    content_html TEXT,
    created_at  TEXT NOT NULL
);
