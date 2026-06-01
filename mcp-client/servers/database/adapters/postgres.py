"""PostgreSQL database adapter."""

from typing import Any, Dict, List, Optional
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID
import json
import asyncpg

from adapters.base import DatabaseAdapter, is_ddl_statement


def _normalize_value(value: Any) -> Any:
    """Normalize value for database insertion, especially handling dates/datetimes."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, str):
        value_stripped = value.strip()
        if not value_stripped:
            return value
        # Try datetime formats
        datetime_formats = [
            "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
            "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
        ]
        for fmt in datetime_formats:
            try:
                return datetime.strptime(value_stripped, fmt)
            except ValueError:
                continue
        # Try date formats
        date_formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"]
        for fmt in date_formats:
            try:
                return datetime.strptime(value_stripped, fmt).date()
            except ValueError:
                continue
    return value


def _json_safe(value: Any) -> Any:
    """JSON serializer for PostgreSQL scalar types."""
    if isinstance(value, Decimal):
        # preserve precision while staying JSON-serializable
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


class PostgresAdapter(DatabaseAdapter):
    """PostgreSQL database adapter using asyncpg."""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
        self._config: Dict[str, Any] = {
            "host": None,
            "port": None,
            "database": None,
            "user": None,
            "password": None,
        }

    def is_connected(self) -> bool:
        return self._pool is not None and not self._pool.is_closing()

    async def connect(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "",
        username: str = "",
        password: str = "",
        **kwargs,
    ) -> str:
        try:
            if self._pool is not None:
                await self._pool.close()
                self._pool = None
            test_pool = await asyncpg.create_pool(
                host=host, port=port, database=database, user=username, password=password,
                min_size=1, max_size=1,
            )
            async with test_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            await test_pool.close()
            self._pool = await asyncpg.create_pool(
                host=host, port=port, database=database, user=username, password=password,
                min_size=1, max_size=10,
            )
            self._config = {"host": host, "port": port, "database": database, "user": username, "password": password}
            return f"Successfully connected to database '{database}' on {host}:{port} as user '{username}'."
        except Exception as e:
            self._pool = None
            return f"Failed to connect to database: {str(e)}. Please check your credentials and try again."

    async def disconnect(self) -> str:
        try:
            if self._pool is not None:
                await self._pool.close()
                self._pool = None
            self._config = {"host": None, "port": None, "database": None, "user": None, "password": None}
            return "Disconnected from database successfully."
        except Exception as e:
            return f"Error disconnecting: {str(e)}"

    async def get_connection_info(self) -> str:
        if not self.is_connected():
            return "Not connected to any database."
        return f"""Current database connection:
