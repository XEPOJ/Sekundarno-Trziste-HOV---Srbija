import sqlite3
from datetime import date
from pathlib import Path

import pytest

from securities_analyzer.db.repo import (
    KeyCollisionError, data_range, get_meta, last_source_year, replace_year,
    set_meta, stored_count,
)
from securities_analyzer.db.schema import connect, init_schema
from securities_analyzer.db.seed import build_seed, ensure_user_db
from tests.factories import load_rows, make_row, rows_to_csv


def test_schema_objects(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert {"trades", "securities", "meta", "saved_queries"} <= names
    assert get_meta(conn, "schema_version") == "2"


def test_replace_year_inserts_and_derives_columns(conn):
    r = make_row(settlement_date=date(2023, 6, 19))
    res = replace_year(conn, 2023, [r])
    assert (res.added, res.removed, res.unchanged) == (1, 0, 0)
    row = conn.execute("SELECT * FROM trades").fetchone()
    assert row["trade_date"] == "2023-06-15"
    assert row["source_year"] == 2023
    assert row["settlement_lag_days"] == 4
    assert row["quality_flag"] == "OK"


def test_replace_year_reports_diff(conn):
    a, b, c = (make_row(isin=f"RSMFRSD0000{i}") for i in (1, 2, 3))
    replace_year(conn, 2023, [a, b])
    res = replace_year(conn, 2023, [b, c])
    assert (res.added, res.removed, res.unchanged) == (1, 1, 1)
    assert stored_count(conn, 2023) == 2


def test_replace_year_is_atomic_on_key_collision(conn):
    a = make_row()
    replace_year(conn, 2023, [a])
    other = make_row(isin="RSMFRSD00009")
    with pytest.raises(KeyCollisionError):
        replace_year(conn, 2024, [other, a])      # `a` already stored under 2023
    assert stored_count(conn, 2024) == 0
    assert stored_count(conn, 2023) == 1


def test_collision_rolls_back_a_populated_target_year(conn):
    stored_2023 = make_row()
    originals = [make_row(trade_date=date(2024, 3, 1), settlement_date=date(2024, 3, 1),
                          isin=f"RSMFRSD0010{i}") for i in range(3)]
    replace_year(conn, 2023, [stored_2023])
    replace_year(conn, 2024, originals)
    new_row = make_row(trade_date=date(2024, 4, 1), settlement_date=date(2024, 4, 1),
                       isin="RSMFRSD00200")
    with pytest.raises(KeyCollisionError):
        replace_year(conn, 2024, [new_row, stored_2023])
    keys = {r["isin"] for r in conn.execute("SELECT isin FROM trades WHERE source_year = 2024")}
    assert keys == {r.isin for r in originals}
    assert stored_count(conn, 2023) == 1


def test_last_source_year_and_range(conn):
    assert last_source_year(conn) is None
    assert data_range(conn) == (None, None, 0)
    load_rows(conn, [
        make_row(trade_date=date(2022, 12, 30), settlement_date=date(2023, 1, 3)),
        make_row(trade_date=date(2023, 6, 15), isin="RSMFRSD00002"),
    ])
    assert last_source_year(conn) == 2023
    assert data_range(conn) == ("2022-12-30", "2023-06-15", 2)


def test_meta_roundtrip(conn):
    set_meta(conn, "k", "v1")
    set_meta(conn, "k", "v2")
    assert get_meta(conn, "k") == "v2"
    assert get_meta(conn, "missing") is None


def test_securities_view(conn):
    load_rows(conn, [make_row(), make_row(trade_date=date(2023, 6, 16), settlement_date=date(2023, 6, 16))])
    rows = conn.execute("SELECT * FROM securities").fetchall()
    assert len(rows) == 1 and rows[0]["trade_rows"] == 2


def test_build_seed_and_ensure_user_db(tmp_path):
    csv_dir = tmp_path / "raw"
    csv_dir.mkdir()
    (csv_dir / "GovermentSecuritySecondaryTrade_2022.csv").write_bytes(
        rows_to_csv([make_row(trade_date=date(2022, 5, 5), settlement_date=date(2022, 5, 5))]))
    (csv_dir / "GovermentSecuritySecondaryTrade_2023.csv").write_bytes(rows_to_csv([make_row()]))
    seed = tmp_path / "seed.db"
    assert build_seed(csv_dir, seed) == 2

    user = tmp_path / "user" / "data.db"
    ensure_user_db(user, seed)                       # copies the seed
    c = connect(user)
    assert data_range(c)[2] == 2
    replace_year(c, 2023, [])                        # user modifies their DB
    c.close()
    ensure_user_db(user, seed)                       # must NOT overwrite
    c = connect(user)
    assert data_range(c)[2] == 1
    c.close()


def test_ensure_user_db_failed_copy_leaves_no_db_and_no_tmp(tmp_path, monkeypatch):
    seed = tmp_path / "seed.db"
    seed.write_bytes(b"seed")
    user = tmp_path / "user" / "data.db"

    def boom(src, dst, *a, **kw):
        Path(dst).write_bytes(b"partial")          # simulate a half-written copy
        raise OSError("disk full")

    monkeypatch.setattr("securities_analyzer.db.seed.shutil.copyfile", boom)
    with pytest.raises(OSError):
        ensure_user_db(user, seed)
    assert not user.exists()
    assert list(user.parent.iterdir()) == []


def test_ensure_user_db_leaves_no_tmp_file_on_success(tmp_path):
    seed = tmp_path / "seed.db"
    build_seed_dir = tmp_path / "raw"
    build_seed_dir.mkdir()
    (build_seed_dir / "GovermentSecuritySecondaryTrade_2023.csv").write_bytes(rows_to_csv([make_row()]))
    build_seed(build_seed_dir, seed)
    user = tmp_path / "user" / "data.db"
    ensure_user_db(user, seed)
    assert [p.name for p in user.parent.iterdir()] == ["data.db"]


def test_build_seed_fails_without_csv_files(tmp_path):
    (tmp_path / "raw").mkdir()
    with pytest.raises(ValueError, match="CSV"):
        build_seed(tmp_path / "raw", tmp_path / "seed.db")


def test_build_seed_fails_when_no_rows_imported(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "GovermentSecuritySecondaryTrade_2023.csv").write_bytes(rows_to_csv([]))
    with pytest.raises(ValueError, match="0 redova|0 rows"):
        build_seed(raw, tmp_path / "seed.db")


def test_ensure_user_db_without_seed_creates_empty(tmp_path):
    user = tmp_path / "x" / "data.db"
    ensure_user_db(user, None)
    c = connect(user)
    assert data_range(c) == (None, None, 0)
    c.close()


def test_v1_database_is_migrated_in_place(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE saved_queries (name TEXT PRIMARY KEY, filter_json TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema_version', '1');
        INSERT INTO saved_queries VALUES ('stari', '{"currency": ["RSD"]}');
    """)
    raw.close()
    conn = connect(path)
    init_schema(conn)
    init_schema(conn)                                    # idempotent
    assert get_meta(conn, "schema_version") == "2"
    row = conn.execute("SELECT name, filter_json, pivot_json FROM saved_queries").fetchone()
    assert (row["name"], row["filter_json"], row["pivot_json"]) == ("stari", '{"currency": ["RSD"]}', None)
    conn.close()


def test_fresh_database_has_pivot_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(saved_queries)")]
    assert cols == ["name", "filter_json", "pivot_json"]


def test_ensure_user_db_migrates_existing_v1_database(tmp_path):
    path = tmp_path / "data.db"
    raw = sqlite3.connect(path)
    raw.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE saved_queries (name TEXT PRIMARY KEY, filter_json TEXT NOT NULL);
        INSERT INTO meta VALUES ('schema_version', '1');
    """)
    raw.close()
    ensure_user_db(path, None)
    c = connect(path)
    assert get_meta(c, "schema_version") == "2"
    assert "pivot_json" in [r[1] for r in c.execute("PRAGMA table_info(saved_queries)")]
    c.close()
