SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS samples (
    sample_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    relpath TEXT NOT NULL UNIQUE,
    category_raw TEXT,
    category TEXT,
    is_good INTEGER,
    split TEXT,
    weld_type TEXT,
    thickness_mm REAL,
    steel_type TEXT,
    current_a REAL,
    voltage_v REAL,
    gas_bar REAL,
    robot_speed_cpm REAL,
    manifest_relpath TEXT,
    manifest_row INTEGER,
    manifest_raw_json TEXT NOT NULL DEFAULT '{}',
    discovered_by_json TEXT NOT NULL DEFAULT '[]',
    health_status TEXT NOT NULL,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    image_count INTEGER NOT NULL DEFAULT 0,
    primary_video_relpath TEXT,
    primary_audio_relpath TEXT,
    primary_sensor_relpath TEXT,
    scanned_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    sample_id TEXT NOT NULL REFERENCES samples(sample_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    relpath TEXT NOT NULL,
    ordinal INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    mtime_ns INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    sha256 TEXT,
    UNIQUE(sample_id, kind, ordinal, relpath)
);

CREATE TABLE IF NOT EXISTS issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id TEXT REFERENCES samples(sample_id) ON DELETE CASCADE,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    relpath TEXT,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_samples_category ON samples(category);
CREATE INDEX IF NOT EXISTS idx_samples_split ON samples(split);
CREATE INDEX IF NOT EXISTS idx_samples_health ON samples(health_status);
CREATE INDEX IF NOT EXISTS idx_samples_session ON samples(session_id);
CREATE INDEX IF NOT EXISTS idx_assets_sample_kind ON assets(sample_id, kind);
CREATE INDEX IF NOT EXISTS idx_issues_sample ON issues(sample_id);
CREATE INDEX IF NOT EXISTS idx_issues_code ON issues(code);
CREATE INDEX IF NOT EXISTS idx_issues_severity ON issues(severity);
"""
