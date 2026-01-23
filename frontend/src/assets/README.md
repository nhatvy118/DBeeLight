# Assets Folder

Thư mục này chứa các file assets (icons, images, fonts, etc.) cho frontend.

## Cấu trúc:

- `icons/` - Các file icon (SVG, PNG, etc.)
- `images/` - Các hình ảnh khác (logos, banners, etc.)

## Cách sử dụng:

### Import icon trong component:

```tsx
import iconName from '../assets/icons/icon-name.svg';

// Sử dụng trong JSX
<img src={iconName} alt="Icon" />
```

### Hoặc import từ public folder (không cần import):

```tsx
// File trong public/icons/icon-name.svg
<img src="/icons/icon-name.svg" alt="Icon" />
```

## Lưu ý:

- Vite sẽ tự động optimize các assets trong `src/assets/`
- Files trong `public/` được copy nguyên vẹn vào `dist/` khi build
- Nên dùng `src/assets/` cho các assets cần import và optimize

