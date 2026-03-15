from typing import Any, Optional
from pathlib import Path
import json
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("excel-summary")

try:
    import pandas as pd
    import openpyxl
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


@mcp.tool()
async def import_excel(path: str) -> str:
    """Import data from an Excel file.
    
    Args:
        path: Path to the Excel file (.xlsx or .xls)
    """
    if not PANDAS_AVAILABLE:
        return "Error: pandas and openpyxl are required. Please install: pip install pandas openpyxl"
    
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"Error: File not found at path '{path}'"
        
        # Read Excel file
        df = pd.read_excel(path)
        
        # Convert to dictionary format
        data = df.to_dict(orient='records')
        
        return f"Successfully imported {len(data)} rows from '{path}'. Data preview (first 5 rows):\n{json.dumps(data[:5], indent=2, default=str)}"
    except Exception as e:
        return f"Error importing Excel file: {str(e)}"


@mcp.tool()
async def export_excel(path: str, data: list[dict[str, Any]]) -> str:
    """Export data to an Excel file.
    
    Args:
        path: Path where to save the Excel file (.xlsx)
        data: List of dictionaries representing rows
    """
    if not PANDAS_AVAILABLE:
        return "Error: pandas and openpyxl are required. Please install: pip install pandas openpyxl"
    
    try:
        # Convert to DataFrame
        df = pd.DataFrame(data)
        
        # Export to Excel
        df.to_excel(path, index=False)
        
        return f"Successfully exported {len(data)} rows to '{path}'"
    except Exception as e:
        return f"Error exporting to Excel: {str(e)}"


@mcp.tool()
async def render_chart(
    chart_type: str,
    data_spec: str
) -> str:
    """Render a chart from data specification.
    
    Args:
        chart_type: Type of chart - "bar", "line", "pie", "scatter", "histogram"
        data_spec: JSON string with chart data specification (e.g., {"x": [...], "y": [...], "labels": [...]})
    """
    if not MATPLOTLIB_AVAILABLE:
        return "Error: matplotlib is required. Please install: pip install matplotlib"
    
    try:
        spec = json.loads(data_spec)
        
        fig, ax = plt.subplots()
        
        if chart_type.lower() == "bar":
            if "x" in spec and "y" in spec:
                ax.bar(spec["x"], spec["y"])
            elif "labels" in spec and "values" in spec:
                ax.bar(spec["labels"], spec["values"])
        elif chart_type.lower() == "line":
            if "x" in spec and "y" in spec:
                ax.plot(spec["x"], spec["y"])
        elif chart_type.lower() == "pie":
            if "labels" in spec and "values" in spec:
                ax.pie(spec["values"], labels=spec["labels"])
        elif chart_type.lower() == "scatter":
            if "x" in spec and "y" in spec:
                ax.scatter(spec["x"], spec["y"])
        elif chart_type.lower() == "histogram":
            if "values" in spec:
                ax.hist(spec["values"])
        else:
            return f"Error: Unsupported chart type '{chart_type}'. Supported types: bar, line, pie, scatter, histogram"
        
        if "title" in spec:
            ax.set_title(spec["title"])
        if "xlabel" in spec:
            ax.set_xlabel(spec["xlabel"])
        if "ylabel" in spec:
            ax.set_ylabel(spec["ylabel"])
        
        # Save chart to file
        output_path = spec.get("output_path", "chart.png")
        plt.savefig(output_path)
        plt.close()
        
        return f"Chart rendered successfully and saved to '{output_path}'"
    except json.JSONDecodeError:
        return f"Error: Invalid JSON in data_spec: {data_spec}"
    except Exception as e:
        return f"Error rendering chart: {str(e)}"


