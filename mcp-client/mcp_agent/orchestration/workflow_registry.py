"""Workflow registry - descriptions of all available workflows for intent classification.

This file provides structured descriptions of each workflow's capabilities.
IntentService uses this to select the right workflow for a user request.
If no workflow matches, the request falls back to a general-purpose agent.
"""

from typing import List

# Each workflow has:
#   id: unique identifier used for routing
#   name: human-readable name
#   agent_type: which agent handles this ("database", "excel", "chart")
#   triggers: keywords/patterns that indicate this workflow
#   description: brief description for intent classification
#   example_queries: sample user queries that match this workflow

DATABASE_WORKFLOWS = [
    {
        "id": "db_readonly",
        "name": "Database Read-Only Query",
        "agent_type": "database",
        "triggers": [
            "select", "query", "show", "list", "count", "sum", "average",
            "find", "search", "get", "describe", "structure", "schema",
            "table info", "thông tin bảng", "liệt kê", "xem dữ liệu",
            "bao nhiêu", "có bao nhiêu", "tổng", "trung bình",
        ],
        "description": "Read-only SQL queries: SELECT, list tables, describe table structure. No data modification. Connection management uses db_general.",
        "example_queries": [
            "Select all users older than 25",
            "Show me the bicycle table structure",
            "List all tables in the database",
            "How many orders were placed yesterday?",
            "What columns does the product table have?",
        ],
    },
    {
        "id": "db_create_table",
        "name": "Database Create Table",
        "agent_type": "database",
        "triggers": [
            "create table", "tạo bảng", "thêm bảng", "new table",
            "define table", "bảng mới", "tạo cấu trúc",
        ],
        "description": "Create new database tables with schema preview and human approval before execution.",
        "example_queries": [
            "Create a table for storing user preferences",
            "Tạo bảng employee với các cột name, email, department",
        ],
    },
    {
        "id": "db_mutation",
        "name": "Database Data Mutation",
        "agent_type": "database",
        "triggers": [
            "insert", "update", "delete", "drop", "alter", "add column",
            "thêm dữ liệu", "sửa dữ liệu", "xóa dữ liệu", "cập nhật",
            "chèn", "bổ sung", "loại bỏ", "export dữ liệu", "xuất dữ liệu",
            "sao chép dữ liệu", "copy data", "move data",
        ],
        "description": "Data modification operations: INSERT, UPDATE, DELETE, ALTER, DROP, export to file. Requires SQL preview and human approval before execution.",
        "example_queries": [
            "Insert a new row into the users table",
            "Update all product prices by 10%",
            "Delete orders older than 2020",
            "Drop the temp_events table",
            "Export all user data to CSV",
            "Thêm một bản ghi vào bảng inventory",
        ],
    },
]

EXCEL_WORKFLOWS = [
    {
        "id": "excel_manipulate",
        "name": "Excel Workbook Manipulation",
        "agent_type": "excel",
        "triggers": [
            "excel", "spreadsheet", "xlsx", "xls",
            "worksheet", "sheet", "cell", "column", "row",
            "formula", "pivot", "chart in excel", "format cells",
            "file excel", "bảng tính", "công thức", "định dạng ô",
        ],
        "description": "Manipulate Excel workbooks: read/write cells and ranges, format ranges, apply formulas, create charts and pivot tables, manage worksheets.",
        "example_queries": [
            "Read sheet 'Sales' from this workbook",
            "Write totals to column D using a SUM formula",
            "Create a pivot table grouping by Category",
            "Format A1:E1 with a bold header",
            "Insert a bar chart for the data in A1:C20",
        ],
    },
]

CHART_WORKFLOWS = [
    {
        "id": "chart_render",
        "name": "Chart Visualization",
        "agent_type": "chart",
        "triggers": [
            "chart", "graph", "visualization", "plot",
            "biểu đồ", "đồ thị", "trực quan",
            "bar chart", "line chart", "pie chart", "scatter",
            "histogram", "heatmap", "boxplot", "area chart",
        ],
        "description": "Render an interactive Vega-Lite chart from data in the project's database. Writes SQL, executes against the active connection, returns a Vega-Lite v5 spec the frontend can render directly.",
        "example_queries": [
            "Show me monthly sales as a line chart",
            "Top 5 customers by revenue as a bar chart",
            "Distribution of order amounts (histogram)",
            "Tạo biểu đồ đường thể hiện doanh số theo tháng",
        ],
    },
]

# Combined registry
ALL_WORKFLOWS = {
    "database": DATABASE_WORKFLOWS,
    "excel": EXCEL_WORKFLOWS,
    "chart": CHART_WORKFLOWS,
}


def get_workflow_descriptions() -> str:
    """Return a formatted string of all workflow descriptions for LLM context."""
    lines = ["Available workflows:\n"]

    for agent_type, workflows in ALL_WORKFLOWS.items():
        lines.append(f"\n## {agent_type.upper()} Agent Workflows")
        for wf in workflows:
            lines.append(f"\n### [{wf['id']}] {wf['name']}")
            lines.append(f"Description: {wf['description']}")
            lines.append(f"Triggers: {', '.join(wf['triggers'][:10])}")
            lines.append(f"Examples: {'; '.join(wf['example_queries'][:2])}")

    lines.append("\n\n## Fallback")
    lines.append("If no workflow matches, the request will be handled by a general-purpose agent")
    lines.append("that can call any available tools dynamically without a predefined workflow.")

    return "\n".join(lines)


def get_workflow_ids() -> List[str]:
    """Return flat list of all workflow IDs."""
    return [wf["id"] for workflows in ALL_WORKFLOWS.values() for wf in workflows]


def get_workflow_by_id(workflow_id: str) -> dict | None:
    """Get workflow config by ID."""
    for workflows in ALL_WORKFLOWS.values():
        for wf in workflows:
            if wf["id"] == workflow_id:
                return wf
    return None


def get_workflow_by_agent(agent_type: str) -> List[dict]:
    """Get all workflows for a specific agent type."""
    return ALL_WORKFLOWS.get(agent_type, [])
