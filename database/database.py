from typing import Any, Optional
import asyncpg
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("database")

# Database connection pool and credentials
_pool: Optional[asyncpg.Pool] = None
_db_config: dict[str, Any] = {
    "host": None,
    "port": None,
    "database": None,
    "user": None,
    "password": None,
    "connected": False
}


async def close_pool():
    """Close the current database connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
    _db_config["connected"] = False


async def get_pool() -> asyncpg.Pool:
    """Get or create database connection pool."""
    global _pool, _db_config
    
    if not _db_config["connected"]:
        raise RuntimeError(
            "Database not connected. Please use 'connect_db' tool first to provide "
            "database credentials (host, port, database name, username, password)."
        )
    
    if _pool is None or _pool.is_closing():
        _pool = await asyncpg.create_pool(
            host=_db_config["host"],
            port=_db_config["port"],
            database=_db_config["database"],
            user=_db_config["user"],
            password=_db_config["password"],
            min_size=1,
            max_size=10,
        )
    return _pool


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
    global _db_config, _pool
    
    try:
        # Close existing connection if any
        if _pool is not None:
            await close_pool()
        
        # Test connection
        test_pool = await asyncpg.create_pool(
            host=host,
            port=port,
            database=database,
            user=username,
            password=password,
            min_size=1,
            max_size=1,
        )
        
        async with test_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        await test_pool.close()
        
        # Save credentials
        _db_config = {
            "host": host,
            "port": port,
            "database": database,
            "user": username,
            "password": password,
            "connected": True
        }
        
        return f"Successfully connected to database '{database}' on {host}:{port} as user '{username}'."
    except Exception as e:
        _db_config["connected"] = False
        return f"Failed to connect to database: {str(e)}. Please check your credentials and try again."


@mcp.tool()
async def get_connection_info() -> str:
    """Get current database connection information (without showing password)."""
    if not _db_config["connected"]:
        return "Not connected to any database. Please use 'connect_db' tool first."
    
    info = f"""Current database connection:
