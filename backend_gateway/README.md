# TestMate Backend Gateway

FastAPI 中台,完全包裹 Dify / RAGFlow / 钉钉 / GitLab / 机台。

## 本地起

```bash
cd backend_gateway
cp .env.example .env
# 改 .env 里的 MYSQL / REDIS / DIFY 配置
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## API 文档

启动后访问 http://localhost:8000/docs

## Docker

```bash
docker build -t testmate-backend .
docker run -p 8000:8000 --env-file .env testmate-backend
```
