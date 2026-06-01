"""SQLite database adapter."""

import os
from typing import Any, Dict, List, Optional
from datetime import datetime, date
import aiosqlite

from adapters.base import DatabaseAdapter, is_ddl_statement


def _normalize_value(value: Any) -> Any:
    """Normalize value for database insertion, especially handling dates/datetimes."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        value_stripped = value.strip()
        if not value_stripped:
            return value
        # Keep dates as strings for SQLite
        return value
    return value


def _parse_sqlite_url(url: str) -> str:
    """Parse SQLite URL to extract file path.
    
    SQLite URL formats:
    - sqlite:////absolute/path → /absolute/path (Unix absolute, 4 slashes)
    - sqlite:///Users/path → /Users/path (Unix absolute, 3 slashes - common mistake)
    - sqlite:///relative/path → relative/path (3 slashes, truly relative)
    - sqlite:///C:/path → C:/path (Windows absolute)
    - /path/to/db.db → /path/to/db.db (plain path)
    """
    url = url.strip()
    
    # Handle sqlite:// prefix
    if url.startswith("sqlite://"):
        # Remove "sqlite://" prefix, leaving the path part
        path = url[len("sqlite://"):]
        
        # sqlite://// → //absolute/path → return /absolute/path
        if path.startswith("//"):
            return path[1:]
        
        # sqlite:/// → /something
        if path.startswith("/"):
            remaining = path[1:]  # Remove the first /
            
            # Check if this looks like an absolute Unix path (starts with common root dirs)
            # e.g., sqlite:///Users/... or sqlite:///home/... or sqlite:///var/...
            if remaining.startswith(("Users/", "home/", "var/", "tmp/", "opt/", "etc/", "usr/")):
                # This is actually an absolute path, restore the /
                return "/" + remaining
            
            # Otherwise treat as relative path
            return remaining
        
        return path
    
    # Plain path (no sqlite:// prefix)
    return url


class SQLiteAdapter(DatabaseAdapter):
    """SQLite database adapter using aiosqlite."""

    def __init__(self):
        self._db_path: Optional[str] = None

    def is_connected(self) -> bool:
        return self._db_path is not None

    async def connect(self, file_path: str = "", **kwargs) -> str:
        """Connect to SQLite database file."""
        try:
            db_path = _parse_sqlite_url(file_path)
            if not db_path:
                return "Error: file_path is required for SQLite connection."

            # Expand user path (~) and make absolute
            db_path = os.path.expanduser(db_path)
            db_path = os.path.abspath(db_path)

            # Ensure directory exists
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

            # Test connection (creates file if not exists)
            async with aiosqlite.connect(db_path) as conn:
                await conn.execute("SELECT 1")

            self._db_path = db_path
            return f"Successfully connected to SQLite database: {db_path}"
        except Exception as e:
            self._db_path = None
            return f"Failed to connect to SQLite database: {str(e)}"

    async def disconnect(self) -> str:
        self._db_path = None
        return "Disconnected from SQLite database."

    async def get_connection_info(self) -> str:
        if not self.is_connected():
            return "Not connected to any database."
        return f"""Current database connection:
