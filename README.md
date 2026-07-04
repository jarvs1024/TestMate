# TestMate 智能测试辅助平台

> SSD 测试组的内网 AI 工作平台,基于 Vue 3 + FastAPI + Dify + RAGFlow。

## 项目状态

- 当前阶段:**方案设计**(P0 尚未启动)
- 仓库:`github.com/jarvs1024/TestMate`
- 详细方案:`docs/superpowers/specs/2026-07-04-testmate-design.md`
- 汇报版:`docs/superpowers/specs/2026-07-04-testmate-brief.md`

## 一句话

前店后厂:Vue 3 结构化卡片前端 + FastAPI 中台(完全包裹 AI 引擎 + 触达硬件)+ Dify agent 编排 + RAGFlow 知识库,部署在内网,服务 SSD 测试组日常工作。

## 核心特性

- **协议检索**:NVMe / JEDEC 等规范 PDF 切片 + 高亮问答
- **log 诊断**:上传 PCIe / 串口 log,AI 提取 assert,对比历史缺陷图谱
- **用例生成**:输入需求,自动生成符合 `import ssd_tool` 规范的 pytest 脚本
- **机台三道闸**:互斥锁 + 指令白名单 + 二次确认,防止 AI 幻觉炸机
- **钉钉通知**:Dify 触发 → 中台转发 → 群机器人单向推送
- **PM dashboard**:Token 漏斗、Prompt 灰度、团队时间线

## 文档索引

| 文档 | 用途 |
|---|---|
| `docs/superpowers/specs/2026-07-04-testmate-brief.md` | 老板汇报(232 行) |
| `docs/superpowers/specs/2026-07-04-testmate-design.md` | 完整技术方案(587 行) |

## 后续

P0 启动后,会在仓库里创建 `frontend_web/` / `backend_gateway/` / `ai_engine/` / `deploy/` 等子目录,详见详细方案 §5 工程项目架构。
