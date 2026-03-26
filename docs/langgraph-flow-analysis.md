# Phân tích chi tiết LangGraph và flow trong project hiện tại

## Tổng quan

Project đang dùng mô hình **Hybrid Orchestrator**:
- Query đơn giản/follow-up: đi thẳng `BaseAgent.process_query()`
- Query phức tạp: đi qua **LangGraph workflow**

LangGraph nằm ở `mcp-client/mcp_agent/graph/`.

---

## 1) Điểm vào chính từ API

### `POST /api/chat`
- Controller gọi `ChatUseCase.chat(...)`
- UseCase lấy orchestrator từ `AgentRepository.get_agent(user_key)`
- Orchestrator là `HybridOrchestrator`
- `HybridOrchestrator.process_query(...)` sẽ:
  1. Chọn agent (`database` hoặc `excel`)
  2. Classify intent/complexity bằng `IntentRouter`
  3. Chọn cách xử lý:
     - `llm_driven`
     - `conversational`
     - `workflow` (LangGraph)

### `POST /api/sql/execute`
- Đi vào `ChatUseCase.execute_sql(...)`
- Nếu orchestrator có `approve_and_execute`, usecase gọi nhánh đó.
- Đây là flow approval riêng ở orchestrator-level.

---

## 2) Các file LangGraph quan trọng

- `mcp-client/mcp_agent/graph/base_workflow.py`
  - Base class build graph bằng `StateGraph`
  - Add node/edge theo config
  - Hỗ trợ wait stage qua `wait_user`

- `mcp-client/mcp_agent/graph/state.py`
  - Enum `StageType`
  - `AgentWorkflowConfig`
  - Config sẵn cho:
    - `DATABASE_WORKFLOW`
    - `EXCEL_WORKFLOW`

- `mcp-client/mcp_agent/graph/graph_state.py`
  - `AgentState` (TypedDict)
  - `create_initial_state(...)`

- `mcp-client/mcp_agent/graph/database_workflow.py`
  - Workflow riêng cho DB

- `mcp-client/mcp_agent/graph/excel_workflow.py`
  - Workflow riêng cho Excel

- `mcp-client/mcp_agent/graph/workflow.py`
  - `AgentWorkflow`: router vào workflow cụ thể theo `agent_type`

---

## 3) Hybrid orchestration flow chi tiết

Trong `mcp-client/mcp_agent/hybrid_orchestrator.py`:

1. `_route_to_agent(query)`
   - Dùng LLM route về `database` hoặc `excel`
2. `IntentRouter.classify(query, agent_id)`
   - Trả JSON gồm:
     - `intent`
     - `complexity` (`simple|complex|conversational`)
     - `requires_approval`
     - `requires_workflow`
3. Quyết định handler:
   - `conversational` -> `_handle_conversational` -> BaseAgent
   - `complex` hoặc `requires_workflow` -> `_handle_workflow`
   - còn lại -> `_handle_llm_driven` -> BaseAgent

Nếu vào `_handle_workflow`:
- Nếu `requires_approval` -> `_handle_with_approval` (flow riêng orchestrator)
- Nếu không -> `_run_workflow` -> gọi `self.workflow.run(...)` (LangGraph)

---

## 4) AgentWorkflow (router của LangGraph)

Trong `graph/workflow.py`:
- `AgentWorkflow._init_workflows(...)` tạo:
  - `DatabaseAgentWorkflow`
  - `ExcelAgentWorkflow`
- `run(session_id, user_message, agent_type)`
  - Chọn workflow theo `agent_type`
  - Gọi `workflow.run(...)`

---

## 5) Cấu trúc state trong graph

`AgentState` gồm các nhóm chính:
- Session: `session_id`, `current_stage`, `agent_type`
- User input: `user_message`
- Intent: `intent`, `detected_language`
- Database context: `tables`, `sql`, `query_result`, ...
- Excel context: `file_path`, `sheet_name`, `data`, ...
- Flow control: `wait_user`, `approved`, `error`, `retry_count`
- Output cho UI/API: `output`

State được tạo từ `create_initial_state(...)`.

---

## 6) BaseAgentWorkflow build graph như thế nào

Trong `base_workflow.py`:

1. Tạo `StateGraph(AgentState)`
2. Add node cho từng stage từ `workflow_config.stages`
   - Nếu có handler thì gọi handler thật
   - Nếu không có thì pass-through
3. Add `START` node -> set stage đầu
4. Add `ERROR` node
5. Add edges theo `transitions`
6. Với stage nằm trong `wait_stages`:
   - dùng `add_conditional_edges` theo `_should_wait`
   - `wait` -> stay tại stage
   - `proceed` -> qua stage sau
7. `DONE -> END`, `ERROR -> END`
8. `graph.compile()` và `ainvoke(state)`

---

## 7) Database workflow chi tiết

File: `database_workflow.py`

