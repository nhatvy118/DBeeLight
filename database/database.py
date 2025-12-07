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
            "Database not connected. Please use 'connect_database' tool first to provide "
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
async def connect_database(
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
        return "Not connected to any database. Please use 'connect_database' tool first."
    
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


def main():
    # Initialize and run the server
    mcp.run(transport='stdio')


if __name__ == "__main__":
    main()