- Host: {_db_config['host']}
- Port: {_db_config['port']}
- Database: {_db_config['database']}
- Username: {_db_config['user']}
- Status: Connected"""
    
    return info


@mcp.tool()
async def disconnect_database() -> str:
    """Disconnect from the current database."""
    try:
        await close_pool()
        return "Disconnected from database successfully."
    except Exception as e:
        return f"Error disconnecting: {str(e)}"


@mcp.tool()
async def create_table(
    table_name: str,
    columns: str,
    primary_key: Optional[str] = None
) -> str:
    """Create a new table in the database.
    
    Args:
        table_name: Name of the table to create
        columns: Column definitions in SQL format (e.g., "id SERIAL, name VARCHAR(100), email VARCHAR(255)")
        primary_key: Optional primary key column name
    """
    try:
        pool = await get_pool()
        
        # Build CREATE TABLE statement
        pk_constraint = f", PRIMARY KEY ({primary_key})" if primary_key else ""
        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({columns}{pk_constraint})"
        
        async with pool.acquire() as conn:
            await conn.execute(query)
        
        return f"Table '{table_name}' created successfully."
    except Exception as e:
        return f"Error creating table: {str(e)}"


@mcp.tool()
async def insert_data(
    table_name: str,
    data: dict[str, Any]
) -> str:
    """Insert data into a table.
    
    Args:
        table_name: Name of the table
        data: Dictionary with column names as keys and values to insert
    """
    try:
        pool = await get_pool()
        
        columns = ", ".join(data.keys())
        placeholders = ", ".join([f"${i+1}" for i in range(len(data))])
        values = list(data.values())
        
        query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders}) RETURNING *"
        
        async with pool.acquire() as conn:
            result = await conn.fetchrow(query, *values)
        
        if result:
            return f"Data inserted successfully into '{table_name}'. Inserted row: {dict(result)}"
        return f"Data inserted into '{table_name}' but no row returned."
    except Exception as e:
        return f"Error inserting data: {str(e)}"


@mcp.tool()
async def select_data(
    table_name: str,
    columns: str = "*",
    where_clause: Optional[str] = None,
    limit: Optional[int] = None,
    order_by: Optional[str] = None
) -> str:
    """Select data from a table.
    
    Args:
        table_name: Name of the table
        columns: Column names to select (default: "*")
        where_clause: Optional WHERE clause (e.g., "age > 18")
        limit: Optional limit on number of rows
        order_by: Optional ORDER BY clause (e.g., "name ASC")
    """
    try:
        pool = await get_pool()
        
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


@mcp.tool()
async def update_data(
    table_name: str,
    data: dict[str, Any],
    where_clause: str
) -> str:
    """Update data in a table.
    
    Args:
        table_name: Name of the table
        data: Dictionary with column names and new values
        where_clause: WHERE clause to identify rows to update (e.g., "id = 1")
    """
    try:
        pool = await get_pool()
        
        set_clauses = []
        values = []
        param_index = 1
        
        for column, value in data.items():
            set_clauses.append(f"{column} = ${param_index}")
            values.append(value)
            param_index += 1
        
        set_clause = ", ".join(set_clauses)
        query = f"UPDATE {table_name} SET {set_clause} WHERE {where_clause} RETURNING *"
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *values)
        
        if not rows:
            return f"No rows updated in '{table_name}' (no rows matched WHERE clause)."
        
        results = [dict(row) for row in rows]
        return f"Updated {len(results)} row(s) in '{table_name}':\n{results}"
    except Exception as e:
        return f"Error updating data: {str(e)}"


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
    try:
        pool = await get_pool()
        
        query = f"DELETE FROM {table_name} WHERE {where_clause} RETURNING *"
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
        
        if not rows:
            return f"No rows deleted from '{table_name}' (no rows matched WHERE clause)."
        
        results = [dict(row) for row in rows]
        return f"Deleted {len(results)} row(s) from '{table_name}':\n{results}"
    except Exception as e:
        return f"Error deleting data: {str(e)}"


@mcp.tool()
async def execute_query(query: str) -> str:
    """Execute a custom SQL query.
    
    Args:
        query: SQL query to execute
    """
    try:
        pool = await get_pool()
        
        async with pool.acquire() as conn:
            # Check if it's a SELECT query
            query_upper = query.strip().upper()
            if query_upper.startswith("SELECT"):
                rows = await conn.fetch(query)
                if not rows:
                    return "Query executed successfully. No rows returned."
                results = [dict(row) for row in rows]
                return f"Query returned {len(results)} row(s):\n{results}"
            else:
                # For INSERT, UPDATE, DELETE, etc.
                result = await conn.execute(query)
                return f"Query executed successfully. Result: {result}"
    except Exception as e:
        return f"Error executing query: {str(e)}"


@mcp.tool()
async def list_tables() -> str:
    """List all tables in the database."""
    try:
        pool = await get_pool()
        
        query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
        
        if not rows:
            return "No tables found in the database."
        
        tables = [row['table_name'] for row in rows]
        return f"Tables in database: {', '.join(tables)}"
    except Exception as e:
        return f"Error listing tables: {str(e)}"


@mcp.tool()
async def describe_table(table_name: str) -> str:
    """Get structure of a table (columns, types, constraints).
    
    Args:
        table_name: Name of the table to describe
    """
    try:
        pool = await get_pool()
        
        query = """
            SELECT 
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_name = $1
            ORDER BY ordinal_position
        """
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, table_name)
        
        if not rows:
            return f"Table '{table_name}' not found."
        
        columns_info = []
        for row in rows:
            info = f"- {row['column_name']}: {row['data_type']}"
            if row['is_nullable'] == 'NO':
                info += " NOT NULL"
            if row['column_default']:
                info += f" DEFAULT {row['column_default']}"
            columns_info.append(info)
        
        return f"Structure of table '{table_name}':\n" + "\n".join(columns_info)
    except Exception as e:
        return f"Error describing table: {str(e)}"


@mcp.tool()
async def create_db_from_spec(spec_text: str) -> str:
    """Create database schema from a specification text (SQL DDL statements).
    
    Args:
        spec_text: SQL DDL statements to create tables, constraints, etc.
    """
    try:
        pool = await get_pool()
        
        async with pool.acquire() as conn:
            # Execute the specification (may contain multiple statements)
            await conn.execute(spec_text)
        
        return f"Database schema created successfully from specification."
    except Exception as e:
        return f"Error creating database from spec: {str(e)}"


@mcp.tool()
async def list_databases() -> str:
    """List all databases on the PostgreSQL server."""
    try:
        pool = await get_pool()
        
        # Connect to postgres database to list all databases
        query = """
            SELECT datname 
            FROM pg_database 
            WHERE datistemplate = false
            ORDER BY datname
        """
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
        
        if not rows:
            return "No databases found."
        
        databases = [row['datname'] for row in rows]
        return f"Databases: {', '.join(databases)}"
    except Exception as e:
        return f"Error listing databases: {str(e)}"


@mcp.tool()
async def get_table_stats(table_name: str) -> str:
    """Get statistics about a table (row count, size, etc.).
    
    Args:
        table_name: Name of the table
    """
    try:
        pool = await get_pool()
        
        # Get row count
        count_query = f"SELECT COUNT(*) as row_count FROM {table_name}"
        
        # Get table size
        size_query = """
            SELECT 
                pg_size_pretty(pg_total_relation_size($1)) as total_size,
                pg_size_pretty(pg_relation_size($1)) as table_size,
                pg_size_pretty(pg_indexes_size($1)) as indexes_size
        """
        
        async with pool.acquire() as conn:
            row_count = await conn.fetchval(count_query)
            size_info = await conn.fetchrow(size_query, table_name)
        
        stats = f"""Statistics for table '{table_name}':
