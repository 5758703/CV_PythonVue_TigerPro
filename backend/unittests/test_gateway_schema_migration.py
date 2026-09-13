import sqlite3

from sqlalchemy import inspect


def test_gateway_startup_migrates_legacy_open_app_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy-gateway.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE open_app ("
            "id INTEGER PRIMARY KEY, app_id VARCHAR(64) NOT NULL, name VARCHAR(128) NOT NULL, "
            "status VARCHAR(1), scopes TEXT, qps_limit INTEGER, daily_limit INTEGER, remark VARCHAR(255))"
        )

    import gateway_app

    monkeypatch.setattr(
        gateway_app.Config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{db_path.as_posix()}",
    )
    app = gateway_app.create_gateway_app()
    with app.app_context():
        columns = {column["name"] for column in inspect(gateway_app.db.engine).get_columns("open_app")}
        tables = set(inspect(gateway_app.db.engine).get_table_names())
        assert "ip_allowlist" in columns
        assert {"open_api_nonce", "open_api_rate_bucket"} <= tables

    # A second startup must be harmless.
    gateway_app.create_gateway_app()
