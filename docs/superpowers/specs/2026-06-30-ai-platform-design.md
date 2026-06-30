# AI 工作平台 — 设计文档

- 日期: 2026-06-30
- 作者: Codex (协助起草)
- 状态: 已通过用户确认,待落盘实现

## 目标

搭建一个本地单页 Web 应用,把 RAGFlow 和 Dify 的嵌入实例并排展示在一个主页上,提供独立配置页管理这些实例。

不做的事(YAGNI):

- 不做用户系统、不做登录鉴权
- 不做跨设备同步(用 localStorage + 导入导出做迁移)
- 不做嵌入实例内部的二次封装(只负责 iframe 加载)
- 不做后端服务

## 用户故事

1. 作为 SSD 测试工程师,我希望把 RAGFlow 的 share 链接和 Dify 的 chatbot 链接登记到平台,在一个页面同时看到两个 agent 的对话界面,不用来回切浏览器标签。
2. 我希望能方便地新增/编辑/删除这些嵌入实例,URL / auth token / 备注都不应该硬编码在代码里。
3. 我希望能导出配置做备份,或者在换电脑时导入。

## 页面

### 1. 主页 `/`

- 顶部 nav bar:
  - 左侧:平台标题 "AI 工作平台"
  - 右侧:"⚙ 配置" 按钮 → 跳转 `/settings`
- 主体:CSS Grid 展示所有已登记的实例
  - 响应式:`grid-template-columns: repeat(auto-fit, minmax(480px, 1fr))`
  - 宽屏两列(默认 RAGFlow 左 / Dify 右),窄屏自动堆叠成单列
- 每个面板:
  - 头部:实例名 + 右上角 "⛶ 全屏" 按钮
  - 主体:`<iframe src={url} sandbox="allow-scripts allow-same-origin allow-forms allow-popups" frameborder="0" />`
  - 全屏状态:占满 viewport,Esc 或再次点 "⛶" 退出
- 空状态:无实例时显示居中提示 + "前往配置" 按钮

### 2. 配置页 `/settings`

- 顶部:返回主页按钮 + 页面标题 "配置"
- 两个分区(垂直堆叠),各自一张卡片:
  - **RAGFlow 实例**
  - **Dify 实例**
- 卡片内容:
  - 该类型下所有实例的列表(每项显示名称 + URL 摘要 + "编辑" / "删除" 按钮)
  - 列表底部 "+ 新增" 按钮
- 页面底部固定区:
  - "导出配置 JSON" 按钮 — 触发下载 `ai-platform-config-YYYY-MM-DD.json`
  - "导入配置 JSON" 按钮 — 选择本地 JSON 文件,做 schema 校验后合并入库
- 增/改表单用 modal(在当前卡片内弹出),不跳页

## 数据模型

```ts
type InstanceType = 'ragflow' | 'dify';

interface BaseInstance {
  id: string;          // uuid v4
  type: InstanceType;
  name: string;        // 用户起的名字
  url: string;         // 嵌入 URL(RAGFlow 含 shared_id + auth; Dify 含 chatbot id)
  createdAt: string;   // ISO 8601
  updatedAt: string;   // ISO 8601
}

interface RAGFlowInstance extends BaseInstance {
  type: 'ragflow';
  authToken?: string;  // 备用,部分 RAGFlow URL 需要单独传 token
}

interface DifyInstance extends BaseInstance {
  type: 'dify';
  apiKey?: string;     // 备用,Dify 嵌入可选 API key
}

type Instance = RAGFlowInstance | DifyInstance;

interface ExportPayload {
  version: 1;
  exportedAt: string;
  instances: Instance[];
}
```

## 存储

- 单一 localStorage key:`ai-platform:instances:v1`
- value:`Instance[]` 的 JSON 序列化结果
- 所有读 / 写 / 删都走 `storage/instances.ts` 模块,组件不直接接触 localStorage
- 导入导出格式见 `ExportPayload`,带 `version` 字段做未来兼容

## 技术栈

- **构建**: Vite 5
- **框架**: React 18 + TypeScript
- **路由**: react-router-dom v6
- **ID 生成**: uuid v4
- **样式**: 原生 CSS(单文件 `global.css`),不上 Tailwind / CSS-in-JS
- **包管理**: npm

## 关键交互细节

- **iframe sandbox**: `allow-scripts allow-same-origin allow-forms allow-popups`,**不**加 `allow-top-navigation` 防止劫持外层页面
- **URL 校验**:表单提交前必须 `new URL(value)` 成功,失败提示 "URL 格式不正确"
- **删除确认**:用 `window.confirm()`,不弹自定义 modal
- **导入冲突**:导入时按 `id` 去重,已存在的 `id` 跳过并在控制台打 warn;不覆盖
- **空 URL 处理**:URL 为空时表单不提交,提示 "URL 必填"

## 目录结构

```
AI工作平台/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── README.md
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── types.ts
    ├── storage/
    │   └── instances.ts
    ├── hooks/
    │   └── useInstances.ts
    ├── pages/
    │   ├── HomePage.tsx
    │   └── SettingsPage.tsx
    ├── components/
    │   ├── InstancePanel.tsx
    │   ├── InstanceForm.tsx
    │   └── EmptyState.tsx
    └── styles/
        └── global.css
```

## 验证标准

实现完成后必须满足:

1. `npm install` 一次成功,无 peer dep 警告以外的报错
2. `npm run build` 通过
3. `npm run dev` 启动后,主页在 http://localhost:5173 可见
4. 配置页能新增一个 RAGFlow 实例(用用户提供的示例 URL),保存后回主页能看到 iframe 加载
5. 配置页能新增一个 Dify 实例(URL 留空占位,待用户填),保存后回主页能看到占位面板
6. 导出 JSON 下载文件可读,内容是合法 JSON
7. 重新导入同一份 JSON,实例数翻倍(预期行为,因为按 id 去重是新 id)

## 范围之外(明确不做)

- 暗色主题(后续可加 CSS 变量切换)
- 拖拽排序
- iframe 重载按钮(浏览器自带刷新即可)
- 多用户 / 鉴权
- 后端持久化
- 嵌入实例内部 API 调用(RAGFlow / Dify 的 REST API)
