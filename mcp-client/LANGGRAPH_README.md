# LangGraph với MCP Integration

Hướng dẫn sử dụng LangGraph để quản lý workflow phức tạp với MCP (Model Context Protocol) servers.

## Tổng Quan

LangGraph là một framework để xây dựng stateful, multi-actor applications với LLMs. Khi kết hợp với MCP, bạn có thể:

- ✅ **State Management**: Quản lý state tốt hơn với TypedDict
- ✅ **Conditional Routing**: Quyết định workflow dựa trên kết quả
- ✅ **Multi-step Workflows**: Xử lý các tác vụ phức tạp nhiều bước
- ✅ **Error Handling**: Xử lý lỗi và retry logic tốt hơn
- ✅ **Checkpointing**: Lưu và khôi phục state

## Cài Đặt

```bash
cd mcp-client
uv sync
```

Đảm bảo có file `.env` với `OPENAI_API_KEY`:

```env
OPENAI_API_KEY=your_api_key_here
```

## Sử Dụng

### Chạy Agent với một server

```bash
uv run langraph_agent.py ../database/database.py
```

### Chạy Agent với nhiều servers

```bash
uv run langraph_agent.py ../database/database.py ../excel-summary/excel_summary.py
```

## Kiến Trúc

### State Definition

```python
class AgentState(TypedDict):
    messages: Annotated[List[Any], add_messages]  # Lịch sử messages
    mcp_sessions: Dict[str, ClientSession]  # MCP sessions
    mcp_tools: Dict[str, List]  # Cached tools
    current_query: str  # Query hiện tại
    tool_results: List[Dict[str, Any]]  # Kết quả từ tool calls
    iteration_count: int  # Số lần iteration
    final_response: Optional[str]  # Response cuối cùng
```

### Graph Workflow

```
┌─────────┐
│  Agent  │ (LLM với tools)
└────┬────┘
     │
     ├─[có tool calls?]─→ ┌────────────┐
     │                    │ Call Tools │ (Gọi MCP tools)
     │                    └─────┬──────┘
     │                          │
     │                          └──→ [quay lại Agent]
     │
     └─[không có tool calls]─→ ┌──────────┐
                                │ Finalize │ (Tạo response)
                                └─────┬────┘
                                      │
                                      └──→ END
```

### Nodes

1. **Agent Node**: Xử lý query với LLM, quyết định gọi tools nào
2. **Call Tools Node**: Gọi MCP tools và xử lý kết quả
3. **Finalize Node**: Tạo final response từ messages

### Conditional Edges

- Nếu LLM muốn gọi tools → điều hướng đến "call_tools"
- Nếu không có tool calls → điều hướng đến "end"
- Giới hạn 10 iterations để tránh infinite loop

## So Sánh với Agent Thông Thường

### Agent Thông Thường (`agent.py`)

- ✅ Đơn giản, dễ hiểu
- ✅ Phù hợp cho use cases đơn giản
- ❌ Khó mở rộng cho workflows phức tạp
- ❌ State management thủ công

### LangGraph Agent (`langraph_agent.py`)

- ✅ State management tự động
- ✅ Dễ mở rộng với nhiều nodes
- ✅ Conditional routing linh hoạt
- ✅ Checkpointing và recovery
- ❌ Phức tạp hơn cho use cases đơn giản

## Ví Dụ Workflow

### Workflow Đơn Giản

```
User Query → Agent → [No tools] → Finalize → Response
```

### Workflow Phức Tạp

```
User Query → Agent → [Tool calls] → Call Tools → Agent → [More tools] → Call Tools → Agent → [No tools] → Finalize → Response
```

## Tùy Chỉnh

### Thêm Nodes Mới

```python
def my_custom_node(state: AgentState) -> AgentState:
    # Xử lý logic của bạn
    return {"messages": [...], ...}

workflow.add_node("my_node", my_custom_node)
```

### Thêm Conditional Logic

```python
def my_condition(state: AgentState) -> Literal["path1", "path2"]:
    # Logic quyết định
    if condition:
        return "path1"
    return "path2"

workflow.add_conditional_edges(
    "my_node",
    my_condition,
    {"path1": "node1", "path2": "node2"}
)
```

### Thêm System Prompt

```python
def agent_node(state: AgentState) -> AgentState:
    messages = state["messages"]
    # Thêm system message
    messages_with_system = [
        SystemMessage(content="You are a helpful assistant..."),
        *messages
    ]
    response = await llm.ainvoke(messages_with_system)
    return {"messages": [response]}
```

## Best Practices

1. **Giới hạn iterations**: Luôn có giới hạn để tránh infinite loops
2. **Error handling**: Xử lý lỗi trong tool calls
3. **State validation**: Kiểm tra state trước khi sử dụng
4. **Checkpointing**: Sử dụng checkpointer để lưu state
5. **Verbose logging**: Log chi tiết để debug

## Troubleshooting

### Lỗi: "Tool not found"

- Kiểm tra xem MCP server đã kết nối chưa
- Kiểm tra tên tool có đúng không
- Xem logs để biết tools nào có sẵn

### Lỗi: "Infinite loop"

- Kiểm tra `should_continue` function
- Đảm bảo có giới hạn `iteration_count`
- Kiểm tra tool calls có trả về đúng format không

### Lỗi: "State not found"

- Đảm bảo state được khởi tạo đúng
- Kiểm tra TypedDict definition
- Xem logs để debug state

## Tài Liệu Tham Khảo

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Documentation](https://python.langchain.com/)
- [MCP Protocol](https://modelcontextprotocol.io/)

