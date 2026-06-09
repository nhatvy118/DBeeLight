# Excel MCP server (bên thứ ba: haris-musa/excel-mcp-server) chạy ở chế độ HTTP.
# Không cần wrapper custom — package tự hỗ trợ transport streamable-http.
FROM python:3.12-slim

RUN pip install --no-cache-dir "excel-mcp-server>=0.1.8"

ENV FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8931 \
    EXCEL_FILES_PATH=/data/uploads

EXPOSE 8931
# Mount tại /mcp:8931 ; api-server nối qua EXCEL_MCP_URL=http://excel-server:8931/mcp
CMD ["python", "-m", "excel_mcp", "streamable-http"]
