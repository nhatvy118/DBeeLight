"""
MCP Database Server with Factory Pattern.

This module provides database tools via MCP using the Factory Pattern
to support both PostgreSQL and SQLite databases transparently.
"""

import sys
import logging
from pathlib import Path
from typing import Any, Optional

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add parent directory to path so we can import adapters when running as script
_this_dir = Path(__file__).parent.resolve()
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from mcp.server.fastmcp import FastMCP

from adapters import DatabaseAdapter, DatabaseAdapterFactory

# Default limit for SELECT queries to prevent large result sets
DEFAULT_LIMIT = 1000

# Initialize FastMCP server
mcp = FastMCP("database")

# Current database adapter instance (can be PostgreSQL or SQLite)
_adapter: Optional[DatabaseAdapter] = None


def get_adapter() -> DatabaseAdapter:
    """Get the current database adapter, raising error if not connected."""
    if _adapter is None:
        raise RuntimeError(
            "Database not connected. Please use 'connect_db' (PostgreSQL) or "
            "'connect_sqlite' (SQLite) tool first."
        )
    return _adapter


# =============================================================================
# Connection Management Tools
# =============================================================================


@mcp.tool()
async def connect_db(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str
) -> str:
    """Connect to a PostgreSQL database. You must call this first before using any other database operations.
    
    Args:
        host: Database host (e.g., "localhost" or "127.0.0.1")
        port: Database port (default PostgreSQL port is 5432)
        database: Database name
        username: Database username
        password: Database password
    """
    global _adapter
    
    # Disconnect existing adapter if any
    if _adapter is not None:
        await _adapter.disconnect()
    
    # Create PostgreSQL adapter
    _adapter = DatabaseAdapterFactory.create_postgres()
    result = await _adapter.connect(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password
    )
    
    if "Failed" in result or "Error" in result:
        _adapter = None
    
    return result


@mcp.tool()
async def connect_sqlite(file_path: str) -> str:
    """Connect to a SQLite database file. Creates the file if it doesn't exist.
    
    Args:
        file_path: Path to the SQLite database file (e.g., "/path/to/db.sqlite" or "sqlite:///path/to/db.sqlite")
    """
    global _adapter
    
    # Disconnect existing adapter if any
    if _adapter is not None:
        await _adapter.disconnect()
    
    # Create SQLite adapter
    _adapter = DatabaseAdapterFactory.create_sqlite()
    result = await _adapter.connect(file_path=file_path)
    
    if "Failed" in result or "Error" in result:
        _adapter = None
    
    return result


@mcp.tool()
async def get_connection_info() -> str:
    """Get current database connection information (without showing password)."""
    if _adapter is None:
        return "Not connected to any database. Please use 'connect_db' or 'connect_sqlite' tool first."
    return await _adapter.get_connection_info()


@mcp.tool()
async def disconnect_database() -> str:
    """Disconnect from the current database."""
    global _adapter
    if _adapter is None:
        return "No active database connection."
    result = await _adapter.disconnect()
    _adapter = None
    return result


# =============================================================================
# Schema Operations
# =============================================================================


@mcp.tool()
async def list_tables() -> str:
    """List all tables in the database."""
    adapter = get_adapter()
    return await adapter.list_tables()


@mcp.tool()
async def describe_table(table_name: str) -> str:
    """Get structure of a table (columns, types, constraints).
    
    Args:
        table_name: Name of the table to describe
    """
    adapter = get_adapter()
    return await adapter.describe_table(table_name)


@mcp.tool()
async def get_schema() -> str:
    """Get the complete database schema (all tables, columns, constraints, etc.)."""
    adapter = get_adapter()
    return await adapter.get_schema()


@mcp.tool()
async def get_table_stats(table_name: str) -> str:
    """Get statistics about a table (row count, size, etc.).
    
    Args:
        table_name: Name of the table
    """
    adapter = get_adapter()
    return await adapter.get_table_stats(table_name)


# =============================================================================
# DDL Operations (Create, Alter Tables)
# =============================================================================


@mcp.tool()
async def create_table(
    table_name: str,
    columns: str,
    primary_key: Optional[str] = None
) -> str:
    """Create a new table in the database.
    
    Args:
        table_name: Name of the table to create
        columns: Column definitions in SQL format (e.g., "id INTEGER PRIMARY KEY, name TEXT, email TEXT")
        primary_key: Optional primary key column name (if not specified in columns)
    """
    adapter = get_adapter()
    return await adapter.create_table(table_name, columns, primary_key)


