-- Initial schema. Never edit a shipped migration: add 0002_*.sql instead.

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per production run (a video, a research sweep, ...).
-- status: pending | running | paused | awaiting_approval | rejected | failed | done
CREATE TABLE jobs (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    input      TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Checkpoint per stage. A 'done' row's output is replayed on resume.
-- status: running | done | failed | awaiting_approval
CREATE TABLE stage_runs (
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    stage      TEXT NOT NULL,
    status     TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    output     TEXT,
    error      TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (job_id, stage)
);

CREATE TABLE approvals (
    job_id     INTEGER NOT NULL REFERENCES jobs(id),
    stage      TEXT NOT NULL,
    decision   TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    note       TEXT,
    decided_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (job_id, stage)
);

CREATE TABLE audit_log (
    id     INTEGER PRIMARY KEY,
    at     TEXT NOT NULL DEFAULT (datetime('now')),
    actor  TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT
);

-- Long-term project memory: decisions, research, learnings, positioning.
-- A correction never overwrites: the old row points at its replacement.
CREATE TABLE memory (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,
    key           TEXT NOT NULL,
    value         TEXT NOT NULL,
    source        TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at    TEXT,
    superseded_by INTEGER REFERENCES memory(id)
);
CREATE INDEX memory_active ON memory (kind, key) WHERE superseded_by IS NULL;

CREATE TABLE ideas (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL UNIQUE,
    pillar     TEXT,
    format     TEXT CHECK (format IN ('short', 'long')),
    score      REAL,
    status     TEXT NOT NULL DEFAULT 'new',
    evidence   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Real uploads only (dry runs are not recorded). content_hash blocks re-uploads.
CREATE TABLE publications (
    id           INTEGER PRIMARY KEY,
    job_id       INTEGER REFERENCES jobs(id),
    video_id     TEXT UNIQUE,
    content_hash TEXT NOT NULL UNIQUE,
    privacy      TEXT NOT NULL,
    title        TEXT,
    published_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- scope: channel | video ; ref: channel or video id ; metrics: JSON as returned.
CREATE TABLE analytics_snapshots (
    id       INTEGER PRIMARY KEY,
    taken_at TEXT NOT NULL DEFAULT (datetime('now')),
    scope    TEXT NOT NULL,
    ref      TEXT NOT NULL,
    metrics  TEXT NOT NULL
);

CREATE TABLE experiments (
    id         INTEGER PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    metric     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open',
    baseline   TEXT,
    result     TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at  TEXT
);
