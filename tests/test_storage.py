import sqlite3

import pytest

from bpu import config, db, memory


def test_migrations_apply_once_and_are_idempotent(conn):
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    assert v >= 1 and db.migrate(conn) == v
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"jobs", "stage_runs", "approvals", "audit_log", "memory", "ideas",
            "publications", "analytics_snapshots", "experiments", "settings"} <= tables


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "0001_ok.sql").write_text("CREATE TABLE a (x);")
    (mig / "0002_bad.sql").write_text("CREATE TABLE b (x); THIS IS NOT SQL;")
    monkeypatch.setattr(db, "MIGRATIONS", mig)
    with pytest.raises(sqlite3.OperationalError):
        db.connect(tmp_path / "t.sqlite3")
    c = sqlite3.connect(tmp_path / "t.sqlite3")
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name = 'b'").fetchone()


def test_memory_dedup_correction_and_expiry(conn):
    a = memory.remember(conn, "decision", "niche", "engineering", source="owner")
    assert memory.remember(conn, "decision", "niche", "engineering") == a  # dedup
    b = memory.remember(conn, "decision", "niche", "engineering + maps", source="analytics")
    assert b != a
    assert [m["value"] for m in memory.recall(conn, "decision", "niche")] == ["engineering + maps"]
    hist = memory.history(conn, "decision", "niche")
    assert hist[0]["superseded_by"] == b and hist[1]["source"] == "analytics"

    memory.remember(conn, "research", "trend", {"x": 1}, expires_at="2000-01-01")
    assert memory.recall(conn, "research") == []


def test_settings_and_backup(conn, tmp_path):
    db.set_setting(conn, "paused", True)
    assert db.get_setting(conn, "paused") is True
    dest = db.backup(conn, tmp_path / "b" / "copy.sqlite3")
    copy = sqlite3.connect(dest)
    assert copy.execute("SELECT value FROM settings WHERE key = 'paused'").fetchone()[0] == "true"


def test_config_validation(tmp_path):
    (tmp_path / "config").mkdir()
    bad = tmp_path / "config" / "settings.toml"
    bad.write_text('[publishing]\nmode = "yolo"\n')
    with pytest.raises(ValueError, match="channel.id is missing"):
        config.load(bad)
    good = config.load(config.ROOT / "config" / "settings.toml")
    assert good["publishing"]["mode"] == "dry_run"  # shipped default must stay safe
    assert good["paths"]["db"].is_absolute()