- Type: PostgreSQL
- Host: {self._config['host']}
- Port: {self._config['port']}
- Database: {self._config['database']}
- Username: {self._config['user']}
- Status: Connected"""

    async def _get_pool(self) -> asyncpg.Pool:
        if not self.is_connected():
            raise RuntimeError("Database not connected. Please connect first.")
        return self._pool

    # --- Schema operations ---

    async def list_tables(self) -> str:
        try:
            pool = await self._get_pool()
            query = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
            async with pool.acquire() as conn:
                rows = await conn.fetch(query)
            if not rows:
                return "No tables found in the database."
            tables = [row['table_name'] for row in rows]
            return f"Tables in database: {', '.join(tables)}"
        except Exception as e:
            return f"Error listing tables: {str(e)}"

    async def describe_table(self, table_name: str) -> str:
        try:
            pool = await self._get_pool()
            query = """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = $1
                ORDER BY ordinal_position
            """
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, table_name)
            if not rows:
                return f"Table '{table_name}' not found."
            lines = []
            for row in rows:
                info = f"- {row['column_name']}: {row['data_type']}"
                if row['is_nullable'] == 'NO':
                    info += " NOT NULL"
                if row['column_default']:
                    info += f" DEFAULT {row['column_default']}"
                lines.append(info)
            return f"Structure of table '{table_name}':\n" + "\n".join(lines)
        except Exception as e:
            return f"Error describing table: {str(e)}"

    async def get_schema(self) -> str:
        try:
            pool = await self._get_pool()
            query = """
                SELECT t.table_name, c.column_name, c.data_type, c.is_nullable, c.column_default, c.character_maximum_length
                FROM information_schema.tables t
                JOIN information_schema.columns c ON t.table_name = c.table_name
                WHERE t.table_schema = 'public'
                ORDER BY t.table_name, c.ordinal_position
            """
            async with pool.acquire() as conn:
                rows = await conn.fetch(query)
            if not rows:
                return "No tables found in the database."
            schema_dict: Dict[str, List[str]] = {}
            for row in rows:
                table = row['table_name']
                if table not in schema_dict:
                    schema_dict[table] = []
                col_info = f"{row['column_name']} ({row['data_type']}"
                if row['character_maximum_length']:
                    col_info += f"({row['character_maximum_length']})"
                col_info += ")"
                if row['is_nullable'] == 'NO':
                    col_info += " NOT NULL"
                if row['column_default']:
                    col_info += f" DEFAULT {row['column_default']}"
                schema_dict[table].append(col_info)
            text = "Database Schema:\n\n"
            for table, columns in schema_dict.items():
                text += f"Table: {table}\n"
                for col in columns:
                    text += f"  - {col}\n"
                text += "\n"
            return text
        except Exception as e:
            return f"Error getting schema: {str(e)}"

    async def get_table_stats(self, table_name: str) -> str:
        try:
            pool = await self._get_pool()
            count_query = f"SELECT COUNT(*) as row_count FROM {table_name}"
            size_query = """
                SELECT pg_size_pretty(pg_total_relation_size($1)) as total_size,
                       pg_size_pretty(pg_relation_size($1)) as table_size,
                       pg_size_pretty(pg_indexes_size($1)) as indexes_size
            """
            async with pool.acquire() as conn:
                row_count = await conn.fetchval(count_query)
                size_info = await conn.fetchrow(size_query, table_name)
            return f"""Statistics for table '{table_name}':
