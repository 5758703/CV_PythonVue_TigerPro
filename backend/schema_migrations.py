"""Small idempotent migrations needed by both the admin app and API gateway."""

from sqlalchemy import inspect, text


def migrate_schema(db):
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())

    def add_columns(table, specs):
        if table not in tables:
            return
        columns = {column["name"] for column in inspector.get_columns(table)}
        additions = [ddl for name, ddl in specs if name not in columns]
        if additions:
            with db.engine.begin() as connection:
                # SQLite accepts one ADD COLUMN clause per ALTER statement.
                for ddl in additions:
                    connection.execute(text(f"ALTER TABLE {table} {ddl}"))

    add_columns("ai_model", [
        ("task", "ADD COLUMN task VARCHAR(64) DEFAULT 'object-detection'"),
        ("library", "ADD COLUMN library VARCHAR(32) DEFAULT 'ultralytics'"),
    ])
    add_columns("reid_embedding", [("model_version", "ADD COLUMN model_version VARCHAR(255) NULL")])
    add_columns("training_dataset", [("source_path", "ADD COLUMN source_path VARCHAR(500) NULL")])
    add_columns("open_app", [
        ("ip_allowlist", "ADD COLUMN ip_allowlist TEXT NULL"),
        ("webhook_url", "ADD COLUMN webhook_url VARCHAR(500) NULL"),
        ("webhook_secret", "ADD COLUMN webhook_secret VARCHAR(128) NULL"),
        ("webhook_events", "ADD COLUMN webhook_events TEXT NULL"),
        ("domain_id", "ADD COLUMN domain_id VARCHAR(64) NULL"),
        ("category", "ADD COLUMN category VARCHAR(32) NULL"),
    ])
    add_columns("camera_topology", [
        ("edge_type", "ADD COLUMN edge_type VARCHAR(32) DEFAULT 'non_overlap'"),
    ])
    if "camera_topology" in tables:
        with db.engine.begin() as connection:
            connection.execute(text(
                "UPDATE camera_topology SET edge_type = 'non_overlap' "
                "WHERE edge_type IS NULL OR edge_type = ''"
            ))
