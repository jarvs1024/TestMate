#!/usr/bin/env python3
"""一行命令建 admin 账号,不用手 SQL。

用法:
    # 默认账号 admin / 默认密码(从 .env 的 ADMIN_DEFAULT_PASSWORD 读,缺省 TestMate@2026)
    python scripts/create_admin.py

    # 自定义账号
    python scripts/create_admin.py --username admin --password 'YourStrongP@ss'

    # 改成 tester 角色
    python scripts/create_admin.py --username li.wang --password xxx --role tester

依赖环境变量(同 backend_gateway 一致):
    MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE
    docker 部署默认 host=mysql,本地直跑请先 export 或用 .env.local
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

# 让脚本能找到 backend_gateway.app.*
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend_gateway"))

# 默认密码(只在用户没传 --password 时使用,生产请覆盖)
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD", "TestMate@2026")

# 关键:从环境覆盖 DB 配置(便于在 docker 主机外跑这个脚本连 docker 暴露的端口)
# 顺序: 显式环境变量 > .env.local > .env.example 默认


def _load_env_file(path: Path) -> None:
    """轻量 .env 加载,不依赖 pydantic-settings。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def main() -> int:
    parser = argparse.ArgumentParser(description="TestMate admin 账号创建脚本")
    parser.add_argument("--username", default="admin", help="用户名(默认 admin)")
    parser.add_argument("--password", default=None, help="明文密码(默认读 ADMIN_DEFAULT_PASSWORD 或 TestMate@2026)")
    parser.add_argument(
        "--role",
        default="admin",
        choices=["admin", "tester", "viewer"],
        help="角色(默认 admin)",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="指定 .env 文件路径(默认依次尝试 .env.local / .env.example)",
    )
    args = parser.parse_args()

    # 加载 env
    if args.env_file:
        _load_env_file(Path(args.env_file))
    else:
        for candidate in [ROOT / ".env.local", ROOT / "backend_gateway" / ".env.example"]:
            _load_env_file(candidate)

    # 延迟 import,确保 sys.path 和环境变量都准备好
    from sqlalchemy import select
    from app.core.security import hash_password
    from app.db.session import AsyncSessionLocal, init_db
    from app.models.user import User, UserRole

    password = args.password or DEFAULT_ADMIN_PASSWORD

    async def run() -> int:
        # 先确保表存在
        await init_db()
        async with AsyncSessionLocal() as session:
            # 查重
            result = await session.execute(select(User).where(User.username == args.username))
            existing = result.scalar_one_or_none()
            if existing:
                # 更新密码 + 角色
                existing.password_hash = hash_password(password)
                existing.role = UserRole(args.role)
                await session.commit()
                print(f"✅ 已更新用户: {args.username} (role={args.role})")
                return 0

            user = User(
                username=args.username,
                password_hash=hash_password(password),
                role=UserRole(args.role),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print(f"✅ 已创建用户: {user.username} (id={user.id}, role={user.role.value})")
            return 0

    rc = asyncio.run(run())
    print()
    print(f"   账号: {args.username}")
    print(f"   密码: {password}")
    print(f"   角色: {args.role}")
    print()
    print("⚠️  生产部署请立即改默认密码,设置 ADMIN_DEFAULT_PASSWORD 环境变量覆盖")
    return rc


if __name__ == "__main__":
    sys.exit(main())
