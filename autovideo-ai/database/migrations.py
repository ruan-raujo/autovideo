"""Versioned, backed-up migration of the stage-1 jobs CHECK constraint."""
import sqlite3
from datetime import datetime

from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateTable

from models.entities import Job


def migrate_stage2(path):
    if not path.exists():
        return
    connection = sqlite3.connect(path, timeout=15)
    try:
        row = connection.execute("SELECT sql FROM sqlite_master WHERE name='jobs'").fetchone()
        if not row or "'completed'" in row[0]:
            return
        backup_path = path.with_name(f"before-stage2-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3")
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            ddl = str(CreateTable(Job.__table__).compile(dialect=sqlite.dialect()))
            connection.execute(ddl.replace("CREATE TABLE jobs", "CREATE TABLE jobs_stage2", 1))
            old_columns = [row[1] for row in connection.execute("PRAGMA table_info(jobs)")]
            names = ", ".join(f'"{name}"' for name in old_columns)
            connection.execute(f"INSERT INTO jobs_stage2 ({names}) SELECT {names} FROM jobs")
            connection.execute("DROP TABLE jobs")
            connection.execute("ALTER TABLE jobs_stage2 RENAME TO jobs")
            connection.execute("CREATE INDEX ix_jobs_status ON jobs(status)")
            connection.execute("CREATE INDEX ix_jobs_created_at ON jobs(created_at)")
            connection.execute("PRAGMA user_version=2")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Migração abortada: referências inválidas no banco.")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        connection.execute("PRAGMA foreign_keys=ON")
    finally:
        connection.close()


def migrate_stage3(path):
    if not path.exists():
        return
    with sqlite3.connect(path, timeout=15) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(jobs)")]
        if columns and "render_languages" not in columns:
            backup_path = path.with_name(f"before-stage3-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3")
            with sqlite3.connect(backup_path) as backup:
                connection.backup(backup)
            connection.execute("ALTER TABLE jobs ADD COLUMN render_languages JSON NOT NULL DEFAULT '[\"PT\"]'")
            connection.execute("PRAGMA user_version=3")


def migrate_stage4(path):
    if not path.exists():
        return
    with sqlite3.connect(path, timeout=15) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(jobs)")]
        if columns and "generation_options" not in columns:
            with sqlite3.connect(path.with_name(f"before-stage4-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3")) as backup:
                connection.backup(backup)
            connection.execute("ALTER TABLE jobs ADD COLUMN generation_options JSON")
            connection.execute("PRAGMA user_version=4")


def migrate_stage5(path):
    if not path.exists(): return
    with sqlite3.connect(path, timeout=15) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(jobs)")]
        if columns and "batch_id" not in columns:
            with sqlite3.connect(path.with_name(f"before-stage5-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3")) as backup:
                connection.backup(backup)
            connection.execute("ALTER TABLE jobs ADD COLUMN batch_id VARCHAR(36)")
            connection.execute("CREATE INDEX IF NOT EXISTS ix_jobs_batch_id ON jobs(batch_id)")
            connection.execute("PRAGMA user_version=5")
