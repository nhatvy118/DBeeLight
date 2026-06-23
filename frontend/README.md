# Frontend - AI Chat App

React application với Tailwind CSS được thiết kế theo giao diện AI Chat.

## Yêu cầu

- Node.js + npm
- Backend chạy ở `http://localhost:5001` (API server)
- Google OAuth2 credentials (lưu ở backend): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`

## Cài đặt

```bash
npm install
```

## Chạy ứng dụng

```bash
npm run dev
```

Ứng dụng sẽ chạy tại `http://localhost:5173`

## Routes (các trang có thể mở)

Hiện tại project dùng **routing tối thiểu (không dùng react-router)**, implement trong `src/routes/AppRoutes.tsx`.

- `GET /` → `src/pages/Home.tsx`
- `GET /chat` → `src/pages/Chat.tsx`
- Các path khác → `src/pages/NotFound.tsx`

> Nếu deploy lên Vercel (hoặc hosting static khác), cần **SPA fallback** để deep link
> như `/login`, `/chat` không bị 404. Project đã có ``frontend/vercel.json`` (rewrite → ``index.html``).
> Tương tự nginx: ``try_files $uri $uri/ /index.html`` trong ``nginx.conf``.

## Kết nối Backend (API)

- Mặc định frontend gọi các endpoint dưới dạng `/api/*`
- Trong môi trường dev, Vite proxy sẽ forward `/api/*` sang `http://localhost:5001` (xem `vite.config.ts`)
- Nếu cần trỏ sang backend khác, bạn có thể set `VITE_API_URL` (ví dụ: `http://localhost:5001`)

## Google Login

Google OAuth2 được xử lý ở **backend** để giữ an toàn `client_secret`.

1) Tạo OAuth Client (Web) trong Google Cloud Console  
2) Tạo file `backend/.env`:

```env
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
# URL public của backend để match redirect URI đã khai báo ở Google Console
PUBLIC_BASE_URL=http://localhost:5001
# URL frontend để redirect về sau khi login
FRONTEND_URL=http://localhost:5173
# Secret để ký session cookie
SESSION_SECRET=change-me
```

Sau đó restart backend và reload frontend.

## Build

```bash
npm run build
```

## Cấu trúc

- **Entry points**
  - `src/main.tsx`: mount React app vào `#root`
  - `src/App.tsx`: giữ `currentSessionId` và bọc layout + routes

- **Routing**
  - `src/routes/AppRoutes.tsx`: routing tối thiểu (map path → page)

- **Pages**
  - `src/pages/Chat.tsx`: trang chat chính (load session, gửi message, refresh response)
  - `src/pages/Home.tsx`: trang Home (có link sang `/chat`)
  - `src/pages/NotFound.tsx`: trang 404 fallback

- **Components**
  - `src/components/layout/*`: layout components (`Header`, `Sidebar`, `MainLayout`)
  - `src/components/chat/*`: chat feature UI (`ChatMessage`, `MessageList`)

- **Services / Hooks / Types / Utils**
  - `src/services/api.ts`: gọi API (`/api/chat`, `/api/sessions`, ...)
  - (Các folder như `hooks/`, `types/`, `utils/`, `constants/` chỉ nên tạo khi thực sự dùng để tránh dead code)
  - `src/index.css`: Tailwind directives + global styles cơ bản

