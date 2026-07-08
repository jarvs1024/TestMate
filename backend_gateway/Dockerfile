# TestMate Backend Dockerfile
# 多阶段 build: builder 阶段装 gcc/libffi-dev 编译依赖,runtime 阶段只保留运行需要的 curl。
# 镜像体积: 单阶段 ~430MB -> 多阶段 ~200MB
#
# 离线场景(如 86 完全断网)备选:
#   没有 python:3.11-slim 镜像 + 没有公网时,可以暂时改用主机直跑:
#     pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0
#   或者参照 deploy/deploy.sh 走完整 offline-save 流程先把 base 镜像弄到内网。
#   不要随便换 base(ubuntu/squid 等) — 它们的 apt repo 走公网,断网下走不通。

# ===== Stage 1: builder =====
FROM python:3.11-slim AS builder

WORKDIR /app

# 编译依赖: gcc/libffi-dev/libssl-dev 装 wheel 包(cryptography / bcrypt 等)
# --no-install-recommends 避免拉不需要的推荐包
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# 先 COPY requirements 利用层缓存:依赖不变就不重装
COPY requirements.txt .

# pip install --user 把包装到 /root/.local,runtime 阶段从这里 COPY 过去
# --no-cache-dir 不缓存 pip 下载的 wheel
RUN pip install --no-cache-dir --user -r requirements.txt

# ===== Stage 2: runtime =====
FROM python:3.11-slim

WORKDIR /app

# runtime 只需要 curl(给 HEALTHCHECK 用)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制装好的包
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8000

# 健康检查 — 探 /health/ready(任何依赖不通返 503)
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health/ready || exit 1

# 启动 uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
