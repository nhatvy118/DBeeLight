# MCP Excel & Summary Server

MCP Server cung cấp các công cụ để import/export Excel và tạo visualizations/summaries từ dữ liệu.

## Cài Đặt

1. Cài đặt dependencies:
```bash
cd excel-summary
uv sync
```

## Các Tools Có Sẵn

### 1. `import_excel`
Import dữ liệu từ file Excel (.xlsx, .xls).

**Parameters:**
- `path`: Đường dẫn đến file Excel

**Ví dụ:**
- "Import data from /path/to/data.xlsx"
- "Load Excel file from ./data.xlsx"

### 2. `export_excel`
Export dữ liệu ra file Excel.

**Parameters:**
- `path`: Đường dẫn để lưu file Excel
- `data`: List of dictionaries chứa dữ liệu

**Ví dụ:**
- "Export this data to output.xlsx"
- "Save results to /path/to/results.xlsx"

### 3. `render_chart`
Render biểu đồ từ data specification.

**Parameters:**
- `chart_type`: Loại biểu đồ - "bar", "line", "pie", "scatter", "histogram"
- `data_spec`: JSON string với specification (x, y, labels, values, etc.)

**Ví dụ:**
- "Create a bar chart with this data"
- "Render a pie chart showing distribution"

### 4. `suggest_charts`
Gợi ý loại biểu đồ phù hợp dựa trên query và schema.

**Parameters:**
- `query`: SQL query hoặc data query
- `result_schema`: JSON string mô tả schema của kết quả

**Ví dụ:**
- "What charts would be good for this data?"
- "Suggest visualizations for this query result"

### 5. `generate_chart_spec`
Tạo chart specification từ dữ liệu.

**Parameters:**
- `chart_type`: Loại biểu đồ
- `data`: List of dictionaries chứa dữ liệu

**Ví dụ:**
- "Generate bar chart spec from this data"
- "Create pie chart specification"

### 6. `describe_result_summary`
Tạo summary mô tả kết quả query.

**Parameters:**
- `data`: List of dictionaries chứa dữ liệu

**Ví dụ:**
- "Summarize this query result"
- "Describe the statistics of this data"

## Sử Dụng

### Chạy Server:
```bash
cd excel-summary
uv run excel_summary.py
```

### Sử dụng với Client:
```bash
cd ../mcp-client
uv run client.py ../excel-summary/excel_summary.py
```

## Dependencies

- `pandas`: Xử lý dữ liệu
- `openpyxl`: Đọc/ghi Excel files
- `matplotlib`: Tạo biểu đồ

## Lưu Ý

- Server sẽ tự động kiểm tra dependencies và báo lỗi nếu thiếu
- Charts được lưu dưới dạng PNG files
- Excel files hỗ trợ format .xlsx và .xls