@mcp.tool()
async def suggest_charts(
    query: str,
    result_schema: str
) -> str:
    """Suggest appropriate chart types based on query and result schema.
    
    Args:
        query: The SQL query or data query
        result_schema: JSON string describing the result schema (column names and types)
    """
    try:
        schema = json.loads(result_schema)
        
        suggestions = []
        
        # Analyze schema to suggest charts
        if isinstance(schema, dict) and "columns" in schema:
            columns = schema["columns"]
            numeric_cols = [col for col in columns if schema.get("types", {}).get(col, "").lower() in ["int", "float", "numeric", "decimal"]]
            categorical_cols = [col for col in columns if schema.get("types", {}).get(col, "").lower() in ["varchar", "text", "string"]]
            
            if len(numeric_cols) >= 2:
                suggestions.append("scatter: Compare two numeric variables")
            if len(numeric_cols) >= 1 and len(categorical_cols) >= 1:
                suggestions.append("bar: Show numeric values by category")
            if len(numeric_cols) >= 1:
                suggestions.append("histogram: Distribution of numeric values")
            if len(categorical_cols) >= 1:
                suggestions.append("pie: Distribution of categories")
        
        if not suggestions:
            suggestions = [
                "bar: Good for comparing categories",
                "line: Good for trends over time",
                "pie: Good for showing proportions",
                "scatter: Good for relationships between variables",
                "histogram: Good for distributions"
            ]
        
        return f"Suggested chart types:\n" + "\n".join(f"- {s}" for s in suggestions)
    except json.JSONDecodeError:
        return f"Error: Invalid JSON in result_schema: {result_schema}"
    except Exception as e:
        return f"Error suggesting charts: {str(e)}"


@mcp.tool()
async def generate_chart_spec(
    chart_type: str,
    data: list[dict[str, Any]]
) -> str:
    """Generate chart specification from data.
    
    Args:
        chart_type: Type of chart - "bar", "line", "pie", "scatter", "histogram"
        data: List of dictionaries representing data rows
    """
    try:
        if not data:
            return "Error: Data is empty"
        
        # Extract column names
        columns = list(data[0].keys())
        
        spec = {}
        
        if chart_type.lower() == "bar":
            if len(columns) >= 2:
                spec = {
                    "labels": [str(row[columns[0]]) for row in data],
                    "values": [float(row[columns[1]]) if isinstance(row[columns[1]], (int, float)) else 0 for row in data]
                }
        elif chart_type.lower() == "line":
            if len(columns) >= 2:
                spec = {
                    "x": [str(row[columns[0]]) for row in data],
                    "y": [float(row[columns[1]]) if isinstance(row[columns[1]], (int, float)) else 0 for row in data]
                }
        elif chart_type.lower() == "pie":
            if len(columns) >= 2:
                spec = {
                    "labels": [str(row[columns[0]]) for row in data],
                    "values": [float(row[columns[1]]) if isinstance(row[columns[1]], (int, float)) else 0 for row in data]
                }
        elif chart_type.lower() == "scatter":
            if len(columns) >= 2:
                spec = {
                    "x": [float(row[columns[0]]) if isinstance(row[columns[0]], (int, float)) else 0 for row in data],
                    "y": [float(row[columns[1]]) if isinstance(row[columns[1]], (int, float)) else 0 for row in data]
                }
        elif chart_type.lower() == "histogram":
            if len(columns) >= 1:
                numeric_values = [float(row[columns[0]]) for row in data if isinstance(row.get(columns[0]), (int, float))]
                spec = {"values": numeric_values}
        else:
            return f"Error: Unsupported chart type '{chart_type}'"
        
        return json.dumps(spec, indent=2)
    except Exception as e:
        return f"Error generating chart spec: {str(e)}"


@mcp.tool()
async def describe_result_summary(data: list[dict[str, Any]]) -> str:
    """Generate a summary description of query results.
    
    Args:
        data: List of dictionaries representing data rows
    """
    try:
        if not data:
            return "Summary: No data returned."
        
        num_rows = len(data)
        columns = list(data[0].keys()) if data else []
        
        summary = f"Summary:\n"
        summary += f"- Total rows: {num_rows}\n"
        summary += f"- Columns: {', '.join(columns)}\n"
        
        # Calculate statistics for numeric columns
        if data:
            numeric_stats = {}
            for col in columns:
                values = [row.get(col) for row in data if row.get(col) is not None]
                numeric_values = [v for v in values if isinstance(v, (int, float))]
                
                if numeric_values:
                    numeric_stats[col] = {
                        "min": min(numeric_values),
                        "max": max(numeric_values),
                        "avg": sum(numeric_values) / len(numeric_values),
                        "count": len(numeric_values)
                    }
            
            if numeric_stats:
                summary += "\nNumeric column statistics:\n"
                for col, stats in numeric_stats.items():
                    summary += f"  {col}:\n"
                    summary += f"    - Min: {stats['min']}\n"
                    summary += f"    - Max: {stats['max']}\n"
                    summary += f"    - Average: {stats['avg']:.2f}\n"
                    summary += f"    - Count: {stats['count']}\n"
        
        return summary
    except Exception as e:
        return f"Error describing result summary: {str(e)}"


