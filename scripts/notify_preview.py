#!/usr/bin/env python3
"""钉钉通知消息的**干跑预览** (2026-10-30 · 第十一轮 · 问题4).

用户要求: "完成钉钉推送的通知信息, 上架补充发描述 比如是干嘛的, 发布更新, 补充更新了啥等,
信息要区分是插件技能还是连接还是软件包, 最后附上连接……消息简洁明了, 好看".

⚠️ **绝对不发** —— 这个脚本只调 `dingtalk.preview_market_message` (纯拼字符串),
   一行网络请求都不发. 线上真发要走 `notify_market`.

用法:
    cd backend_gateway
    set -a && source ../deploy/native/runtime/config/backend.env && set +a
    ../deploy/native/runtime/venv/bin/python3 ../scripts/notify_preview.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend_gateway"))

from app.core.dingtalk import preview_market_message  # noqa: E402


SCENES = [
    {
        "event": "publish",
        "title": "市场 · 上架新资产 (插件)",
        "kw": dict(
            name="代码检视流水线", version="1.0.0", actor="zhangsan",
            kind="plugin", category="流程规范", code="dml-code-review",
            summary="一键串联: 取 MR diff → 送检视 → 回写评论 → 汇总结果",
        ),
    },
    {
        "event": "update",
        "title": "市场 · 发布新版本 (连接器)",
        "kw": dict(
            name="GitLab 连接器", version="0.2.0", actor="zhangsan",
            kind="mcp", category="管协同", code="dml-gitlab",
            summary="支持只读访问项目与 MR, 鉴权走个人令牌",
        ),
    },
    {
        "event": "software_publish",
        "title": "软件库 · 上架新软件",
        "kw": dict(
            name="E2E 演示软件", version="1.0.0", actor="zhangsan",
            kind="software", category="工具", code="e2e-demo",
            summary="e2e 走通用的演示软件",
        ),
    },
    {
        "event": "software_update",
        "title": "软件库 · 发布新版本",
        "kw": dict(
            name="E2E 演示软件", version="1.0.3", actor="zhangsan",
            kind="software", category="工具", code="e2e-demo",
            summary="e2e 走通用的演示软件",
            release_notes="修了日志解析在超长行上的截断问题, 另外补了个 --json 输出",
        ),
    },
    {
        "event": "review",
        "title": "市场 · 上架待审核 (审核群)",
        "kw": dict(
            name="SSD 日志医生", version="1.0.0", actor="lisi",
            kind="skill", category="兜住质量", code="dml-ssd-doctor",
            summary="读取 NVMe SMART 日志, 自动定位失败扇区",
        ),
    },
    {
        # ⚠️ 2026-10-30 (第十二轮): 「只改了信息」的待审通知 ——
        #    跟「新资产待审核」长得不一样 (标题 + 说的是"改了信息"), 管理员才分得出.
        #    ⚠️ 这条**只发审核群**, 审核通过后**不通知市场群** (包没变).
        "event": "review",
        "title": "审核群 · 只改了信息, 待审核 (包没变)",
        "kw": dict(
            name="代码检视流水线", version="1.2.0", actor="zhangsan",
            kind="plugin", category="流程规范", code="dml-code-review",
            summary="一键串联: 取 MR diff → 送检视 → 回写评论 → 汇总结果",
            detail="修改了资产信息, 等管理员审核",
            title_override="📝 资产信息修改, 待审核",
        ),
    },
]


async def main() -> int:
    try:
        for sc in SCENES:
            r = await preview_market_message(sc["event"], **sc["kw"])
            print("=" * 68)
            print(f"【{sc['title']}】  event={r['event']}")
            print("-" * 68)
            print(r["text"])
            print()
        print("=" * 68)
        print("⚠️ 以上全部是**干跑渲染**的结果 —— 没有发出任何请求.")
        return 0
    finally:
        # ⚠️ 断开连接池 —— 否则退出时 aiomysql 的连接回收会打一堆
        #    "Event loop is closed" 的栈 (那个 event loop 已经关了).
        from app.db.session import engine
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
