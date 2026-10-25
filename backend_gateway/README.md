# TestMate Backend Gateway

FastAPI 中台,完全包裹 RAGFlow / ReviewAgent / 钉钉 / GitLab / 机台。

## 本地起

⚠️ **不要用 `backend_gateway/.env.example` 直跑** —— 里面的 `MYSQL_HOST=mysql` /
`REDIS_HOST=redis` 是 docker 里的 service 名,在 Mac 上直跑解析不了。
本地直跑的配置在**仓库根**的 `.env.example.local`(`MYSQL_HOST=127.0.0.1`)。

```bash
cd backend_gateway

# 1) 仓库根准备本地直跑配置
cp ../.env.example.local ../.env.local

# 2) ⚠️ config.py 的 env_file=".env" 是**相对 CWD** 的:
#    后端从 backend_gateway/ 启动,读到的就是 backend_gateway/.env,
#    不是仓库根的 .env.local —— 所以要把它拷到位
cp ../.env.local .env

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

> 一键起(等价流程 + 自动起 MySQL/Redis 容器):
> `./scripts/start.sh --local`(后端用 `source ../.env.local` 注入环境变量)。

## API 文档

启动后访问 http://localhost:8000/docs

## Docker

```bash
docker build -t testmate-backend .
docker run -p 8000:8000 --env-file .env.docker testmate-backend
```

> `--env-file` 要用 **docker 服务名** 那份(仓库根 `.env.example.docker` → `.env.docker`),
> 不是本地直跑那份 `.env`(`MYSQL_HOST=127.0.0.1` 在容器里指容器自己)。
