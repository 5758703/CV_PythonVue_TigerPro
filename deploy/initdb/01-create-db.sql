-- Runs once on the first `db` start, after MySQL creates ${MYSQL_DATABASE}.
-- The app's own migration layer (schema_migrations.py) does the table work;
-- this only pins the character set to what backend/README.md asks for.
ALTER DATABASE cv_python_tigerpro CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
