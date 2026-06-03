from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


def init_sqlite_database(db_path: Path) -> bool:
    """
    Initialize a new SQLite database file.
    
    Args:
        db_path: Path to the SQLite database file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create SQLite database file
        conn = sqlite3.connect(str(db_path))
        conn.close()
        
        logger.info(f"SQLite database initialized at: {db_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize SQLite database at {db_path}: {e}")
        return False


def generate_sqlite_db_path(base_dir: Optional[Path] = None) -> Path:
    """
    Generate a path for a new SQLite database file with a random name.
    
    Args:
        base_dir: Base directory for databases (defaults to api-server/internal/databases/)

    Returns:
        Path to the SQLite database file
    """
    if base_dir is None:
        # parent x3 of internal/features/project/sqlite_helper.py == internal/,
        # so this resolves to api-server/internal/databases/ (matches the file
        # service + chart-server allow-list).
        base_dir = Path(__file__).resolve().parent.parent.parent / "databases"
    
    # Create directory if it doesn't exist
    base_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate a random UUID for the filename
    db_filename = f"{uuid4()}.db"
    
    # Return path: databases/{random_uuid}.db
    return base_dir / db_filename


def get_sqlite_db_url_from_path(db_path: Path) -> str:
    """
    Get the SQLite database URL from a file path.
    
    Args:
        db_path: Path to the SQLite database file
        
    Returns:
        SQLite database URL with absolute path
        Format: sqlite:////absolute/path (4 slashes for Unix absolute paths)
    """
    # Get absolute path
    absolute_path = db_path.resolve()
    path_str = str(absolute_path)
    
    # SQLite URL convention:
    # - sqlite:///relative/path → relative path
    # - sqlite:////absolute/path → absolute path on Unix (4 slashes total)
    # We always use absolute paths for reliability
    if path_str.startswith('/'):
        # Unix absolute path: sqlite:/// + /path = sqlite:////path
        return f"sqlite:///{path_str}"
    else:
        # Windows or relative: sqlite:///path
        return f"sqlite:///{path_str}"
