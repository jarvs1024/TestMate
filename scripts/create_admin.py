#!/usr/bin/env python3
"""一行命令建 admin 账号,不用手 SQL。

用法:
    # 默认账号 admin + 默认密码(从 --password / --password-file / ADMIN_DEFAULT_PASSWORD env 读)
    python scripts/create_admin.py --password 'YourStrongP@ss'

    # 显式指定 MySQL 连接(从 docker 主机外跑这个脚本连 docker 暴露的端口时用)
    python scripts/create_admin.py \\
        --password 'xxx' \\
        --mysql-host 127.0.0.1 --mysql-port 3306 \\
        --mysql-user testmate --mysql-password 'mysql-pass' \\
        --mysql-database testmate

    # 密码从文件读(避免 shell history / ps 泄漏)
    python scripts/create_admin.py --password-file /run/secrets/admin-password

    # 改成 tester 角色
    python scripts/create_admin.py --password xxx --role tester --username li.wang

参数优先级(高到低):
    --password / --password-file   命令行
    ADMIN_DEFAULT_PASSWORD env     环境变量
    显式 --mysql-* 参数            覆盖 .env 加载值
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

# 让脚本能找到 backend_gateway.app.*
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend_gateway"))


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
        # 改用 os.environ[k] = v — 显式覆盖,跟命令行参数顺序一致
        # (旧版用 setdefault,会导致 env 变量优先于命令行,反直觉)
        os.environ[k] = v


def _resolve_password(args) -> str:
    """密码解析 — 三种来源,优先级: --password-file > --password > ADMIN_DEFAULT_PASSWORD env。"""
    if args.password_file:
        p = Path(args.password_file)
        if not p.exists():
            print(f"❌ 密码文件不存在: {p}", file=sys.stderr)
            sys.exit(2)
        return p.read_text(encoding="utf-8").rstrip("\n")
    if args.password:
        return args.password
    env_pw = os.environ.get("ADMIN_DEFAULT_PASSWORD")
    if env_pw:
        return env_pw
    print("❌ 必须传 --password / --password-file 或设置 ADMIN_DEFAULT_PASSWORD 环境变量", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="TestMate admin 账号创建脚本")
    parser.add_argument("--username", default="admin", help="用户名(默认 admin)")
    parser.add_argument("--password", default=None, help="明文密码")
    parser.add_argument(
        "--password-file",
        default=None,
        help="密码文件路径(推荐,避免 ps / history 泄漏)",
    )
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
    # 显式 MySQL 参数 — 覆盖 .env 里的值
    parser.add_argument("--mysql-host", default=None)
    parser.add_argument("--mysql-port", type=int, default=None)
    parser.add_argument("--mysql-user", default=None)
    parser.add_argument("--mysql-password", default=None)
    parser.add_argument("--mysql-database", default=None)
    args = parser.parse_args()

    # 加载 env
    if args.env_file:
        _load_env_file(Path(args.env_file))
    else:
        for candidate in [ROOT / ".env.local", ROOT / "backend_gateway" / ".env.example"]:
            _load_env_file(candidate)

    # 命令行 --mysql-* 优先级最高
    if args.mysql_host:
        os.environ["MYSQL_HOST"] = args.mysql_host
    if args.mysql_port:
        os.environ["MYSQL_PORT"] = str(args.mysql_port)
    if args.mysql_user:
        os.environ["MYSQL_USER"] = args.mysql_user
    if args.mysql_password:
        os.environ["MYSQL_PASSWORD"] = args.mysql_password
    if args.mysql_database:
        os.environ["MYSQL_DATABASE"] = args.mysql_database

    password = _resolve_password(args)

    # 延迟 import,确保 sys.path 和环境变量都准备好
    from sqlalchemy import select
    from app.core.security import hash_password
    from app.db.session import AsyncSessionLocal, init_db
    from app.models.user import User, UserRole

    async def run() -> int:
        # 先确保表存在(走 alembic)
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
    print(f"   密码: {password if args.password else '(从文件/env 读)'}")
    print(f"   角色: {args.role}")
    print()
    print("⚠️  生产部署请立即改默认密码,设置 ADMIN_DEFAULT_PASSWORD 环境变量覆盖")
    return rc


if __name__ == "__main__":
    sys.exit(main())
