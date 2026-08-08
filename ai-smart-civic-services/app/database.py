"""
DatabaseManager for AI Smart Civic Services.
Handles SQLite connection, engine creation, table initialization, schema migration, and session lifecycle.
"""
import os
import logging
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from app.models import Base

logger = logging.getLogger("database")
DEFAULT_DB_PATH = "sqlite:///./civic_services.db"


class DatabaseManager:
    """Encapsulates all database operations, engine creation, and session management."""

    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv("DATABASE_URL", DEFAULT_DB_PATH)
        connect_args = {}
        if self.db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        self.engine = create_engine(self.db_url, connect_args=connect_args, echo=False)
        self.SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def init_db(self) -> None:
        """Create all database tables and perform lightweight non-destructive migrations."""
        Base.metadata.create_all(bind=self.engine)
        
        # Ensure optional and relational fields exist if database was previously initialized with earlier schema
        if self.db_url.startswith("sqlite"):
            with self.engine.connect() as conn:
                new_columns = [
                    ("citizen_id", "INTEGER"),
                    ("phone", "VARCHAR(50)"),
                    ("latitude", "FLOAT"),
                    ("longitude", "FLOAT"),
                    ("image_url", "TEXT"),
                ]
                for col_name, col_type in new_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE complaints ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                        logger.info(f"Added column {col_name} to complaints table.")
                    except Exception:
                        # Column already present
                        pass

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Provide a transactional scope around a series of operations."""
        session: Session = self.SessionFactory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_db_dependency(self) -> Generator[Session, None, None]:
        """FastAPI dependency for yielding database sessions."""
        session: Session = self.SessionFactory()
        try:
            yield session
        finally:
            session.close()


# Global default database manager
db_manager = DatabaseManager()


def get_db() -> Generator[Session, None, None]:
    """FastAPI route dependency."""
    yield from db_manager.get_db_dependency()