- Type: SQLite
- File: {self._db_path}
- Status: Connected"""

    async def _run(self, query: str, params: tuple = ()) -> tuple[List[tuple], Optional[str]]:
        """Execute a query and return (rows, error_message)."""
        if not self._db_path:
            return [], "Database not connected."
        try:
            async with aiosqlite.connect(self._db_path) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(query, params)
                rows = await cursor.fetchall()
                await conn.commit()
                return rows, None
        except Exception as e:
            return [], str(e)

    async def _execute(self, query: str, params: tuple = ()) -> Optional[str]:
        """Execute a query without returning rows. Returns error message or None."""
        if not self._db_path:
            return "Database not connected."
        try:
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.execute(query, params)
                await conn.commit()
                return None
        except Exception as e:
            return str(e)

    # --- Schema operations ---

    async def list_tables(self) -> str:
        query = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        rows, error = await self._run(query)
        if error:
            return f"Error listing tables: {error}"
        if not rows:
            return "No tables found in the database."
        tables = [row[0] for row in rows]
        return f"Tables in database: {', '.join(tables)}"

    async def describe_table(self, table_name: str) -> str:
        query = f"PRAGMA table_info({table_name})"
        rows, error = await self._run(query)
        if error:
            return f"Error describing table: {error}"
        if not rows:
            return f"Table '{table_name}' not found."
        lines = []
        for row in rows:
            # row: (cid, name, type, notnull, dflt_value, pk)
            cid, name, col_type, notnull, default, pk = row
            info = f"- {name}: {col_type}"
            if pk:
                info += " PRIMARY KEY"
            if notnull:
                info += " NOT NULL"
            if default is not None:
                info += f" DEFAULT {default}"
            lines.append(info)
        return f"Structure of table '{table_name}':\n" + "\n".join(lines)

    async def get_schema(self) -> str:
        list_query = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        tables, error = await self._run(list_query)
        if error:
            return f"Error getting schema: {error}"
        if not tables:
            return "No tables found in the database."
        text = "Database Schema:\n\n"
        for (table_name,) in tables:
            pragma_query = f"PRAGMA table_info({table_name})"
            columns, err = await self._run(pragma_query)
            if err:
                text += f"Table: {table_name}\n  (Error: {err})\n\n"
                continue
            text += f"Table: {table_name}\n"
            for row in columns:
                cid, name, col_type, notnull, default, pk = row
                col_info = f"  - {name} ({col_type})"
                if pk:
                    col_info += " PK"
                if notnull:
                    col_info += " NOT NULL"
                if default is not None:
                    col_info += f" DEFAULT {default}"
                text += col_info + "\n"
            text += "\n"
        return text

    async def get_table_stats(self, table_name: str) -> str:
        count_query = f"SELECT COUNT(*) FROM {table_name}"
        rows, error = await self._run(count_query)
        if error:
            return f"Error getting table stats: {error}"
        row_count = rows[0][0] if rows else 0
        # SQLite doesn't have built-in size info like PostgreSQL
        return f"""Statistics for table '{table_name}':
