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


def main():
    # Initialize and run the server
    mcp.run(transport='stdio')


if __name__ == "__main__":
    main()

