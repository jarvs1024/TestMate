#!/usr/bin/env python3
"""AI 资产市场 — 种子数据灌入脚本.

把团队基线的 13 条资产通过**真实上传接口**写入 (而不是直接改库/改 git),
这样能顺带验证: 落盘 → index.json → git commit → push 的完整链路.
脚本是幂等的: 已存在的 code 会走更新接口.

每个资产都会带上**真实可安装的包** (技能 SKILL.md / 插件 .qoder-plugin/plugin.json /
连接器 .mcp.json) —— 只有元数据的资产装不上, 市场的旗舰位不能是摆设.

用法:
    python3 scripts/seed_market.py [--base http://localhost:18000] \
        [--user admin] [--password 'Admin@123']

⚠️ 需要发布者权限 (admin 恒可发布, 其他用户要在 marketplace.publisher_ids 里).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid


def _req(url: str, data: dict | None = None, headers: dict | None = None,
         method: str = "GET", raw: bytes | None = None,
         content_type: str | None = None) -> tuple[int, dict | str]:
    hdrs = {"Accept": "application/json", **(headers or {})}
    body = None
    if raw is not None:
        body = raw
        if content_type:
            hdrs["Content-Type"] = content_type
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(txt)
            except json.JSONDecodeError:
                return r.status, txt
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt)
        except json.JSONDecodeError:
            return e.code, txt


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """fields: 普通表单字段; files: {相对路径: 内容} → 统一以 files 字段名提交."""
    b = "----tms" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
    for name, content in files.items():
        out.append(
            f"--{b}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{name}\"\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n{content}\r\n"
        )
    out.append(f"--{b}--\r\n")
    return "".join(out).encode("utf-8"), f"multipart/form-data; boundary={b}"


# ============ 真实可安装的包内容 ============

def _package_files(a: dict) -> dict[tuple[str, str], str]:
    """为每个资产生成**真实可安装**的文件内容.

    之前种子只传元数据、不带文件, 后端只能从 description 合成一个 README.md ——
    结果是: 技能的 SKILL.md 缺失 (文档接口 404)、插件的 .qoder-plugin/plugin.json 缺失
    (安装直接失败)。市场里的旗舰资产不能只是摆设, 所以这里按 kind 生成合规包:
      skill  → SKILL.md (带 frontmatter)
      plugin → README.md + .qoder-plugin/plugin.json
      mcp    → README.md + .mcp.json
    """
    code, kind, name = a["code"], a["kind"], a["name"]
    ver = a["version"].lstrip("v")
    summary = a["summary"]
    body = "\n".join([
        f"# {name}",
        "",
        a["description"],
        "",
        "## 适用场景",
        a["use_when"],
        "",
        "## 不适用",
        a["not_for"],
        "",
        "## 安装步骤",
        *[f"{i + 1}. {s}" for i, s in enumerate(a["install_steps"])],
        "",
    ])
    out: dict[str, str] = {}
    if kind == "skill":
        skill = "\n".join([
            "---",
            f"name: {code}",
            f"description: {summary}",
            "---",
            "",
            body,
        ])
        out["SKILL.md"] = skill
    elif kind == "plugin":
        plugin_json = json.dumps({
            "name": code,
            "displayName": name,
            "version": ver,
            "description": summary,
            "descriptionZh": summary,
            "author": {"name": "SSD 测试组"},
        }, ensure_ascii=False, indent=2)
        out["README.md"] = body
        out[".qoder-plugin/plugin.json"] = plugin_json
    else:  # mcp
        url = ""
        for s in a["install_steps"]:
            if "http" in s:
                url = s.split("http", 1)[1].split()[0].strip().rstrip("，,")
                url = "http" + url
                break
        out["README.md"] = body
        out[".mcp.json"] = json.dumps({
            "mcpServers": {code: ({"url": url} if url else {"command": "npx", "args": ["-y", code]})}
        }, ensure_ascii=False, indent=2)
    return out


# ============ 基线资产目录 (团队真实业务域) ============

ASSETS: list[dict] = [
    # ---------------- 技能 ----------------
    {
        "code": "ssd-log-cheatsheet", "kind": "skill", "name": "SSD 日志速查手册",
        "icon": "📜", "version": "v1.4.0", "category": "知识资产",
        "summary": "dmesg / FW log 常见报错码与定位路径速查, 贴日志即可判断问题域",
        "description": "沉淀了 SSD 测试中最常见的 40+ 条日志特征, 覆盖 I/O timeout、assert、"
                       "SMART 告警、thermal throttle 等。\n\n"
                       "给模型一份「看到这个关键字 → 先查什么 → 怎么排除」的决策树, 比让它自由发挥稳定得多。",
        "use_when": "拿到一段 dmesg / syslog / FW log, 需要快速判断问题域和下一步排查方向",
        "not_for": "需要逐行精确解析完整 trace, 请用 Trace 诊断类连接器",
        "tags": ["日志", "诊断", "速查"], "featured": True, "install_count": 128,
        "permissions": {}, "install_steps": ["将 ssd-log-cheatsheet/ 复制到宿主的 skills 目录", "重启 Agent 会话"],
    },
    {
        "code": "nvme-spec-cheatsheet", "kind": "skill", "name": "NVMe Spec 速查",
        "icon": "📕", "version": "v2.1.0", "category": "知识资产",
        "summary": "NVMe 1.4 / JEDEC 关键命令、字段与状态码速查, 答题带出处",
        "description": "把 NVMe 1.4 与 JEDEC 相关章节压缩成按命令组织的速查表, 每条都标注 spec 章节号。\n\n"
                       "模型回答协议问题时可以引用章节号, 避免凭空编造字段含义。",
        "use_when": "需要确认某个 NVMe 命令 / 字段 / 状态码的准确语义, 或写涉及协议的自动化脚本",
        "not_for": "完整的协议全文检索请用知识库连接器, 本技能只做速查",
        "tags": ["NVMe", "Spec", "协议"], "featured": True, "install_count": 96,
        "permissions": {}, "install_steps": ["将 nvme-spec-cheatsheet/ 复制到宿主的 skills 目录", "重启 Agent 会话"],
    },
    {
        "code": "burn-result-reader", "kind": "skill", "name": "老化结果解读",
        "icon": "🔥", "version": "v1.0.2", "category": "任务调度",
        "summary": "长时老化 / burn-in 数据解读: 判断失败模式, 区分真失效与环境噪声",
        "description": "老化跑完拿到一份数据后, 用它判断是真实器件失效、温箱波动、还是接触不良导致的假失效。\n\n"
                       "内置 SSD 测试组的经验判据, 避免把环境问题误报成器件问题。",
        "use_when": "老化任务结束后拿到结果, 需要判断是否需要复测或报废",
        "not_for": "老化任务的派发与调度, 请用 TestMate 机台运维连接器",
        "tags": ["老化", "数据解读"], "install_count": 54,
        "permissions": {}, "install_steps": ["将 burn-result-reader/ 复制到宿主的 skills 目录", "重启 Agent 会话"],
    },
    {
        "code": "testcase-template-gen", "kind": "skill", "name": "用例模板生成",
        "icon": "🧪", "version": "v0.9.0", "category": "方案用例",
        "summary": "按团队 pytest 规范生成用例骨架, 自动带 ssd_tool 导入与断言模板",
        "description": "内置团队自动化用例的代码规范: 目录结构、`import ssd_tool` 约定、fixture 写法、断言风格。\n\n"
                       "生成的骨架能直接跑, 不需要再手工改格式。",
        "use_when": "拿到测试方案, 需要快速展开成符合团队规范的 pytest 用例骨架",
        "not_for": "用例逻辑本身的正确性需要人工评审",
        "tags": ["用例", "pytest", "模板"], "install_count": 71,
        "permissions": {}, "install_steps": ["将 testcase-template-gen/ 复制到宿主的 skills 目录", "重启 Agent 会话"],
    },
    {
        "code": "test-plan-assistant", "kind": "skill", "name": "测试方案助手",
        "icon": "📝", "version": "v0.8.1", "category": "方案用例",
        "summary": "给 Spec / 工况描述, 出一版测试方案骨架: 覆盖点、步骤、风险项",
        "description": "把一段模糊的需求描述展开成可评审的测试方案骨架, 强制产出覆盖矩阵和风险清单。",
        "use_when": "客户新功能上线前需要快速出一版测试方案初稿",
        "not_for": "已有成熟方案的直接复用, 不需要生成本技能",
        "tags": ["测试方案", "Spec"], "install_count": 43,
        "permissions": {}, "install_steps": ["将 test-plan-assistant/ 复制到宿主的 skills 目录", "重启 Agent 会话"],
    },
    # ---------------- 连接器 ----------------
    {
        "code": "review-agent-board", "kind": "mcp", "name": "ReviewAgent 评审看板",
        "icon": "🧬", "version": "v0.2.0", "category": "流程管控",
        "summary": "代码检视数据看板: MR 生命周期、建议采纳率、规则命中与作者分布",
        "description": "连接 ReviewAgent 的 telemetry API, 提供 MR / 建议 / 规则三个维度的聚合数据。",
        "use_when": "想看团队代码检视的整体采纳情况, 或排查某个 MR 的评审历史",
        "not_for": "需要写回 GitLab 的操作 (adopt / dismiss), 请直接用 GitLab",
        "tags": ["代码", "检视", "看板"], "featured": True, "install_count": 38,
        "permissions": {"network": ["host.docker.internal:3000"]},
        "install_steps": ["在宿主 MCP 配置中新增 server: review-agent-board", "url 填 http://host.docker.internal:3000/mcp", "重启 Agent 会话"],
    },
    {
        "code": "pr-agent-review", "kind": "mcp", "name": "pr-agent 代码检视",
        "icon": "🔍", "version": "v1.6.2", "category": "流程管控",
        "summary": "pr-agent 检视数据查询, 与 ReviewAgent 数据可比",
        "description": "提供 pr-agent 侧的 runs / suggestions / stats 查询, 历史上用于与 ReviewAgent 做数据对照。",
        "use_when": "需要与 ReviewAgent 做数据比对, 或排查历史检视记录",
        "not_for": "主用看板请看 ReviewAgent 评审看板",
        "tags": ["代码", "检视"], "install_count": 22,
        "permissions": {"network": ["host.docker.internal:5050"]},
        "install_steps": ["在宿主 MCP 配置中新增 server: pr-agent-review", "url 填 http://host.docker.internal:5050/mcp"],
    },
    {
        "code": "testmate-machine-ops", "kind": "mcp", "name": "TestMate 机台运维",
        "icon": "🛠", "version": "v0.3.0", "category": "环境运维",
        "summary": "查询测试机状态 / 温箱与通道占用 / 触发常用运维动作",
        "description": "经 TestMate 网关访问机台字典与 SSH 通道, 提供机台状态查询与受限的运维动作。",
        "use_when": "测试过程中要快速查机台状态、看通道占用、拉日志或复位",
        "not_for": "长时老化任务的派发, 不在本连接器职责内",
        "tags": ["机台", "运维"], "featured": True, "install_count": 61,
        "permissions": {"network": ["testmate.internal:8000"], "process_exec": ["ssh"]},
        "install_steps": ["在宿主 MCP 配置中新增 server: testmate-machine-ops", "url 填 TestMate 网关 /api/v1/machines"],
    },
    {
        "code": "kb-search", "kind": "mcp", "name": "知识库检索",
        "icon": "📚", "version": "v0.5.0", "category": "知识资产",
        "summary": "检索团队私有知识源 (RAGFlow), 返回带出处引用的片段",
        "description": "所有智能体共享的私有知识源检索入口, 结果带章节级出处。",
        "use_when": "需要从团队沉淀的文档 / spec / 历史报告里找依据",
        "not_for": "实时数据查询, 本连接器只检索非结构化文档",
        "tags": ["知识库", "检索"], "install_count": 87,
        "permissions": {"network": ["ragflow.internal:9380"]},
        "install_steps": ["在宿主 MCP 配置中新增 server: kb-search", "url 填 RAGFlow /api/v1"],
    },
    {
        "code": "dingtalk-notify", "kind": "mcp", "name": "钉钉通知推送",
        "icon": "📮", "version": "v0.4.2", "category": "环境运维",
        "summary": "向指定钉钉群推送 Markdown 卡片, 支持加签",
        "description": "经 TestMate 网关转发钉钉机器人 webhook, 统一管理加签与重试。",
        "use_when": "需要把测试结果 / 告警推送到团队群",
        "not_for": "面向外部客户的通知, 需走单独审批",
        "tags": ["钉钉", "通知"], "install_count": 45,
        "permissions": {"network": ["oapi.dingtalk.com:443"], "secrets": ["DINGTALK_SECRET"]},
        "install_steps": ["在宿主 MCP 配置中新增 server: dingtalk-notify", "url 填 TestMate 网关 /api/v1/notify"],
    },
    # ---------------- 插件 ----------------
    {
        "code": "code-review-pipeline", "kind": "plugin", "name": "代码检视流水线",
        "icon": "⚙️", "version": "v1.2.0", "category": "任务调度",
        "summary": "一键串联: 取 MR diff → 送检视 → 回写评论 → 汇总结果",
        "description": "把 ReviewAgent 调用、结果回写与汇总打包成一个插件, 适合 CI 流水线与批量检视场景。\n\n"
                       "插件包内含一个 MCP server, 安装前请确认权限声明。",
        "use_when": "需要在 CI 或批量流程里自动跑一轮代码检视",
        "not_for": "只想查看看板数据, 用 ReviewAgent 评审看板连接器即可",
        "tags": ["流水线", "检视", "CI"], "featured": True, "install_count": 29,
        "permissions": {
            "filesystem_write": ["~/lab/review-reports/**"],
            "network": ["git.internal:443", "host.docker.internal:3000"],
            "process_exec": ["git"],
            "secrets": ["GITLAB_TOKEN"],
        },
        "install_steps": ["导入插件包 code-review-pipeline", "在设置中填入 GITLAB_TOKEN (仅存本地)", "确认权限声明后启用流水线"],
    },
    {
        "code": "weekly-report-assistant", "kind": "plugin", "name": "周报助手",
        "icon": "📊", "version": "v0.3.1", "category": "流程管控",
        "summary": "汇总本周检视 / 老化 / 用例数据, 生成周报并推送钉钉群",
        "description": "采集三类数据源, 生成带 AI 综述的周报, 推送到团队群。\n\n"
                       "推送默认走 dry-run, 需显式开启真实推送。",
        "use_when": "每周固定产出团队 AI 效能周报",
        "not_for": "即时数据查询, 本插件面向周期性汇总",
        "tags": ["周报", "汇总"], "install_count": 34,
        "permissions": {"network": ["oapi.dingtalk.com:443"], "secrets": ["DINGTALK_SECRET"]},
        "install_steps": ["导入插件包 weekly-report-assistant", "配置数据源地址与钉钉 webhook"],
    },
    {
        "code": "test-report-gen", "kind": "plugin", "name": "测试报告生成",
        "icon": "📑", "version": "v1.0.0", "category": "流程管控",
        "summary": "把测试数据 + 结论整理成可交付的报告 (含图表与结论页)",
        "description": "读取测试结果, 输出统一模板的测试报告, 支持导出 PDF / xlsx。",
        "use_when": "一轮测试结束后要产出交付给客户或上级的报告",
        "not_for": "原始数据分析请用对应领域的连接器",
        "tags": ["报告", "交付"], "install_count": 26,
        "permissions": {
            "filesystem_read": ["~/lab/results/**"],
            "filesystem_write": ["~/lab/reports/**"],
        },
        "install_steps": ["导入插件包 test-report-gen", "确认结果目录路径"],
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:18000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    ap.add_argument("--wait", type=int, default=90, help="等待推送完成的秒数")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    st, data = _req(f"{base}/api/v1/auth/login",
                     {"username": args.user, "password": args.password}, method="POST")
    if st != 200 or not isinstance(data, dict) or "access_token" not in data:
        print(f"❌ 登录失败 ({st}): {data}")
        return 1
    token = data["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    print(f"✅ 已登录 {args.user}")

    job_ids: list[int] = []
    # 先取已有资产 —— 直接走对的动作 (新建/更新), 避免"先创建撞 409"把工作区写脏
    st, existing = _req(f"{base}/api/v1/assets?limit=200", headers=H)
    known: set[str] = set()
    if isinstance(existing, dict):
        known = {i.get("code") for i in existing.get("items", []) if i.get("code")}
    print(f"已存在资产 {len(known)} 条, 将按需走更新")

    for a in ASSETS:
        fields = {
            "code": a["code"], "kind": a["kind"], "name": a["name"],
            "version": a["version"], "summary": a["summary"],
            "description": a["description"], "use_when": a["use_when"],
            "not_for": a["not_for"], "category": a["category"], "icon": a["icon"],
            "tags": json.dumps(a.get("tags", []), ensure_ascii=False),
            "keywords": "[]",
            "featured": "true" if a.get("featured") else "false",
            "permissions": json.dumps(a.get("permissions", {}), ensure_ascii=False),
            "install_steps": json.dumps(a.get("install_steps", []), ensure_ascii=False),
            "bindings": "{}",
        }
        pkg_files = _package_files(a)
        if a["code"] in known:
            raw, ct = _multipart({k: v for k, v in fields.items() if k != "code"}, pkg_files)
            st, data = _req(f"{base}/api/v1/assets/{a['code']}", raw=raw,
                            headers=H, method="PUT", content_type=ct)
        else:
            raw, ct = _multipart(fields, pkg_files)
            st, data = _req(f"{base}/api/v1/assets/upload", raw=raw,
                            headers=H, method="POST", content_type=ct)
        if st not in (200, 202):
            print(f"❌ {a['code']}: HTTP {st} {str(data)[:200]}")
            continue
        if isinstance(data, dict):
            job_ids.append(data["id"])
            print(f"  ✓ {a['code']:<26} job={data['id']} status={data.get('status')} files={len(pkg_files)}")

    print(f"\n⏳ 等待 {len(job_ids)} 个任务同步到 GitLab …")
    deadline = time.time() + args.wait
    pending = set(job_ids)
    while pending and time.time() < deadline:
        time.sleep(2)
        for jid in list(pending):
            st, d = _req(f"{base}/api/v1/assets/jobs/{jid}", headers=H)
            if not isinstance(d, dict):
                continue
            if d.get("status") == "pushed":
                pending.discard(jid)
                print(f"  ✓ job {jid} → pushed  {d.get('commit_sha', '')[:10]}")
            elif d.get("status") == "failed":
                pending.discard(jid)
                print(f"  ✗ job {jid} → failed: {d.get('error', '')[:200]}")
    if pending:
        print(f"  ⏳ 仍有 {len(pending)} 个任务未完成: {sorted(pending)}")

    st, d = _req(f"{base}/api/v1/assets?limit=100", headers=H)
    if isinstance(d, dict):
        print(f"\n📦 资产总数: {d.get('total')}")
        for it in d.get("items", []):
            print(f"   {it['kind']:<7} {it['code']:<26} {it['sync_status']:<8} {it['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
