"""Abstract base class for database adapters."""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple


class DatabaseAdapter(ABC):
    """
    Abstract base class defining the interface for all database adapters.
    Each adapter (PostgreSQL, SQLite, etc.) must implement these methods.
    """

    @abstractmethod
    async def connect(self, **kwargs) -> str:
        """Connect to the database. Returns success/error message."""
        pass

    @abstractmethod
    async def disconnect(self) -> str:
        """Disconnect from the database. Returns success/error message."""
        pass

    @abstractmethod
    async def get_connection_info(self) -> str:
        """Get current connection information (without sensitive data)."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if currently connected to a database."""
        pass

    # --- Schema operations ---

    @abstractmethod
    async def list_tables(self) -> str:
        """List all tables in the database."""
        pass

    @abstractmethod
    async def describe_table(self, table_name: str) -> str:
        """Get structure of a table (columns, types, constraints)."""
        pass

    @abstractmethod
    async def get_schema(self) -> str:
        """Get the complete database schema."""
        pass

    @abstractmethod
    async def get_table_stats(self, table_name: str) -> str:
        """Get statistics about a table (row count, size)."""
        pass

    # --- DDL operations ---

    @abstractmethod
    async def create_table(self, table_name: str, columns: str, primary_key: Optional[str] = None) -> str:
        """Create a new table."""
        pass

    @abstractmethod
    async def alter_table(
        self,
        action: str,
        table_name: str,
        column_name: str,
        column_def: Optional[str] = None,
        new_column_name: Optional[str] = None,
    ) -> str:
        """Alter table structure (add/drop/modify/rename column)."""
        pass

    @abstractmethod
    async def create_from_spec(self, spec_text: str) -> str:
        """Create database schema from SQL DDL statements."""
        pass

    # --- DML operations ---

    @abstractmethod
    async def select_data(
        self,
        table_name: str,
        columns: str = "*",
        where_clause: Optional[str] = None,
        limit: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> str:
        """Select data from a table."""
        pass

    @abstractmethod
    async def insert_data(self, table_name: str, data: Dict[str, Any]) -> str:
        """Insert data into a table."""
        pass

    @abstractmethod
    async def update_data(self, table_name: str, data: Dict[str, Any], where_clause: str) -> str:
        """Update data in a table."""
        pass

    @abstractmethod
    async def delete_data(self, table_name: str, where_clause: str) -> str:
        """Delete data from a table."""
        pass

    @abstractmethod
    async def preview_table(self, table_name: str, limit: int = 10) -> str:
        """Preview a table with limited rows."""
        pass

    # --- Query execution ---

    @abstractmethod
    async def execute_query(self, query: str) -> str:
        """Execute a custom SQL query."""
        pass

    @abstractmethod
    def stream_query(
        self, query: str, chunk_size: int = 5000
    ) -> AsyncIterator[Tuple[List[str], List[Any]]]:
        """Stream a SELECT query in chunks to avoid loading the full result into RAM.

        Yields ``(columns, rows)`` where ``columns`` is the canonical column list
        (same on every yield) and ``rows`` is a list of up to ``chunk_size`` items
        whose elements support key-based indexing (e.g. ``row["col"]``).
        Empty results yield nothing.
        """
        ...

    @abstractmethod
    async def run_mutation(self, sql: str) -> str:
        """Run a mutation query (INSERT/UPDATE/DELETE)."""
        pass

    @abstractmethod
    async def validate_sql(self, sql: str) -> str:
        """Validate SQL syntax without executing."""
        pass

    @abstractmethod
    async def explain_sql(self, sql: str) -> str:
        """Explain the execution plan of a SQL query."""
        pass

    # --- Additional operations ---

    @abstractmethod
    async def list_databases(self) -> str:
        """List all databases (PostgreSQL) or current file (SQLite)."""
        pass

    @abstractmethod
    async def generate_schema_doc(self, format: str = "text") -> str:
        """Generate documentation for the database schema."""
        pass

    @abstractmethod
    async def manage_constraint(
        self,
        action: str,
        table_name: str,
        constraint_name: str,
        constraint_def: Optional[str] = None,
    ) -> str:
        """Manage constraints (add/drop)."""
        pass

    @abstractmethod
    async def manage_trigger(
        self,
        action: str,
        trigger_name: str,
        table_name: str,
        trigger_def: Optional[str] = None,
    ) -> str:
        """Manage triggers (create/drop)."""
        pass