# =============================================================================
# Database Integration Tools
# =============================================================================

# These tools will be available when connected to a database via MCP
# The excel agent can use them in combination with database tools


@mcp.tool()
async def prepare_export_query(table_name: str, columns: str = "*", where_clause: str = None) -> str:
    """Prepare a SELECT query for exporting data to Excel.

    Args:
        table_name: Name of the table to export
        columns: Column names to export (default: "*")
        where_clause: Optional WHERE clause to filter data
    """
    query = f"SELECT {columns} FROM {table_name}"
    if where_clause:
        query += f" WHERE {where_clause}"
    query += " LIMIT 10000"  # Default export limit

    return f"Export query prepared:\n```sql\n{query}\n```\nThis query will export up to 10000 rows. Execute it using the database tool, then use export_excel to save to Excel."


@mcp.tool()
async def prepare_import_excel_to_db(
    excel_path: str,
    db_table: str,
    column_mapping: str = None,
    batch_size: int = 100
) -> str:
    """Prepare to import Excel data into database table.

    This tool generates the insert statements. Execute using database agent's insert_data tool.

    Args:
        excel_path: Path to Excel file
        db_table: Target database table name
        column_mapping: Optional mapping like "excel_col1:db_col1,excel_col2:db_col2"
        batch_size: Number of rows per batch (default: 100)

    Workflow:
    1. Use import_excel to read the Excel file first
    2. Use this tool to prepare the insert statements
    3. Use database insert_data tool to insert the data
    """
    if not PANDAS_AVAILABLE:
        return "Error: pandas required"

    try:
        df = pd.read_excel(excel_path)
        total_rows = len(df)

        # Apply column mapping if provided
        if column_mapping:
            mappings = {}
            for pair in column_mapping.split(","):
                if ":" in pair:
                    exc, dbc = pair.split(":")
                    mappings[exc.strip()] = dbc.strip()
            df = df.rename(columns=mappings)

        # Limit to batch_size for preview
        preview_data = df.head(batch_size).to_dict(orient="records")

        result = f"Excel Import Preparation:\n"
        result += f"- File: {excel_path}\n"
        result += f"- Target table: {db_table}\n"
        result += f"- Total rows: {total_rows}\n"
        result += f"- Columns: {', '.join(df.columns.tolist())}\n"
        result += f"\nFirst {min(batch_size, total_rows)} rows prepared:\n"
        result += json.dumps(preview_data[:3], indent=2, default=str)
        result += f"\n\nUse database insert_data tool with this data to insert into {db_table}"

        return result
    except Exception as e:
        return f"Error preparing import: {str(e)}"


@mcp.tool()
async def suggest_import_mapping(excel_columns: str, db_table: str, db_columns: str) -> str:
    """Suggest column mapping between Excel and database table.

    Args:
        excel_columns: Comma-separated Excel column names
        db_table: Database table name
        db_columns: Comma-separated database column names (use list_tables + describe_table to get)
    """
    excel_cols = [c.strip() for c in excel_columns.split(",")]
    db_cols = [c.strip() for c in db_columns.split(",")]

    suggestions = []
    for exc in excel_cols:
        # Try to find matching DB column
        match = None
        for dbc in db_cols:
            if exc.lower() == dbc.lower():
                match = dbc
                break
            if exc.lower().replace("_", "") == dbc.lower().replace("_", ""):
                match = dbc
                break
            if exc.lower() in dbc.lower() or dbc.lower() in exc.lower():
                match = dbc

        if match:
            suggestions.append(f"- {exc} -> {match}")
        else:
            suggestions.append(f"- {exc} -> (no match, skip)")

    return "Suggested mapping:\n" + "\n".join(suggestions) + "\n\nAdjust as needed, then use insert_data tool to insert rows."


# =============================================================================
# Data Analysis Tools
# =============================================================================

