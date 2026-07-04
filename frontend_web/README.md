# TestMate Frontend

Vue 3 + Vite + TypeScript + Tailwind + Element Plus + Monaco。

## 本地起

```bash
cd frontend_web
npm install
npm run dev    # http://localhost:5173
```

Vite dev server 自动 proxy `/api` → `http://localhost:8000`。

## Docker

```bash
docker build -t testmate-frontend .
docker run -p 8080:80 testmate-frontend
```
