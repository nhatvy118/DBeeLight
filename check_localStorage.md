# Check localStorage trong Browser Console

## 1. Xem tất cả projects:
```javascript
console.log('Projects:', JSON.parse(localStorage.getItem('projects') || '[]'));
```

## 2. Xem projectSessions:
```javascript
console.log('Project Sessions:', JSON.parse(localStorage.getItem('projectSessions') || '{}'));
```

## 3. Xem selected project:
```javascript
console.log('Selected Project ID:', localStorage.getItem('selectedProjectId'));
```

## 4. Clear tất cả để test lại:
```javascript
localStorage.clear();
location.reload();
```
