"""Database adapters package with Factory Pattern."""

from adapters.base import DatabaseAdapter
from adapters.postgres import PostgresAdapter
from adapters.sqlite import SQLiteAdapter
from adapters.factory import DatabaseAdapterFactory

__all__ = [
    "DatabaseAdapter",
    "PostgresAdapter",
    "SQLiteAdapter",
    "DatabaseAdapterFactory",
]
