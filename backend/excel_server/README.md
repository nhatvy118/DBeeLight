# excel-server (HTTP MCP)

Wrapper triển khai cho [`excel-mcp-server`](https://github.com/haris-musa/excel-mcp-server)
(haris-musa, MIT) chạy ở chế độ **streamable-http** — đây là MCP server *duy nhất* còn
tách process trong kiến trúc mới (vì là code bên thứ ba).

## Chạy

```bash
# trực tiếp
pip install "excel-mcp-server>=0.1.8"
FASTMCP_PORT=8931 EXCEL_FILES_PATH=/data/uploads python -m excel_mcp streamable-http
# → phục vụ MCP tại http://localhost:8931/mcp

# hoặc docker
docker compose up excel-server
```

## Env

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `FASTMCP_HOST` | `0.0.0.0` | host bind |
| `FASTMCP_PORT` | `8931` (đặt trong Dockerfile) | port |
| `EXCEL_FILES_PATH` | `/data/uploads` | thư mục chứa `.xlsx` — **phải là shared volume** với api-server |

## Lưu ý quan trọng (storage §8)

Tool Excel nhận **đường dẫn tương đối** so với `EXCEL_FILES_PATH`. api-server ghi file
upload vào `DATA_ROOT/uploads/<session>/<filename>` (cùng volume), nên path truyền cho
tool là `"<session>/<filename>"`. Cả hai container phải mount chung volume `filedata`.
