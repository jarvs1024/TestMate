# 资产市场后端测试

## 跑起来

```bash
cd backend_gateway
pip install -r requirements-dev.txt          # pytest / pytest-asyncio / ruff
python -m pytest tests/ -v
```

## 前置：测试库

单测跑在**独立的测试库** `testmate_test` 上，绝不碰生产库。
第一次跑之前建一次库并授权（一次就够）：

```bash
# 从 deploy/.env 取 MYSQL_ROOT_PASSWORD
docker exec test-mate-mysql-1 mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "
  CREATE DATABASE IF NOT EXISTS testmate_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  GRANT ALL PRIVILEGES ON testmate_test.* TO 'testmate'@'%';
  FLUSH PRIVILEGES;"
```

在容器里跑（推荐，依赖齐全）：

```bash
docker cp backend_gateway/tests/. test-mate-backend-1:/app/tests/
docker cp backend_gateway/pyproject.toml test-mate-backend-1:/app/pyproject.toml
docker exec -w /app test-mate-backend-1 python -m pytest tests/ -v
```

## 隔离措施

| 隔离项 | 做法 |
|---|---|
| 数据库 | `MYSQL_DATABASE=testmate_test`，每个用例前后清表 |
| git 工作区 | 每个用例一个临时目录 + 一个**本地裸库**当远端（真跑 commit/push，不连真 GitLab） |
| 远端地址 | `MARKET_GIT_REMOTE` 指向 127.0.0.1:1（一定连不上），不会误推真仓库 |
| 后台任务 | 用 `ASGITransport` 不跑 lifespan → worker/拉取器都不启动 |
| 事件循环 | 全部用例共用一个 loop（SQLAlchemy 连接池绑在 loop 上） |

⚠️ `MARKET_WORKSPACE` 必须**强制**覆盖成临时目录：容器里它指向真实的
`/workspace`（市场 git 仓库），用 `setdefault` 会保留它 —— 测试就会往真实仓库里写文件。

## 覆盖范围

| 文件 | 覆盖 |
|---|---|
| `test_pkg.py` | 解包安全：zip-slip / 绝对路径 / 符号链接 / 敏感路径 / 体积与数量预算 / 确定性打包 / frontmatter |
| `test_market_catalog.py` | 文件校验、code/版本校验、索引条目与 publish_status 往返 |
| `test_dingtalk.py` | 加签算法（与官方实现交叉验证）、关键词前置、回执落库、失败重试与退避 |
| `test_git_sync.py` | semver 比较、错误分类、提交推送、**推送失败后重试**、origin 地址同步 |
| `test_qoder_marketplace.py` | marketplace.json 结构、只收 published 的 plugin、sha256 与实际字节一致 |
| `test_market_api.py` | 上传落库、审核状态机、可见性、权限边界、包预检、安装/卸载、上下架、删除、审计、状态统计 |
| `test_availability.py` | 并发上传/安装、崩溃恢复、依赖不可用时的降级、通知失败不影响主流程 |
