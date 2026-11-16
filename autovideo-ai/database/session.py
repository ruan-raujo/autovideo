from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.config import Config
from models.entities import Base
from database.migrations import migrate_stage2, migrate_stage3, migrate_stage4, migrate_stage5


def open_database(config: Config):
    migrate_stage2(config.database_path)
    migrate_stage3(config.database_path)
    migrate_stage4(config.database_path)
    migrate_stage5(config.database_path)
    engine = create_engine(
        URL.create("sqlite", database=str(config.database_path)),
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        # Explicit transactions also cover SELECT and DDL on Python's sqlite3.
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def begin_transaction(connection):
        # Short transactions, serialized writers: no read -> write upgrade races.
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