### Stages
1. `INTENT_PARSE`
2. `SCHEMA_DISCOVERY`
3. `SQL_GENERATION`
4. `SQL_PREVIEW` (wait stage)
5. `SQL_EXECUTION`
6. `DONE`

### Ý nghĩa từng stage

- `INTENT_PARSE`
  - Parse operation/tables/filters/export/language bằng LLM

- `SCHEMA_DISCOVERY`
  - Delegate cho BaseAgent gọi tool schema (`list_tables`, `describe_table`)

- `SQL_GENERATION`
  - Nếu SELECT đơn giản có thể generate+execute trực tiếp qua agent
  - Nếu mutation/export: generate SQL và đặt `wait_user=True`

- `SQL_PREVIEW`
  - Chưa approved -> giữ trạng thái chờ
  - Approved -> cho đi tiếp `SQL_EXECUTION`

- `SQL_EXECUTION`
  - Delegate BaseAgent thực thi SQL qua MCP

---

## 8) Excel workflow chi tiết

File: `excel_workflow.py`

### Stages
1. `INTENT_PARSE`
2. `FILE_LOAD`
3. `DATA_ANALYZE`
4. `DATA_TRANSFORM`
5. `CHART_GENERATE`
6. `EXPORT`
7. `DONE`

### Ý nghĩa từng stage
- Parse intent excel
- Load file
- Analyze dữ liệu
- Transform dữ liệu
- Generate chart
- Export

Toàn bộ stage đều delegate xuống `BaseAgent.process_query(...)`.

---

## 9) IntentRouter chi tiết

File: `intent_router.py`

Router phân loại:
- Intent nghiệp vụ
- Complexity
- Có cần approval không
- Có cần workflow không
- Suggested tools

Quyết định route cuối:
- `conversational` -> conversational handler
- `complex` hoặc `requires_workflow=true` -> workflow
- còn lại -> llm_driven

---

## 10) Approval flow: thực tế vs thiết kế graph

Đây là điểm quan trọng nhất của project hiện tại.

### Thiết kế trong LangGraph
- Database workflow có `SQL_PREVIEW` và `wait_user`
- Có thể resume bằng `continue_from_stage(...)`

### Thực tế đang chạy
- `HybridOrchestrator._handle_with_approval(...)` dùng state riêng `_session_states`
- Generate SQL preview bằng BaseAgent
- Khi user bấm execute, `approve_and_execute(...)` chạy SQL trực tiếp
- API execute_sql đang ưu tiên nhánh orchestrator này

=> Nghĩa là approval hiện tại **không hoàn toàn đi theo resume graph chuẩn**, mà dùng lớp orchestrator làm gate.

---

## 11) Luồng end-to-end (as-is)

```text
Frontend
  -> POST /api/chat
  -> ChatUseCase.chat
  -> AgentRepository.get_agent
  -> HybridOrchestrator.process_query
       -> route_to_agent
       -> intent_router.classify
       -> if simple/conversational:
             BaseAgent.process_query
          else if complex:
             if requires_approval:
                _handle_with_approval (orchestrator state)
             else:
                AgentWorkflow.run (LangGraph)
                   -> DatabaseWorkflow / ExcelWorkflow
                   -> each stage delegates BaseAgent.process_query
  -> return response
```

Execute SQL:

```text
Frontend
  -> POST /api/sql/execute
  -> ChatUseCase.execute_sql
  -> HybridOrchestrator.approve_and_execute (if available)
  -> execute SQL via DB agent/session tool
  -> return result
```

---

## 12) Đánh giá nhanh

### Điểm mạnh
- Hybrid approach hợp lý cho hiệu năng + kiểm soát
- Tách module rõ ràng
- LangGraph state/stage khá đầy đủ
- Dễ mở rộng thêm agent/stage mới

### Điểm cần chú ý
- Approval hiện có 2 lớp (graph + orchestrator) -> có thể lệch behavior
- Resume graph chưa là đường chính cho execute
- Output giữa các stage còn mang tính text tự do, khó chuẩn hóa UI

---

## 13) Đề xuất cải tiến (nếu muốn chuẩn hóa)

1. Chọn 1 mô hình approval duy nhất:
   - hoặc full trong LangGraph (khuyến nghị)
   - hoặc full ngoài graph
2. Chuẩn hóa `output` schema theo `output.type`
3. Bổ sung stage telemetry (enter/exit/duration/error)
4. Nếu cần resume sau restart: cân nhắc persist graph state theo session

---

## 14) Kết luận

Trong project hiện tại, LangGraph đã được dùng đúng vai trò cho tác vụ phức tạp và đã có workflow riêng cho database/excel. Tuy nhiên, nhánh approval SQL đang được thực thi chủ yếu ở orchestrator-level. Nếu thống nhất lại approval vào một chỗ, kiến trúc sẽ dễ bảo trì và dễ mở rộng hơn đáng kể.
