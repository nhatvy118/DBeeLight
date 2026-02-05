"""Factory for creating database adapters based on connection string."""

from typing import Optional

from adapters.base import DatabaseAdapter
from adapters.postgres import PostgresAdapter
from adapters.sqlite import SQLiteAdapter


class DatabaseAdapterFactory:
    """
    Factory class for creating appropriate database adapters.
    
    Usage:
        adapter = DatabaseAdapterFactory.create("sqlite:///path/to/db.sqlite")
        adapter = DatabaseAdapterFactory.create("postgres://user:pass@host:5432/dbname")
    """

    @staticmethod
    def create(connection_string: str) -> DatabaseAdapter:
        """
        Create a database adapter based on the connection string.
        
        Args:
            connection_string: Database connection string. Supported formats:
                - SQLite: "sqlite:///path/to/db.sqlite" or just "/path/to/db.sqlite"
                - PostgreSQL: "postgres://user:password@host:port/database"
                              "postgresql://user:password@host:port/database"
        
        Returns:
            An instance of the appropriate DatabaseAdapter subclass.
        
        Raises:
            ValueError: If the connection string format is not recognized.
        """
        conn_str = connection_string.strip().lower()
        
        # Detect SQLite
        if conn_str.startswith("sqlite:"):
            return SQLiteAdapter()
        
        # Detect PostgreSQL
        if conn_str.startswith("postgres://") or conn_str.startswith("postgresql://"):
            return PostgresAdapter()
        
        # Try to detect by file extension (for SQLite)
        if conn_str.endswith(".db") or conn_str.endswith(".sqlite") or conn_str.endswith(".sqlite3"):
            return SQLiteAdapter()
        
        # Default to PostgreSQL for backwards compatibility
        # (assuming old connection strings without prefix)
        raise ValueError(
            f"Unrecognized database connection string format: '{connection_string}'. "
            "Use 'sqlite:///path/to/file.db' for SQLite or "
            "'postgres://user:pass@host:port/db' for PostgreSQL."
        )

    @staticmethod
    def create_postgres() -> PostgresAdapter:
        """Create a PostgreSQL adapter directly."""
        return PostgresAdapter()

    @staticmethod
    def create_sqlite() -> SQLiteAdapter:
        """Create a SQLite adapter directly."""
        return SQLiteAdapter()

    @staticmethod
    def detect_type(connection_string: str) -> str:
        """
        Detect the database type from a connection string.
        
        Returns:
            'sqlite', 'postgres', or 'unknown'
        """
        conn_str = connection_string.strip().lower()
        
        if conn_str.startswith("sqlite:"):
            return "sqlite"
        if conn_str.startswith("postgres://") or conn_str.startswith("postgresql://"):
            return "postgres"
        if conn_str.endswith(".db") or conn_str.endswith(".sqlite") or conn_str.endswith(".sqlite3"):
            return "sqlite"
        
        return "unknown"
