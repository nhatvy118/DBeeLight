# Project-Specific Chat History Implementation

## Tổng quan
Đã cải tiến hệ thống chat để mỗi project có lịch sử chat (session) riêng biệt. Trước đây, tất cả sessions được lưu chung và sử dụng localStorage để map với projects. Giờ đây, mỗi session được gắn với `project_id` ngay từ backend.

## Các thay đổi chính

### 1. Backend Changes

#### a) Schemas (`api-server/internal/controllers/schemas.py`)
- **ChatRequest**: Thêm field `project_id: Optional[str] = None`
- **NewSessionRequest**: Thêm field `project_id: Optional[str] = None`

#### b) SessionManager (`mcp-client/agent.py`)
- **create_session()**: Thêm parameter `project_id`, lưu vào session metadata
- **list_sessions()**: Thêm parameter `project_id` để filter sessions theo project
- **get_session_info()**: Trả về thêm field `project_id`

#### c) Chat UseCase (`api-server/internal/usecases/chat_usecase.py`)
- **chat()**: 
  - Thêm parameter `project_id`
  - Tự động tạo session mới với `project_id` nếu chưa có session
  - Gửi `project_id` khi tạo session mới

#### d) Sessions UseCase (`api-server/internal/usecases/sessions_usecase.py`)
- **list_sessions()**: Thêm parameter `project_id` để filter
- **create_session()**: Thêm parameter `project_id`

#### e) Controllers
- **chat_controller.py**: Gửi `req.project_id` vào usecase
- **sessions_controller.py**: 
  - GET `/api/sessions`: Hỗ trợ query parameter `?project_id=xxx`
  - POST `/api/sessions/new`: Nhận và xử lý `project_id` từ request body

### 2. Frontend Changes

#### a) API Service (`frontend/src/services/api.ts`)
- **SessionInfo type**: Thêm field `project_id?: string | null`
- **sendMessage()**: Thêm parameter `projectId` và gửi trong request body
- **getSessions()**: Thêm parameter `projectId`, gửi qua query string
- **createSession()**: Thêm parameter `projectId`

#### b) Chat Component (`frontend/src/pages/Chat.tsx`)
- **doSend()**: 
  - Gửi `selectedProject?.id` khi call `sendMessage()`
  - Đơn giản hóa logic - không cần lưu vào localStorage nữa
  - Chỉ cần reload sessions sau khi tạo session mới
- **handleRefreshResponse()**: Gửi `project_id` khi refresh
- **loadProjectSessions()**: 
  - Gọi `getSessions(selectedProject.id)` để lấy sessions đã được filter từ backend
  - Không cần filter ở frontend nữa

#### c) Sidebar Component (`frontend/src/components/layout/Sidebar.tsx`)
- **handleNewChat()**: Tạo session với `project_id = null` (unassigned)
- **getUnassignedSessions()**: 
  - Đơn giản hóa - chỉ filter sessions có `project_id` null/undefined
  - Không cần dùng localStorage nữa
- **handleSessionClick()**: Check `project_id` từ session object thay vì localStorage

## Lợi ích của cải tiến

1. **Data Consistency**: Session data giờ được quản lý tập trung ở backend, không bị conflict giữa client và server
2. **Scalability**: Có thể dễ dàng sync sessions giữa nhiều devices/browsers
3. **Simplicity**: Frontend code đơn giản hơn, không cần quản lý mapping localStorage
4. **Reliability**: Không còn phụ thuộc vào localStorage có thể bị xóa/corrupt
5. **Multi-user**: Dễ dàng mở rộng để support nhiều users, mỗi user có projects và sessions riêng

## Cách hoạt động

### Khi tạo chat mới trong project:
1. User chọn project trong Sidebar
2. User gửi message đầu tiên
3. Frontend gửi `project_id` cùng với message
4. Backend tạo session mới với `project_id` trong metadata
5. Session được lưu vào file JSON với field `project_id`

### Khi load history của project:
1. User chọn project
2. Frontend gọi `getSessions(project_id)`
3. Backend filter sessions có `project_id` matching
4. Chỉ sessions thuộc project đó được hiển thị

### Khi tạo chat không gắn project:
1. User click "New chat" trong Sidebar (không chọn project)
2. Session được tạo với `project_id = null`
3. Hiển thị trong phần "Chats" (unassigned)

## Migration Note

Sessions cũ (đã tồn tại trước khi implement) sẽ không có field `project_id`, được coi là unassigned sessions. Nếu muốn migrate, có thể:
1. Đọc localStorage `projectSessions` để biết sessions thuộc project nào
2. Update file JSON của từng session, thêm field `project_id`
3. Sau đó có thể xóa localStorage `projectSessions`

## Testing Checklist

- [ ] Tạo project mới và chat trong project đó
- [ ] Chuyển đổi giữa các projects, verify sessions riêng biệt
- [ ] Tạo unassigned chat (không chọn project)
- [ ] Load lại trang, verify sessions vẫn đúng project
- [ ] Kiểm tra session files trong `api-server/sessions/<user_key>/` có field `project_id`