- Row count: {row_count}
- (Note: SQLite does not expose detailed size info per table)"""

    # --- DDL operations ---

    async def create_table(self, table_name: str, columns: str, primary_key: Optional[str] = None) -> str:
        pk_constraint = f", PRIMARY KEY ({primary_key})" if primary_key else ""
        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({columns}{pk_constraint})"
        error = await self._execute(query)
        if error:
            return f"Error creating table: {error}"
        return f"Table '{table_name}' created successfully."

    async def alter_table(
        self,
        action: str,
        table_name: str,
        column_name: str,
        column_def: Optional[str] = None,
        new_column_name: Optional[str] = None,
    ) -> str:
        action_lower = action.lower()

        # SQLite has limited ALTER TABLE support
        if action_lower == "add_column":
            if not column_def:
                return "Error: column_def is required when adding a column."
            query = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
        elif action_lower == "drop_column":
            # SQLite 3.35+ supports DROP COLUMN
            query = f"ALTER TABLE {table_name} DROP COLUMN {column_name}"
        elif action_lower == "rename_column":
            if not new_column_name:
                return "Error: new_column_name is required when renaming a column."
            # SQLite 3.25+ supports RENAME COLUMN
            query = f"ALTER TABLE {table_name} RENAME COLUMN {column_name} TO {new_column_name}"
        elif action_lower in ("modify_column", "alter_column"):
            return "Error: SQLite does not support modifying column types directly. You need to recreate the table."
        else:
            return f"Error: action must be one of: 'add_column', 'drop_column', 'rename_column'. Got '{action}'"

        error = await self._execute(query)
        if error:
            return f"Error altering table: {error}"
        return f"Table '{table_name}' altered successfully."

    async def create_from_spec(self, spec_text: str) -> str:
        if not self._db_path:
            return "Database not connected."
        try:
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.executescript(spec_text)
                await conn.commit()
            return "Database schema created successfully from specification."
        except Exception as e:
            return f"Error creating database from spec: {str(e)}"

    # --- DML operations ---

    async def select_data(
        self,
        table_name: str,
        columns: str = "*",
        where_clause: Optional[str] = None,
        limit: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> str:
        query = f"SELECT {columns} FROM {table_name}"
        if where_clause:
            query += f" WHERE {where_clause}"
        if order_by:
            query += f" ORDER BY {order_by}"
        if limit:
            query += f" LIMIT {limit}"

        rows, error = await self._run(query)
        if error:
            return f"Error selecting data: {error}"
        if not rows:
            return f"No data found in '{table_name}'."

        results = [dict(row) for row in rows]
        return f"Found {len(results)} row(s):\n{results}"

    async def insert_data(self, table_name: str, data: Dict[str, Any]) -> str:
        if not self._db_path:
            return "Database not connected."
        try:
            normalized = {k: _normalize_value(v) for k, v in data.items()}
            columns = ", ".join(normalized.keys())
            placeholders = ", ".join(["?" for _ in normalized])
            values = list(normalized.values())
            query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
            async with aiosqlite.connect(self._db_path) as conn:
                cursor = await conn.execute(query, values)
                lastrowid = cursor.lastrowid
                await conn.commit()
            return f"Data inserted successfully into '{table_name}'. Last row ID: {lastrowid}"
        except Exception as e:
            return f"Error inserting data: {str(e)}"

    async def update_data(self, table_name: str, data: Dict[str, Any], where_clause: str) -> str:
        if not self._db_path:
            return "Database not connected."
        try:
            normalized = {k: _normalize_value(v) for k, v in data.items()}
            set_clauses = [f"{col} = ?" for col in normalized.keys()]
            values = list(normalized.values())
            query = f"UPDATE {table_name} SET {', '.join(set_clauses)} WHERE {where_clause}"
            async with aiosqlite.connect(self._db_path) as conn:
                cursor = await conn.execute(query, values)
                rowcount = cursor.rowcount
                await conn.commit()
            if rowcount == 0:
                return f"No rows updated in '{table_name}' (no rows matched WHERE clause)."
            return f"Updated {rowcount} row(s) in '{table_name}'."
        except Exception as e:
            return f"Error updating data: {str(e)}"

    async def delete_data(self, table_name: str, where_clause: str) -> str:
        if not self._db_path:
            return "Database not connected."
        try:
            query = f"DELETE FROM {table_name} WHERE {where_clause}"
            async with aiosqlite.connect(self._db_path) as conn:
                cursor = await conn.execute(query)
                rowcount = cursor.rowcount
                await conn.commit()
            if rowcount == 0:
                return f"No rows deleted from '{table_name}' (no rows matched WHERE clause)."
            return f"Deleted {rowcount} row(s) from '{table_name}'."
        except Exception as e:
            return f"Error deleting data: {str(e)}"

    async def preview_table(self, table_name: str, limit: int = 10) -> str:
        query = f"SELECT * FROM {table_name} LIMIT {limit}"
        rows, error = await self._run(query)
        if error:
            return f"Error previewing table: {error}"
        if not rows:
            return f"Table '{table_name}' is empty."
        results = [dict(row) for row in rows]
        return f"Preview of '{table_name}' (showing {len(results)} row(s)):\n{results}"

    # --- Query execution ---

    async def execute_query(self, query: str) -> str:
        # Auto-add LIMIT for regular queries
        query = self._add_limit(query)
        return await self.execute_query_no_limit(query)

    async def execute_query_no_limit(self, query: str) -> str:
        """Execute query WITHOUT auto-LIMIT."""
        if not self._db_path:
            return "Database not connected."
        try:
            async with aiosqlite.connect(self._db_path) as conn:
                conn.row_factory = aiosqlite.Row
                query_upper = query.strip().upper()
                if query_upper.startswith("SELECT") or query_upper.startswith("PRAGMA"):
                    cursor = await conn.execute(query)
                    rows = await cursor.fetchall()
                    if not rows:
                        return "Query executed successfully. No rows returned."
                    results = [dict(row) for row in rows]
                    import json
                    return json.dumps(results)
                else:
                    await conn.execute(query)
                    await conn.commit()
                    return "Query executed successfully."
        except Exception as e:
            return f"Error executing query: {str(e)}"

    async def stream_query(self, query: str, chunk_size: int = 5000):
        if not self._db_path:
            raise RuntimeError("Database not connected.")
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(query) as cursor:
                columns = [d[0] for d in (cursor.description or [])]
                while True:
                    rows = await cursor.fetchmany(chunk_size)
                    if not rows:
                        break
                    yield columns, rows

    def _add_limit(self, query: str) -> str:
        """Auto-add LIMIT to prevent large result sets."""
        query_upper = query.strip().upper()
        if not query_upper.startswith("SELECT"):
            return query
        if "LIMIT" in query_upper:
            return query
        return f"{query} LIMIT 1000"

    async def run_mutation(self, sql: str) -> str:
        sql_upper = sql.strip().upper()
        if not any(sql_upper.startswith(cmd) for cmd in ["INSERT", "UPDATE", "DELETE"]):
            return "Error: run_mutation only accepts INSERT, UPDATE, or DELETE queries."
        if not self._db_path:
            return "Database not connected."
        try:
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.execute(sql)
                await conn.commit()
            return "Mutation executed successfully."
        except Exception as e:
            return f"Error running mutation: {str(e)}"

    async def validate_sql(self, sql: str) -> str:
        """DDL only (dry-run + rollback). Use explain_sql for SELECT/DML."""
        if not self._db_path:
            return "Database not connected."
        if not is_ddl_statement(sql):
            return (
                "Error: validate_sql is for DDL only (CREATE/ALTER/DROP/TRUNCATE). "
                "Use explain_sql for SELECT, INSERT, UPDATE, or DELETE."
            )
        return await self._validate_ddl(sql)

    async def _validate_ddl(self, sql: str) -> str:
        """Tier 3: dry-run DDL, then rollback (SQLite)."""
        if not self._db_path:
            return "Database not connected."
        try:
            async with aiosqlite.connect(self._db_path) as conn:
                await conn.execute("BEGIN")
                try:
                    await conn.execute(sql)
                except Exception as e:
                    await conn.rollback()
                    return f"SQL validation error: {str(e)}"
                await conn.rollback()
            return "SQL query is valid."
        except Exception as e:
            return f"SQL validation error: {str(e)}"

    @staticmethod
    def _explain_query_plan_sql(sql: str) -> str:
        return f"EXPLAIN QUERY PLAN {sql}"

    async def explain_sql(self, sql: str) -> str:
        query = self._explain_query_plan_sql(sql)
        rows, error = await self._run(query)
        if error:
            return f"Error explaining SQL: {error}"
        plan_lines = [str(tuple(row)) for row in rows]
        return "Execution plan:\n" + "\n".join(plan_lines)

    # --- Additional operations ---

    async def list_databases(self) -> str:
        if not self._db_path:
            return "Not connected to any SQLite database."
        return f"Currently connected SQLite database: {self._db_path}"

    async def generate_schema_doc(self, format: str = "text") -> str:
        schema = await self.get_schema()
        if format.lower() == "markdown":
            lines = schema.split("\n")
            markdown = "# Database Schema Documentation\n\n"
            for line in lines:
                if line.startswith("Table:"):
                    markdown += f"## {line.replace('Table:', '').strip()}\n\n"
                elif line.startswith("  -"):
                    markdown += f"- {line.replace('  -', '').strip()}\n"
                elif line.strip() == "":
                    markdown += "\n"
            return markdown
        return schema

    async def manage_constraint(
        self,
        action: str,
        table_name: str,
        constraint_name: str,
        constraint_def: Optional[str] = None,
    ) -> str:
        # SQLite has limited support for constraints after table creation
        return "Error: SQLite does not support adding or dropping constraints after table creation. You need to recreate the table."

    async def manage_trigger(
        self,
        action: str,
        trigger_name: str,
        table_name: str,
        trigger_def: Optional[str] = None,
    ) -> str:
        if action.lower() == "create":
            if not trigger_def:
                return "Error: trigger_def is required when creating a trigger."
            query = f"CREATE TRIGGER {trigger_name} {trigger_def}"
        elif action.lower() == "drop":
            query = f"DROP TRIGGER IF EXISTS {trigger_name}"
        else:
            return f"Error: action must be 'create' or 'drop', got '{action}'"

        error = await self._execute(query)
        if error:
            return f"Error managing trigger: {error}"
        return f"Trigger '{trigger_name}' {action}d successfully."