@mcp.tool()
async def alter_table(
    action: str,
    table_name: str,
    column_name: str,
    column_def: Optional[str] = None,
    new_column_name: Optional[str] = None
) -> str:
    """Alter a table structure (add, drop, modify, rename columns).
    
    Args:
        action: Action to perform - "add_column", "drop_column", "modify_column", "rename_column"
        table_name: Name of the table to alter
        column_name: Name of the column (for add/modify/drop/rename)
        column_def: Column definition (required for "add_column" and "modify_column")
                   Examples:
                   - "VARCHAR(100)" for add_column
                   - "VARCHAR(200)" or "SET NOT NULL" for modify_column
        new_column_name: New name for the column (required for "rename_column")
    
    Examples:
        - Add column: action="add_column", column_name="email", column_def="VARCHAR(255)"
        - Drop column: action="drop_column", column_name="old_column"
        - Modify column: action="modify_column", column_name="name", column_def="VARCHAR(200)"
        - Rename column: action="rename_column", column_name="old_name", new_column_name="new_name"
    
    Note: SQLite has limited ALTER TABLE support (no modify_column).
    """
    adapter = get_adapter()
    return await adapter.alter_table(action, table_name, column_name, column_def, new_column_name)


@mcp.tool()
async def create_db_from_spec(spec_text: str) -> str:
    """Create database schema from a specification text (SQL DDL statements).
    
    Args:
        spec_text: SQL DDL statements to create tables, constraints, etc.
    """
    adapter = get_adapter()
    return await adapter.create_from_spec(spec_text)


# =============================================================================
# DML Operations (Insert, Select, Update, Delete)
# =============================================================================


@mcp.tool()
async def insert_data(
    table_name: str,
    data: dict[str, Any]
) -> str:
    """Insert data into a table.
    
    Args:
        table_name: Name of the table
        data: Dictionary with column names as keys and values to insert.
              Date/datetime values can be provided as:
              - String in format "YYYY-MM-DD" for dates
              - String in format "YYYY-MM-DD HH:MM:SS" for datetimes
              - Python date/datetime objects
    """
    adapter = get_adapter()
    return await adapter.insert_data(table_name, data)


@mcp.tool()
async def select_data(
    table_name: str,
    columns: str = "*",
    where_clause: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    order_by: Optional[str] = None
) -> str:
    """Select data from a table.

    Args:
        table_name: Name of the table
        columns: Column names to select (default: "*")
        where_clause: Optional WHERE clause (e.g., "age > 18")
        limit: Number of rows to return (default: 1000)
        order_by: Optional ORDER BY clause (e.g., "name ASC")
    """
    adapter = get_adapter()
    return await adapter.select_data(table_name, columns, where_clause, limit, order_by)


@mcp.tool()
async def update_data(
    table_name: str,
    data: dict[str, Any],
    where_clause: str
) -> str:
    """Update data in a table.
    
    Args:
        table_name: Name of the table
        data: Dictionary with column names and new values.
              Date/datetime values can be provided as:
              - String in format "YYYY-MM-DD" for dates
              - String in format "YYYY-MM-DD HH:MM:SS" for datetimes
              - Python date/datetime objects
        where_clause: WHERE clause to identify rows to update (e.g., "id = 1")
    """
    adapter = get_adapter()
    return await adapter.update_data(table_name, data, where_clause)


@mcp.tool()
async def delete_data(
    table_name: str,
    where_clause: str
) -> str:
    """Delete data from a table.
    
    Args:
        table_name: Name of the table
        where_clause: WHERE clause to identify rows to delete (e.g., "id = 1")
    """
    adapter = get_adapter()
    return await adapter.delete_data(table_name, where_clause)


@mcp.tool()
async def preview_table(table_name: str, limit: int = 10) -> str:
    """Preview a table with a limited number of rows.
    
    Args:
        table_name: Name of the table
        limit: Number of rows to preview (default: 10)
    """
    adapter = get_adapter()
    return await adapter.preview_table(table_name, limit)


# =============================================================================
# Query Execution
# =============================================================================


def _add_limit(query: str) -> str:
    """Auto-add LIMIT to SELECT queries if not present."""
    query = query.strip()
    query_upper = query.upper()

    # Only add limit to SELECT queries
    if not query_upper.startswith("SELECT"):
        return query

    # Skip if already has LIMIT
    if "LIMIT" in query_upper:
        return query

    # Add LIMIT
    return f"{query} LIMIT {DEFAULT_LIMIT}"