- Row count: {row_count}
- Total size: {size_info['total_size']}
- Table size: {size_info['table_size']}
- Indexes size: {size_info['indexes_size']}"""
        except Exception as e:
            return f"Error getting table stats: {str(e)}"

    # --- DDL operations ---

    async def create_table(self, table_name: str, columns: str, primary_key: Optional[str] = None) -> str:
        try:
            pool = await self._get_pool()
            pk_constraint = f", PRIMARY KEY ({primary_key})" if primary_key else ""
            query = f"CREATE TABLE IF NOT EXISTS {table_name} ({columns}{pk_constraint})"
            async with pool.acquire() as conn:
                await conn.execute(query)
            return f"Table '{table_name}' created successfully."
        except Exception as e:
            return f"Error creating table: {str(e)}"

    async def alter_table(
        self,
        action: str,
        table_name: str,
        column_name: str,
        column_def: Optional[str] = None,
        new_column_name: Optional[str] = None,
    ) -> str:
        try:
            pool = await self._get_pool()
            action_lower = action.lower()
            if action_lower == "add_column":
                if not column_def:
                    return "Error: column_def is required when adding a column."
                query = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
            elif action_lower == "drop_column":
                query = f"ALTER TABLE {table_name} DROP COLUMN {column_name}"
            elif action_lower in ("modify_column", "alter_column"):
                if not column_def:
                    return "Error: column_def is required when modifying a column."
                if not any(column_def.upper().startswith(kw) for kw in ["TYPE", "SET", "DROP"]):
                    query = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE {column_def}"
                else:
                    query = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} {column_def}"
            elif action_lower == "rename_column":
                if not new_column_name:
                    return "Error: new_column_name is required when renaming a column."
                query = f"ALTER TABLE {table_name} RENAME COLUMN {column_name} TO {new_column_name}"
            else:
                return f"Error: action must be one of: 'add_column', 'drop_column', 'modify_column', 'rename_column'. Got '{action}'"
            async with pool.acquire() as conn:
                await conn.execute(query)
            return f"Table '{table_name}' altered successfully."
        except Exception as e:
            return f"Error altering table: {str(e)}"

    async def create_from_spec(self, spec_text: str) -> str:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(spec_text)
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
        try:
            pool = await self._get_pool()
            query = f"SELECT {columns} FROM {table_name}"
            if where_clause:
                query += f" WHERE {where_clause}"
            if order_by:
                query += f" ORDER BY {order_by}"
            if limit:
                query += f" LIMIT {limit}"
            async with pool.acquire() as conn:
                rows = await conn.fetch(query)
            if not rows:
                return f"No data found in '{table_name}'."
            results = [dict(row) for row in rows]
            return f"Found {len(results)} row(s):\n{results}"
        except Exception as e:
            return f"Error selecting data: {str(e)}"

    async def insert_data(self, table_name: str, data: Dict[str, Any]) -> str:
        try:
            pool = await self._get_pool()
            normalized = {k: _normalize_value(v) for k, v in data.items()}
            columns = ", ".join(normalized.keys())
            placeholders = ", ".join([f"${i+1}" for i in range(len(normalized))])
            values = list(normalized.values())
            query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders}) RETURNING *"
            async with pool.acquire() as conn:
                result = await conn.fetchrow(query, *values)
            if result:
                return f"Data inserted successfully into '{table_name}'. Inserted row: {dict(result)}"
            return f"Data inserted into '{table_name}' but no row returned."
        except Exception as e:
            return f"Error inserting data: {str(e)}"

    async def update_data(self, table_name: str, data: Dict[str, Any], where_clause: str) -> str:
        try:
            pool = await self._get_pool()
            normalized = {k: _normalize_value(v) for k, v in data.items()}
            set_clauses = []
            values = []
            for i, (col, val) in enumerate(normalized.items(), 1):
                set_clauses.append(f"{col} = ${i}")
                values.append(val)
            query = f"UPDATE {table_name} SET {', '.join(set_clauses)} WHERE {where_clause} RETURNING *"
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *values)
            if not rows:
                return f"No rows updated in '{table_name}' (no rows matched WHERE clause)."
            results = [dict(row) for row in rows]
            return f"Updated {len(results)} row(s) in '{table_name}':\n{results}"
        except Exception as e:
            return f"Error updating data: {str(e)}"

    async def delete_data(self, table_name: str, where_clause: str) -> str:
        try:
            pool = await self._get_pool()
            query = f"DELETE FROM {table_name} WHERE {where_clause} RETURNING *"
            async with pool.acquire() as conn:
                rows = await conn.fetch(query)
            if not rows:
                return f"No rows deleted from '{table_name}' (no rows matched WHERE clause)."
            results = [dict(row) for row in rows]
            return f"Deleted {len(results)} row(s) from '{table_name}':\n{results}"
        except Exception as e:
            return f"Error deleting data: {str(e)}"

    async def preview_table(self, table_name: str, limit: int = 10) -> str:
        try:
            pool = await self._get_pool()
            query = f"SELECT * FROM {table_name} LIMIT {limit}"
            async with pool.acquire() as conn:
                rows = await conn.fetch(query)
            if not rows:
                return f"Table '{table_name}' is empty."
            results = [dict(row) for row in rows]
            return f"Preview of '{table_name}' (showing {len(results)} row(s)):\n{results}"
        except Exception as e:
            return f"Error previewing table: {str(e)}"

    # --- Query execution ---

    async def execute_query(self, query: str) -> str:
        # Auto-add LIMIT for regular queries
        query = self._add_limit(query)
        return await self.execute_query_no_limit(query)

    async def execute_query_no_limit(self, query: str) -> str:
        """Execute query WITHOUT auto-LIMIT."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                return await self._execute_on_connection(conn, query)
        except Exception as e:
            err = str(e)
            if "cached statement plan is invalid" in err.lower():
                try:
                    pool = await self._get_pool()
                    async with pool.acquire() as conn:
                        await self._discard_prepared_statements(conn)
                        return await self._execute_on_connection(conn, query)
                except Exception as retry_e:
                    return f"Error executing query: {retry_e}"
            return f"Error executing query: {err}"

    async def _execute_on_connection(self, conn, query: str) -> str:
        query_upper = query.strip().upper()
        if query_upper.startswith("SELECT"):
            rows = await conn.fetch(query)
            if not rows:
                return "Query executed successfully. No rows returned."
            results = [dict(row) for row in rows]
            return json.dumps(results, default=_json_safe)
        await conn.execute(query)
        return "Query executed successfully."

    async def stream_query(self, query: str, chunk_size: int = 5000):
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                cur = await conn.cursor(query, prefetch=chunk_size)
                columns: Optional[List[str]] = None
                while True:
                    rows = await cur.fetch(chunk_size)
                    if not rows:
                        break
                    if columns is None:
                        columns = list(rows[0].keys())
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
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(sql)
            return "Mutation executed successfully."
        except Exception as e:
            return f"Error running mutation: {str(e)}"

    async def validate_sql(self, sql: str) -> str:
        """DDL only (dry-run + rollback). Use explain_sql for SELECT/DML."""
        if not is_ddl_statement(sql):
            return (
                "Error: validate_sql is for DDL only (CREATE/ALTER/DROP/TRUNCATE). "
                "Use explain_sql for SELECT, INSERT, UPDATE, or DELETE."
            )
        return await self._validate_ddl(sql)

    @staticmethod
    async def _discard_prepared_statements(conn) -> None:
        """Clear asyncpg/PostgreSQL cached plans after DDL (even rolled back)."""
        try:
            await conn.execute("DISCARD ALL")
        except Exception:
            pass

    async def _validate_ddl(self, sql: str) -> str:
        """Tier 3: dry-run DDL inside a transaction, then rollback (PostgreSQL)."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                tr = conn.transaction()
                await tr.start()
                try:
                    await conn.execute(sql)
                except Exception as e:
                    await tr.rollback()
                    await self._discard_prepared_statements(conn)
                    return f"SQL validation error: {str(e)}"
                await tr.rollback()
                # DDL dry-run invalidates prepared plans on this pooled connection.
                await self._discard_prepared_statements(conn)
            return "SQL query is valid."
        except Exception as e:
            return f"SQL validation error: {str(e)}"

    async def explain_sql(self, sql: str) -> str:
        # EXPLAIN only (no ANALYZE) — safe for mutations; does not execute the statement.
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(f"EXPLAIN {sql}")
            plan_lines = [str(row[0]) for row in rows]
            return "Execution plan:\n" + "\n".join(plan_lines)
        except Exception as e:
            return f"Error explaining SQL: {str(e)}"

    # --- Additional operations ---

    async def list_databases(self) -> str:
        try:
            pool = await self._get_pool()
            query = "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
            async with pool.acquire() as conn:
                rows = await conn.fetch(query)
            if not rows:
                return "No databases found."
            databases = [row['datname'] for row in rows]
            return f"Databases: {', '.join(databases)}"
        except Exception as e:
            return f"Error listing databases: {str(e)}"

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
        try:
            pool = await self._get_pool()
            if action.lower() == "add":
                if not constraint_def:
                    return "Error: constraint_def is required when adding a constraint."
                query = f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} {constraint_def}"
            elif action.lower() == "drop":
                query = f"ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name}"
            else:
                return f"Error: action must be 'add' or 'drop', got '{action}'"
            async with pool.acquire() as conn:
                await conn.execute(query)
            return f"Constraint '{constraint_name}' {action}ed successfully on table '{table_name}'."
        except Exception as e:
            return f"Error managing constraint: {str(e)}"

    async def manage_trigger(
        self,
        action: str,
        trigger_name: str,
        table_name: str,
        trigger_def: Optional[str] = None,
    ) -> str:
        try:
            pool = await self._get_pool()
            if action.lower() == "create":
                if not trigger_def:
                    return "Error: trigger_def is required when creating a trigger."
                query = f"CREATE TRIGGER {trigger_name} {trigger_def}"
            elif action.lower() == "drop":
                query = f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}"
            else:
                return f"Error: action must be 'create' or 'drop', got '{action}'"
            async with pool.acquire() as conn:
                await conn.execute(query)
            return f"Trigger '{trigger_name}' {action}d successfully on table '{table_name}'."
        except Exception as e:
            return f"Error managing trigger: {str(e)}"
