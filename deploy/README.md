# TestMate 一键部署

```bash
cd deploy
cp .env.example .env
$EDITOR .env                    # 填 DB 密码 / JWT secret / Dify / RAGFlow
docker compose up -d
```

启动后:

- 前端:http://localhost:8080
- 后端 API:http://localhost:8000
- API 文档:http://localhost:8000/docs
- MySQL:localhost:3306
- Redis:localhost:6379

## 首次创建 admin 用户

P0 简化:首次启动后,直接进 MySQL 创建 admin:

```bash
docker compose exec mysql mysql -uroot -p$MYSQL_ROOT_PASSWORD testmate

# 密码 hash 用 bcrypt(后端 login 用的格式),先用 Python 生成:
# python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('admin123'))"
# 复制输出的 hash 替换下面的 $HASH

INSERT INTO users (username, password_hash, role, created_at, updated_at)
VALUES ('admin', '$HASH', 'admin', NOW(), NOW());
```

## 数据卷

- `mysql_data` — MySQL
- `redis_data` — Redis

## 备份

```bash
docker compose exec mysql mysqldump -uroot -p$MYSQL_ROOT_PASSWORD testmate > backup-$(date +%F).sql
```