@mcp.tool()
async def execute_query(query: str) -> str:
    """Execute a custom SQL query.

    Args:
        query: SQL query to execute
    """
    # Auto-add LIMIT to prevent large result sets
    query = _add_limit(query)

    adapter = get_adapter()
    return await adapter.execute_query(query)


@mcp.tool()
async def execute_query_no_limit(query: str) -> str:
    """Execute a SELECT query WITHOUT auto-LIMIT (for exports).

    Args:
        query: SQL SELECT query to execute (no limit will be added)
    """
    adapter = get_adapter()
    return await adapter.execute_query(query)


@mcp.tool()
async def export_table_to_excel(
    table_name: str,
    columns: str = "*",
    where_clause: str | None = None
) -> dict:
    """Export table data to Excel file. Returns dict with base64 content and filename.

    Args:
        table_name: Name of the table to export
        columns: Column names to export (default: "*")
        where_clause: Optional WHERE clause to filter data
    """
    import base64
    import io
    import json
    import logging
    import pandas as pd

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        # Build query
        query = f"SELECT {columns} FROM {table_name}"
        if where_clause:
            query += f" WHERE {where_clause}"

        logger.info(f"[export_table_to_excel] table={table_name}, query={query}")

        # Execute query without limit
        adapter = get_adapter()
        result = await adapter.execute_query_no_limit(query)
        logger.info(f"[export_table_to_excel] query result length: {len(result)}")

        # Parse JSON result
        try:
            data = json.loads(result)
            if not isinstance(data, list):
                data = [data]
        except json.JSONDecodeError:
            import re
            match = re.search(r'\[.*\]', result, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                logger.error(f"[export_table_to_excel] parse error: {result[:200]}")
                return {"error": f"Could not parse query result: {result[:200]}"}

        logger.info(f"[export_table_to_excel] parsed {len(data)} rows")

        if not data:
            return {"error": "No data found"}

        # Create Excel
        df = pd.DataFrame(data)
        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)

        # Encode to base64
        b64 = base64.b64encode(output.read()).decode('utf-8')
        filename = f"{table_name}.xlsx"

        logger.info(f"[export_table_to_excel] success: {len(data)} rows, base64 length: {len(b64)}")

        return {
            "base64": b64,
            "filename": filename,
            "row_count": len(data)
        }
    except Exception as e:
        logger.error(f"[export_table_to_excel] ERROR: {str(e)}")
        return {"error": str(e)}


@mcp.tool()
async def run_mutation(sql: str) -> str:
    """Run a mutation query (INSERT, UPDATE, DELETE) and return affected rows.
    
    Args:
        sql: SQL mutation query (INSERT, UPDATE, or DELETE)
    """
    adapter = get_adapter()
    return await adapter.run_mutation(sql)


@mcp.tool()
async def validate_sql(sql: str) -> str:
    """Validate SQL syntax without executing it.
    
    Args:
        sql: SQL query to validate
    """
    adapter = get_adapter()
    return await adapter.validate_sql(sql)


@mcp.tool()
async def explain_sql(sql: str) -> str:
    """Explain the execution plan of a SQL query.
    
    Args:
        sql: SQL query to explain
    """
    adapter = get_adapter()
    return await adapter.explain_sql(sql)


# =============================================================================
# Additional Operations
# =============================================================================


@mcp.tool()
async def list_databases() -> str:
    """List all databases (PostgreSQL) or show current database (SQLite)."""
    adapter = get_adapter()
    return await adapter.list_databases()


@mcp.tool()
async def generate_schema_doc(format: str = "text") -> str:
    """Generate documentation for the database schema.
    
    Args:
        format: Output format - "text" or "markdown"
    """
    adapter = get_adapter()
    return await adapter.generate_schema_doc(format)


@mcp.tool()
async def manage_constraint(
    action: str,
    table_name: str,
    constraint_name: str,
    constraint_def: Optional[str] = None
) -> str:
    """Manage constraints (add, drop) on a table.
    
    Args:
        action: "add" or "drop"
        table_name: Name of the table
        constraint_name: Name of the constraint
        constraint_def: Constraint definition (required for "add", e.g., "CHECK (age > 0)")
    
    Note: SQLite does not support adding/dropping constraints after table creation.
    """
    adapter = get_adapter()
    return await adapter.manage_constraint(action, table_name, constraint_name, constraint_def)