@mcp.tool()
async def analyze_numeric_distribution(data: list[dict[str, Any]]) -> str:
    """Analyze distribution of numeric columns.

    Args:
        data: List of dictionaries representing data rows
    """
    if not data:
        return "Error: No data provided"

    try:
        df = pd.DataFrame(data)
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

        if not numeric_cols:
            return "No numeric columns found in data"

        result = "Numeric Column Distribution Analysis:\n"

        for col in numeric_cols:
            col_data = df[col].dropna()
            if len(col_data) == 0:
                continue

            result += f"\n{col}:\n"
            result += f"  Count: {len(col_data)}\n"
            result += f"  Mean: {col_data.mean():.2f}\n"
            result += f"  Median: {col_data.median():.2f}\n"
            result += f"  Std Dev: {col_data.std():.2f}\n"
            result += f"  Min: {col_data.min()}\n"
            result += f"  Max: {col_data.max()}\n"
            result += f"  25%: {col_data.quantile(0.25):.2f}\n"
            result += f"  75%: {col_data.quantile(0.75):.2f}\n"

            # Check for outliers using IQR
            Q1 = col_data.quantile(0.25)
            Q3 = col_data.quantile(0.75)
            IQR = Q3 - Q1
            outliers = col_data[(col_data < Q1 - 1.5*IQR) | (col_data > Q3 + 1.5*IQR)]
            result += f"  Outliers: {len(outliers)}\n"

        return result
    except Exception as e:
        return f"Error analyzing distribution: {str(e)}"


@mcp.tool()
async def find_outliers(data: list[dict[str, Any]], column: str, method: str = "iqr") -> str:
    """Find outliers in a numeric column.

    Args:
        data: List of dictionaries representing data rows
        column: Column name to check for outliers
        method: Detection method - "iqr" (Interquartile Range) or "zscore" (default: "iqr")
    """
    if not data:
        return "Error: No data provided"

    try:
        df = pd.DataFrame(data)

        if column not in df.columns:
            return f"Error: Column '{column}' not found. Available: {', '.join(df.columns)}"

        col_data = pd.to_numeric(df[column], errors='coerce').dropna()

        if len(col_data) == 0:
            return f"Error: Column '{column}' has no numeric values"

        if method == "iqr":
            Q1 = col_data.quantile(0.25)
            Q3 = col_data.quantile(0.75)
            IQR = Q3 - Q1
            lower = Q1 - 1.5 * IQR
            upper = Q3 + 1.5 * IQR
            outlier_mask = (col_data < lower) | (col_data > upper)
            method_name = "IQR"
        else:  # zscore
            mean = col_data.mean()
            std = col_data.std()
            z_scores = (col_data - mean) / std if std > 0 else 0
            outlier_mask = abs(z_scores) > 3
            method_name = "Z-Score (>3)"

        outliers = col_data[outlier_mask]
        total = len(col_data)

        if len(outliers) == 0:
            return f"No outliers found in '{column}' using {method_name}"

        result = f"Outliers in '{column}' using {method_name}:\n"
        result += f"Total rows: {total}\n"
        result += f"Outliers found: {len(outliers)} ({100*len(outliers)/total:.1f}%)\n"
        result += f"\nOutlier values:\n"
        for val in outliers.head(20).tolist():
            result += f"- {val}\n"

        if len(outliers) > 20:
            result += f"... and {len(outliers) - 20} more\n"

        return result
    except Exception as e:
        return f"Error finding outliers: {str(e)}"


@mcp.tool()
async def calculate_correlation(data: list[dict[str, Any]], columns: str = None) -> str:
    """Calculate correlation matrix between numeric columns.

    Args:
        data: List of dictionaries representing data rows
        columns: Comma-separated column names to include (optional, defaults to all numeric)
    """
    if not data:
        return "Error: No data provided"

    try:
        df = pd.DataFrame(data)
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

        if not numeric_cols:
            return "No numeric columns found"

        if columns:
            cols = [c.strip() for c in columns.split(",")]
            numeric_cols = [c for c in cols if c in numeric_cols]

        if len(numeric_cols) < 2:
            return "Need at least 2 numeric columns for correlation"

        corr_matrix = df[numeric_cols].corr()

        return f"Correlation Matrix:\n{corr_matrix.to_string()}"
    except Exception as e:
        return f"Error calculating correlation: {str(e)}"