- Row count: {row_count}
- Total size: {size_info['total_size']}
- Table size: {size_info['table_size']}
- Indexes size: {size_info['indexes_size']}"""
        
        return stats
    except Exception as e:
        return f"Error getting table stats: {str(e)}"


@mcp.tool()
async def get_schema() -> str:
    """Get the complete database schema (all tables, columns, constraints, etc.)."""
    try:
        pool = await get_pool()
        
        # Get all tables with their columns
        query = """
            SELECT 
                t.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.character_maximum_length
            FROM information_schema.tables t
            JOIN information_schema.columns c ON t.table_name = c.table_name
            WHERE t.table_schema = 'public'
            ORDER BY t.table_name, c.ordinal_position
        """
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
        
        if not rows:
            return "No tables found in the database."
        
        # Group by table
        schema_dict = {}
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
        
        schema_text = "Database Schema:\n\n"
        for table, columns in schema_dict.items():
            schema_text += f"Table: {table}\n"
            for col in columns:
                schema_text += f"  - {col}\n"
            schema_text += "\n"
        
        return schema_text
    except Exception as e:
        return f"Error getting schema: {str(e)}"


@mcp.tool()
async def generate_schema_doc(format: str = "text") -> str:
    """Generate documentation for the database schema.
    
    Args:
        format: Output format - "text" or "markdown"
    """
    try:
        schema = await get_schema()
        
        if format.lower() == "markdown":
            # Convert to markdown format
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
        else:
            return schema
    except Exception as e:
        return f"Error generating schema doc: {str(e)}"


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
    """
    try:
        pool = await get_pool()
        
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
        trigger_def: Trigger definition (required for "create", e.g., "BEFORE INSERT ON table_name FOR EACH ROW EXECUTE FUNCTION function_name()")
    """
    try:
        pool = await get_pool()
        
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


@mcp.tool()
async def preview_table(table_name: str, limit: int = 10) -> str:
    """Preview a table with a limited number of rows.
    
    Args:
        table_name: Name of the table
        limit: Number of rows to preview (default: 10)
    """
    try:
        pool = await get_pool()
        
        query = f"SELECT * FROM {table_name} LIMIT {limit}"
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
        
        if not rows:
            return f"Table '{table_name}' is empty."
        
        results = [dict(row) for row in rows]
        return f"Preview of '{table_name}' (showing {len(results)} row(s)):\n{results}"
    except Exception as e:
        return f"Error previewing table: {str(e)}"


@mcp.tool()
async def validate_sql(sql: str) -> str:
    """Validate SQL syntax without executing it.
    
    Args:
        sql: SQL query to validate
    """
    try:
        pool = await get_pool()
        
        # Use EXPLAIN to validate without executing
        explain_query = f"EXPLAIN {sql}"
        
        async with pool.acquire() as conn:
            await conn.fetch(explain_query)
        
        return "SQL query is valid."
    except Exception as e:
        return f"SQL validation error: {str(e)}"


@mcp.tool()
async def explain_sql(sql: str) -> str:
    """Explain the execution plan of a SQL query.
    
    Args:
        sql: SQL query to explain
    """
    try:
        pool = await get_pool()
        
        explain_query = f"EXPLAIN ANALYZE {sql}"
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(explain_query)
        
        # Extract query plan from rows
        plan_lines = []
        for row in rows:
            # asyncpg returns rows as Record objects
            plan_lines.append(str(row[0]))
        
        plan = "\n".join(plan_lines)
        return f"Execution plan:\n{plan}"
    except Exception as e:
        return f"Error explaining SQL: {str(e)}"


@mcp.tool()
async def run_mutation(sql: str) -> str:
    """Run a mutation query (INSERT, UPDATE, DELETE) and return affected rows.
    
    Args:
        sql: SQL mutation query (INSERT, UPDATE, or DELETE)
    """
    try:
        pool = await get_pool()
        
        # Check if it's a mutation query
        sql_upper = sql.strip().upper()
        if not any(sql_upper.startswith(cmd) for cmd in ["INSERT", "UPDATE", "DELETE"]):
            return "Error: run_mutation only accepts INSERT, UPDATE, or DELETE queries."
        
        async with pool.acquire() as conn:
            result = await conn.execute(sql)
        
        return f"Mutation executed successfully. {result}"
    except Exception as e:
        return f"Error running mutation: {str(e)}"


def main():
    # Initialize and run the server
    mcp.run(transport='stdio')


if __name__ == "__main__":
    main()