@mcp.tool()
async def manage_trigger(
    action: str,
    trigger_name: str,
    table_name: str,
    trigger_def: Optional[str] = None
) -> str:
    """Manage triggers (create, drop) on a table.
    
    Args:
        action: "create" or "drop"
        trigger_name: Name of the trigger
        table_name: Name of the table
        trigger_def: Trigger definition (required for "create")
    """
    adapter = get_adapter()
    return await adapter.manage_trigger(action, trigger_name, table_name, trigger_def)


# =============================================================================
# Excel/CSV Import Tools
# =============================================================================

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


@mcp.tool()
async def import_excel_to_db(
    file_path: str,
    table_name: str,
    column_mapping: Optional[str] = None,
    if_exists: str = "append"
) -> str:
    """Import data from Excel file directly into database table.

    Args:
        file_path: Path to Excel file (.xlsx or .xls)
        table_name: Target database table name
        column_mapping: Optional mapping like "excel_col1:db_col1,excel_col2:db_col2"
        if_exists: What to do if table exists - "append", "fail", "replace" (default: "append")
    """
    if not PANDAS_AVAILABLE:
        return "Error: pandas is required. Please install: pip install pandas openpyxl"

    from pathlib import Path

    try:
        file = Path(file_path)
        if not file.exists():
            return f"Error: File not found at '{file_path}'"

        # Read Excel
        df = pd.read_excel(file_path)

        # Apply column mapping if provided
        if column_mapping:
            mappings = {}
            for pair in column_mapping.split(","):
                if ":" in pair:
                    exc, dbc = pair.split(":")
                    mappings[exc.strip()] = dbc.strip()
            df = df.rename(columns=mappings)

        columns = df.columns.tolist()
        records = df.to_dict(orient="records")

        # Get adapter and insert
        adapter = get_adapter()

        # Insert in batches
        batch_size = 100
        inserted = 0
        for i in range(0, len(records), batch_size):
            batch = records[i:i+batch_size]
            for record in batch:
                try:
                    await adapter.insert_data(table_name, record)
                    inserted += 1
                except Exception as e:
                    return f"Error inserting row {i}: {str(e)}"

        return f"Successfully imported {inserted} rows from '{file_path}' into table '{table_name}'. Columns: {columns}"
    except Exception as e:
        return f"Error importing Excel to database: {str(e)}"


@mcp.tool()
async def import_csv_to_db(
    file_path: str,
    table_name: str,
    column_mapping: Optional[str] = None,
    if_exists: str = "append",
    delimiter: str = ","
) -> str:
    """Import data from CSV file directly into database table.

    Args:
        file_path: Path to CSV file
        table_name: Target database table name
        column_mapping: Optional mapping like "csv_col1:db_col1,csv_col2:db_col2"
        if_exists: What to do if table exists - "append", "fail", "replace" (default: "append")
        delimiter: CSV delimiter (default: ",")
    """
    try:
        from pathlib import Path

        file = Path(file_path)
        if not file.exists():
            return f"Error: File not found at '{file_path}'"

        # Read CSV
        df = pd.read_csv(file_path, delimiter=delimiter)

        # Apply column mapping if provided
        if column_mapping:
            mappings = {}
            for pair in column_mapping.split(","):
                if ":" in pair:
                    exc, dbc = pair.split(":")
                    mappings[exc.strip()] = dbc.strip()
            df = df.rename(columns=mappings)

        columns = df.columns.tolist()
        records = df.to_dict(orient="records")

        # Get adapter and insert
        adapter = get_adapter()

        # Insert in batches
        batch_size = 100
        inserted = 0
        for i in range(0, len(records), batch_size):
            batch = records[i:i+batch_size]
            for record in batch:
                try:
                    await adapter.insert_data(table_name, record)
                    inserted += 1
                except Exception as e:
                    return f"Error inserting row {i}: {str(e)}"

        return f"Successfully imported {inserted} rows from '{file_path}' into table '{table_name}'. Columns: {columns}"
    except ImportError:
        return "Error: pandas is required. Please install: pip install pandas"
    except Exception as e:
        return f"Error importing CSV to database: {str(e)}"


# =============================================================================
# Main Entry Point
# =============================================================================


def main():
    """Initialize and run the MCP server."""
    mcp.run(transport='stdio')


if __name__ == "__main__":
    main()
