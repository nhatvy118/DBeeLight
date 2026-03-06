## Routing issues & proposed fix

### Hiện tượng bug

- Khi click vào một session trong **Chat History** ở sidebar:
  - URL thanh địa chỉ thay đổi (ví dụ từ `/chat` sang `/chat/<sessionId>`).
  - Nhưng UI chính đôi khi bị **trắng** (không render Chat), chỉ khi bấm **reload** trang mới hiện lại đúng.

### Nguyên nhân gốc

- App hiện tại **tự quản lý routing** bằng `window.history.pushState` + `PopStateEvent`:
  - `MainLayout` có state riêng `path` (lắng nghe `popstate` để quyết định có hiển thị sidebar, v.v.).
  - `AppRoutes` cũng có state riêng `path` (lắng nghe `popstate` để quyết định render `Chat`, `Home`, `Login`, ...).
  - `Sidebar` và một số chỗ khác gọi trực tiếp:
    - `window.history.pushState({}, '', path);`
    - `window.dispatchEvent(new PopStateEvent('popstate'));`
- Vì có **nhiều nguồn state `path` khác nhau**, đôi khi:
  - URL đã đổi nhưng `AppRoutes`/`MainLayout` chưa kịp sync,
  - dẫn tới vùng nội dung chính trả về `null` hoặc component không phù hợp → người dùng thấy **trang trắng** cho tới khi reload.

### Hướng refactor đề xuất (dùng `react-router-dom`)

Mục tiêu: để **router là single source of truth**, tránh tự quản lý `path` bằng `useState` và `popstate`.

#### 1. Cài đặt thư viện

Trong thư mục `frontend`:

```bash
npm install react-router-dom
# hoặc
yarn add react-router-dom
# hoặc
pnpm add react-router-dom
```

#### 2. Bọc app bằng `BrowserRouter`

File `App.tsx`:

```tsx
import { BrowserRouter } from 'react-router-dom';
import { useState } from 'react';
import { AuthProvider } from './context/AuthContext';
import MainLayout from './components/layout/MainLayout';
import AppRoutes from './routes/AppRoutes';

export default function App() {
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);

  return (
    <AuthProvider>
      <BrowserRouter>
        <MainLayout currentSessionId={currentSessionId} onSessionSelect={setCurrentSessionId}>
          <AppRoutes sessionId={currentSessionId} onSessionIdChange={setCurrentSessionId} />
        </MainLayout>
      </BrowserRouter>
    </AuthProvider>
  );
}
```

#### 3. Đơn giản hoá `AppRoutes` để dùng router thay vì tự giữ `path`

Ý tưởng chính:

- Thay state `path` + listener `popstate` bằng `useLocation` / `Routes` / `Route`.
- Dùng `useParams` để lấy `projectId` / `sessionId` rồi truyền vào `Chat`.
- Dùng `Navigate` để xử lý redirect theo trạng thái đăng nhập.

Phác thảo (pseudo-code, chưa phải code cuối cùng):

```tsx
import { Routes, Route, Navigate, useParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Chat from '../pages/Chat';
import Home from '../pages/Home';
import Login from '../pages/Login';
import SignUp from '../pages/SignUp';
import Account from '../pages/Account';
import NotFound from '../pages/NotFound';

function ChatRouteWrapper({ onSessionIdChange }: { onSessionIdChange: (id: string | null) => void }) {
  const { projectId, sessionId } = useParams<'projectId' | 'sessionId'>();
  return <Chat projectId={projectId ?? null} sessionId={sessionId ?? null} onSessionIdChange={onSessionIdChange} />;
}

export default function AppRoutes({ onSessionIdChange }: { onSessionIdChange: (id: string | null) => void }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return null;

  const isAuthenticated = !!user;

  return (
    <Routes>
      <Route path="/" element={isAuthenticated ? <Navigate to="/chat" replace /> : <Home />} />
      <Route path="/login" element={isAuthenticated ? <Navigate to="/chat" replace /> : <Login />} />
      <Route path="/signup" element={isAuthenticated ? <Navigate to="/chat" replace /> : <SignUp />} />

      <Route
        path="/chat"
        element={
          isAuthenticated ? (
            <Chat projectId={null} sessionId={null} onSessionIdChange={onSessionIdChange} />
          ) : (
            <Navigate to="/" replace />
          )
        }
      />

      <Route
        path="/chat/:sessionId"
        element={
          isAuthenticated ? (
            <ChatRouteWrapper onSessionIdChange={onSessionIdChange} />
          ) : (
            <Navigate to="/" replace />
          )
        }
      />

      <Route
        path="/chat/:projectId/:sessionId"
        element={
          isAuthenticated ? (
            <ChatRouteWrapper onSessionIdChange={onSessionIdChange} />
          ) : (
            <Navigate to="/" replace />
          )
        }
      />

      <Route path="/account" element={isAuthenticated ? <Account /> : <Navigate to="/" replace />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
```

#### 4. Cập nhật `MainLayout` để dùng `useLocation`

Thay vì tự giữ `path` và nghe `popstate`, `MainLayout` chỉ cần:

```tsx
import { useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

export default function MainLayout(...) {
  const location = useLocation();
  const { user, isLoading } = useAuth();

  const showSidebar = location.pathname.startsWith('/chat') && user !== null && !isLoading;

  // phần còn lại giữ nguyên
}
```

#### 5. Cập nhật `Sidebar` để dùng `useNavigate`

- Bỏ hàm `navigate` tự viết dùng `window.history.pushState`.
- Dùng hook `useNavigate`:

```tsx
import { useNavigate, useLocation } from 'react-router-dom';

const navigate = useNavigate();

// Ví dụ click session:
navigate(`/chat/${sessionId}`);

// Project:
navigate(`/chat/${project.id}`);
```

#### 6. Ghi chú quan trọng

- Sau khi chuyển sang `react-router-dom`:
  - **Không nên** dùng `window.history.pushState` + `PopStateEvent` thủ công nữa.
  - Router là single source of truth cho URL → UI luôn sync với URL.
  - Vấn đề “URL đổi nhưng màn hình trắng cho tới khi reload” sẽ được loại bỏ.