@mcp.tool()
async def detect_data_types(data: list[dict[str, Any]]) -> str:
    """Detect and display data types of all columns.

    Args:
        data: List of dictionaries representing data rows
    """
    if not data:
        return "Error: No data provided"

    try:
        df = pd.DataFrame(data)
        columns = df.columns.tolist()

        result = f"Columns: {len(columns)}\n\n"

        for col in columns:
            dtype = str(df[col].dtype)
            non_null = df[col].notna().sum()
            unique = df[col].nunique()
            sample = df[col].dropna().iloc[0] if non_null > 0 else "N/A"

            result += f"{col}:\n"
            result += f"  Type: {dtype}\n"
            result += f"  Non-null: {non_null}/{len(df)}\n"
            result += f"  Unique values: {unique}\n"
            result += f"  Sample: {sample}\n\n"

        return result
    except Exception as e:
        return f"Error detecting data types: {str(e)}"


@mcp.tool()
async def find_missing_values(data: list[dict[str, Any]]) -> str:
    """Find and report missing values in data.

    Args:
        data: List of dictionaries representing data rows
    """
    if not data:
        return "Error: No data provided"

    try:
        df = pd.DataFrame(data)
        total = len(df)

        result = f"Missing Values Report (total rows: {total}):\n"

        has_missing = False
        for col in df.columns:
            missing = df[col].isna().sum()
            if missing > 0:
                has_missing = True
                pct = 100 * missing / total
                result += f"- {col}: {missing} ({pct:.1f}%)\n"

        if not has_missing:
            result += "No missing values found!"

        return result
    except Exception as e:
        return f"Error finding missing values: {str(e)}"


@mcp.tool()
async def group_and_aggregate(
    data: list[dict[str, Any]],
    group_by: str,
    aggregations: str = "count"
) -> str:
    """Group data and calculate aggregations.

    Args:
        data: List of dictionaries representing data rows
        group_by: Column name to group by
        aggregations: Comma-separated - "count", "sum", "avg", "min", "max" (default: "count")
    """
    if not data:
        return "Error: No data provided"

    try:
        df = pd.DataFrame(data)

        if group_by not in df.columns:
            return f"Error: Column '{group_by}' not found"

        agg_funcs = [a.strip().lower() for a in aggregations.split(",")]
        valid_funcs = {"count", "sum", "avg", "min", "max"}
        agg_funcs = [f for f in agg_funcs if f in valid_funcs]

        if not agg_funcs:
            return f"Error: No valid aggregation. Use: {', '.join(valid_funcs)}"

        # Get numeric columns for aggregation
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

        result_parts = []

        if "count" in agg_funcs:
            count_result = df.groupby(group_by).size().reset_index(name='count')
            result_parts.append(count_result.to_string(index=False))

        # Get numeric aggregations (sum, avg, min, max) for numeric columns
        numeric_aggs = [f for f in agg_funcs if f in {"sum", "avg", "min", "max"}]
        if numeric_aggs and numeric_cols:
            agg_result = df.groupby(group_by)[numeric_cols].agg(numeric_aggs).reset_index()
            result_parts.append(agg_result.to_string(index=False))

        if not result_parts:
            return "No aggregations to show (need numeric columns for sum/avg/min/max)"

        return "\n\n".join(result_parts)
    except Exception as e:
        return f"Error grouping data: {str(e)}"


@mcp.tool()
async def pivot_analysis(
    data: list[dict[str, Any]],
    index: str,
    columns: str,
    values: str,
    aggfunc: str = "sum"
) -> str:
    """Create pivot table analysis.

    Args:
        data: List of dictionaries representing data rows
        index: Column to use as index (row labels)
        columns: Column to use as columns (column labels)
        values: Column to aggregate
        aggfunc: Aggregation function - "sum", "avg", "count", "min", "max" (default: "sum")
    """
    if not data:
        return "Error: No data provided"

    try:
        df = pd.DataFrame(data)

        for col in [index, columns, values]:
            if col not in df.columns:
                return f"Error: Column '{col}' not found"

        pivot = pd.pivot_table(
            df,
            index=index,
            columns=columns,
            values=values,
            aggfunc=aggfunc,
            fill_value=0
        )

        return f"Pivot Table ({aggfunc} of {values} by {index} and {columns}):\n{pivot.to_string()}"
    except Exception as e:
        return f"Error creating pivot table: {str(e)}"


def main():
    # Initialize and run the server
    mcp.run(transport='stdio')


if __name__ == "__main__":
    main()

