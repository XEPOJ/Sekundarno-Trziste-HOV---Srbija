import os
from pathlib import Path

import pytest

from securities_analyzer.db.schema import connect, init_schema


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_schema(c)
    yield c
    c.close()


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test.db"
    c = connect(p)
    init_schema(c)
    c.close()
    return p


def find_raw_dir() -> Path | None:
    default = Path(__file__).resolve().parents[2] / "outputs" / "PowerBI_Data" / "RawData"
    d = Path(os.environ.get("SA_RAW_DIR", default))
    return d if d.is_dir() and list(d.glob("GovermentSecuritySecondaryTrade_*.csv")) else None


@pytest.fixture(scope="session")
def real_conn(tmp_path_factory):
    raw = find_raw_dir()
    if raw is None:
        pytest.skip("real NBS CSV files not available (set SA_RAW_DIR)")
    from securities_analyzer.db.seed import build_seed
    out = tmp_path_factory.mktemp("seed") / "seed.db"
    build_seed(raw, out)
    c = connect(out)
    yield c
    c.close()
