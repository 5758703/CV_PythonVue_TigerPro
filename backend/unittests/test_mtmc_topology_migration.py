"""Executable old-schema coverage for the MTMC topology edge type migration."""
from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest
from sqlalchemy import inspect, text


@pytest.fixture
def legacy_topology_db(monkeypatch, tmp_path):
    from config import Config

    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{tmp_path / 'legacy.db'}")
    fake_seed = ModuleType("seed")
    fake_seed.init_seed = lambda: None
    monkeypatch.setitem(sys.modules, "seed", fake_seed)
    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")

    with app_module.app.app_context():
        with app_module.db.engine.begin() as conn:
            conn.execute(text("DROP TABLE camera_topology"))
            conn.execute(text("""
                CREATE TABLE camera_topology (
                    id INTEGER PRIMARY KEY,
                    from_camera_id INTEGER NOT NULL,
                    to_camera_id INTEGER NOT NULL,
                    min_transit_sec FLOAT,
                    max_transit_sec FLOAT,
                    weight FLOAT,
                    remark VARCHAR(255),
                    status VARCHAR(1),
                    create_time DATETIME
                )
            """))
            conn.execute(text("""
                INSERT INTO camera_topology
                    (id, from_camera_id, to_camera_id, min_transit_sec, max_transit_sec, weight, status)
                VALUES (1, 1, 2, 0, 30, 0.8, '0')
            """))
        yield app_module

    with app_module.app.app_context():
        app_module.db.session.remove()
        app_module.db.engine.dispose()
    sys.modules.pop("app", None)


def test_migrate_adds_and_backfills_topology_edge_type(legacy_topology_db):
    app_module = legacy_topology_db

    with app_module.app.app_context():
        app_module._migrate(app_module.db)
        columns = {c["name"] for c in inspect(app_module.db.engine).get_columns("camera_topology")}
        edge_type = app_module.db.session.execute(
            text("SELECT edge_type FROM camera_topology WHERE id = 1")
        ).scalar_one()

    assert "edge_type" in columns
    assert edge_type == "non_overlap"


def test_migrate_topology_edge_type_is_idempotent(legacy_topology_db):
    app_module = legacy_topology_db

    with app_module.app.app_context():
        app_module._migrate(app_module.db)
        app_module._migrate(app_module.db)
        edge_type = app_module.db.session.execute(
            text("SELECT edge_type FROM camera_topology WHERE id = 1")
        ).scalar_one()

    assert edge_type == "non_overlap"
