"""Persistent project memory with dedup, corrections, expiry and provenance.

kind examples: decision, learning, research, positioning, failure.
"""
import json


def remember(conn, kind, key, value, source=None, expires_at=None) -> int:
    """Store a fact. Same value again -> no-op. New value -> supersedes the old row."""
    blob = json.dumps(value, sort_keys=True, default=str)
    old = conn.execute(
        "SELECT id, value FROM memory WHERE kind = ? AND key = ? AND superseded_by IS NULL",
        (kind, key)).fetchone()
    if old and old["value"] == blob:
        return old["id"]
    conn.execute("BEGIN")
    try:
        new_id = conn.execute(
            "INSERT INTO memory (kind, key, value, source, expires_at) VALUES (?, ?, ?, ?, ?)",
            (kind, key, blob, source, expires_at)).lastrowid
        if old:
            conn.execute("UPDATE memory SET superseded_by = ? WHERE id = ?", (new_id, old["id"]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return new_id


def recall(conn, kind, key=None) -> list[dict]:
    """Current, unexpired entries of a kind (optionally one key), newest first."""
    sql = ("SELECT * FROM memory WHERE kind = ? AND superseded_by IS NULL "
           "AND (expires_at IS NULL OR expires_at > datetime('now'))")
    args = [kind]
    if key is not None:
        sql += " AND key = ?"
        args.append(key)
    rows = conn.execute(sql + " ORDER BY id DESC", args).fetchall()
    return [{**dict(r), "value": json.loads(r["value"])} for r in rows]


def history(conn, kind, key) -> list[dict]:
    """Every version of a fact, oldest first (corrections included)."""
    rows = conn.execute("SELECT * FROM memory WHERE kind = ? AND key = ? ORDER BY id",
                        (kind, key)).fetchall()
    return [{**dict(r), "value": json.loads(r["value"])} for r in rows]
