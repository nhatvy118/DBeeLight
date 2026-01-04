# Excel Summary & Chart Generator UI

Web UI để upload Excel files, tạo summary và generate charts sử dụng MCP excel-summary server tools.

## Cài Đặt

1. Cài đặt dependencies:
```bash
cd excel-ui
uv sync
```

2. Đảm bảo excel-summary server dependencies đã được cài đặt:
```bash
cd ../excel-summary
uv sync
```

## Chạy Ứng Dụng

```bash
cd excel-ui
uv run app.py
```

Sau đó mở browser tại: http://localhost:5000

## Tính Năng

### 1. Upload Excel File
- Drag & drop hoặc click để upload
- Hỗ trợ .xlsx và .xls files
- Tự động import và preview data

### 2. Data Summary
- Generate summary với statistics
- Hiển thị row count, column info, numeric statistics

### 3. Chart Generation
- Hỗ trợ nhiều loại charts:
  - Bar Chart
  - Line Chart
  - Pie Chart
  - Scatter Plot
  - Histogram
- Tự động suggest chart types phù hợp
- Custom chart title

## API Endpoints

### POST `/api/upload`
Upload Excel file và import data.

**Request:** multipart/form-data với file field

**Response:**
```json
{
  "success": true,
  "message": "...",
  "filename": "data.xlsx",
  "data": [...]
}
```

### POST `/api/summary`
Generate summary từ data.

**Request:**
```json
{
  "data": [...]
}
```

**Response:**
```json
{
  "success": true,
  "summary": "..."
}
```

### POST `/api/suggest-charts`
Get chart type suggestions.

**Request:**
```json
{
  "data": [...]
}
```

### POST `/api/generate-chart`
Generate chart từ data.

**Request:**
```json
{
  "chart_type": "bar",
  "data": [...],
  "title": "Optional title"
}
```

**Response:**
```json
{
  "success": true,
  "chart_url": "/static/charts/chart_xxx.png"
}
```

## Cấu Trúc

```
excel-ui/
├── app.py              # Flask backend
├── templates/
│   └── index.html      # Frontend HTML
├── static/
│   ├── css/
│   │   └── style.css   # Styles
│   ├── js/
│   │   └── app.js      # Frontend JavaScript
│   └── charts/         # Generated charts
├── uploads/            # Uploaded files
└── pyproject.toml
```

## Lưu Ý

- Files được lưu trong `uploads/` directory
- Charts được lưu trong `static/charts/` directory
- Max file size: 16MB
- Cần có excel-summary server dependencies để hoạt động

