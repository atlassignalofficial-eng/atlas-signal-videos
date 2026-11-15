"""SQLite storage: connection, numbered migrations, audit log, backup."""
import json
import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).parent / "migrations"


def connect(path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # explicit transactions only
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn) -> int:
    """Apply every migrations/NNNN_*.sql newer than PRAGMA user_version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for f in sorted(MIGRATIONS.glob("*.sql")):
        n = int(f.name.split("_", 1)[0])
        if n <= current:
            continue
        try:
            conn.executescript(f"BEGIN;\n{f.read_text()}\nPRAGMA user_version = {n};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        current = n
    return current


def audit(conn, actor: str, action: str, **detail) -> None:
    conn.execute("INSERT INTO audit_log (actor, action, detail) VALUES (?, ?, ?)",
                 (actor, action, json.dumps(detail, default=str) if detail else None))


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(conn, key, value) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps(value)))


def backup(conn, dest) -> Path:
    """Consistent online copy of the live database."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(dest) as out:
        conn.backup(out)
    out.close()
    return dest
