import shutil

import pytest

from bpu import config, db
from bpu.config import ROOT


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "settings.toml", tmp_path / "config" / "settings.toml")
    c = config.load(tmp_path / "config" / "settings.toml")
    c["pipeline"]["retry_backoff_seconds"] = 0
    return c


@pytest.fixture
def conn(cfg):
    c = db.connect(cfg["paths"]["db"])
    yield c
    c.close()
