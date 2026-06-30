# AI 工作平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建一个本地单页 Web 应用,主页并排展示 RAGFlow / Dify 嵌入实例,配置页管理这些实例(增/改/删 + 导入导出),数据存 localStorage。

**Architecture:** React 18 + Vite SPA,react-router-dom v6 路由 `/`(主页 grid + iframe)与 `/settings`(配置 + 导入导出),`storage/instances.ts` 封装 localStorage 持久化,`useInstances` hook 提供响应式数据流,纯 CSS 单文件样式。

**Tech Stack:** Vite 5、React 18、TypeScript 5、react-router-dom v6、uuid v9。**不**上 Tailwind / 状态管理库 / 测试框架 — 业务简单,手测为主。

## Global Constraints

- 工作目录: `/Users/jarvs/Code/AI工作平台/`
- Node 版本: >= 18(由 Vite 5 要求)
- 包管理: npm(锁文件 `package-lock.json`)
- localStorage key 固定为 `ai-platform:instances:v1`
- iframe sandbox: `allow-scripts allow-same-origin allow-forms allow-popups`,**禁止** `allow-top-navigation`
- 文件 / 目录 / 字段命名: 全部英文(类名 PascalCase,变量 / 函数 camelCase)
- UI 文案: 中文为主,操作按钮 / 标题用中文(如 "新增" / "导出配置 JSON")
- 每次完成任务后立即 `git commit`,提交信息用 `type(scope): summary`(feat / chore / docs / refactor)
- 任何新依赖必须先告知用户,再 `npm install`

---

## File Structure

| 文件 | 职责 |
|---|---|
| `package.json` | 依赖与脚本 |
| `vite.config.ts` | Vite 配置,启用 `@vitejs/plugin-react` |
| `tsconfig.json` / `tsconfig.node.json` | TS 配置 |
| `index.html` | HTML 入口,挂载 `#root` |
| `src/main.tsx` | 启动 React + Router |
| `src/App.tsx` | 路由配置 |
| `src/types.ts` | `Instance` / `RAGFlowInstance` / `DifyInstance` / `ExportPayload` 类型 |
| `src/storage/instances.ts` | localStorage CRUD + import / export |
| `src/hooks/useInstances.ts` | 响应式封装 `storage/instances.ts` |
| `src/pages/HomePage.tsx` | 主页 grid 渲染所有实例 |
| `src/pages/SettingsPage.tsx` | 配置页:列表 + 表单 + 导入导出 |
| `src/components/InstancePanel.tsx` | 单个实例面板(iframe + 全屏) |
| `src/components/InstanceForm.tsx` | 新增 / 编辑表单 modal |
| `src/components/EmptyState.tsx` | 主页空状态 |
| `src/styles/global.css` | 全局样式(布局 / 卡片 / 按钮 / form / modal) |
| `README.md` | 启动 / 使用 / 备份说明 |

---

## Task 1: 项目脚手架

**Files:**
- Create: `package.json`
- Create: `vite.config.ts`
- Create: `tsconfig.json`
- Create: `tsconfig.node.json`
- Create: `index.html`
- Create: `src/main.tsx`
- Create: `src/App.tsx`(占位)
- Create: `src/styles/global.css`(空骨架)

- [ ] **Step 1: 初始化 package.json**

创建 `package.json`:

```json
{
  "name": "ai-work-platform",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2",
    "uuid": "^9.0.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@types/uuid": "^9.0.8",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.6"
  }
}
```

- [ ] **Step 2: 写 vite.config.ts**

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 }
});
```

- [ ] **Step 3: 写 tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: 写 tsconfig.node.json**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: 写 index.html**

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI 工作平台</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: 写 src/main.tsx**

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles/global.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
```

- [ ] **Step 7: 写 src/App.tsx 占位**

```tsx
import { Routes, Route } from 'react-router-dom';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<div>主页占位</div>} />
      <Route path="/settings" element={<div>配置页占位</div>} />
    </Routes>
  );
}
```

- [ ] **Step 8: 写 src/styles/global.css 最小骨架**

```css
* { box-sizing: border-box; }

html, body, #root {
  margin: 0;
  padding: 0;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  color: #1f2328;
  background: #f6f8fa;
}
```

- [ ] **Step 9: 安装依赖**

```bash
cd /Users/jarvs/Code/AI工作平台 && npm install
```

期望: 锁文件生成,无 ERR,可能有 WARN(可接受)。

- [ ] **Step 10: 验证 build 通过**

```bash
npm run build
```

期望: 看到 `dist/` 目录生成,Vite 输出 `built in ...ms`。

- [ ] **Step 11: commit**

```bash
git add -A
git commit -m "chore: scaffold Vite + React + TS project"
```

---

## Task 2: 类型 + 存储层

**Files:**
- Create: `src/types.ts`
- Create: `src/storage/instances.ts`

- [ ] **Step 1: 写 src/types.ts**

```ts
export type InstanceType = 'ragflow' | 'dify';

export interface BaseInstance {
  id: string;
  type: InstanceType;
  name: string;
  url: string;
  createdAt: string;
  updatedAt: string;
}

export interface RAGFlowInstance extends BaseInstance {
  type: 'ragflow';
  authToken?: string;
}

export interface DifyInstance extends BaseInstance {
  type: 'dify';
  apiKey?: string;
}

export type Instance = RAGFlowInstance | DifyInstance;

export interface ExportPayload {
  version: 1;
  exportedAt: string;
  instances: Instance[];
}
```

- [ ] **Step 2: 写 src/storage/instances.ts**

```ts
import type { ExportPayload, Instance, InstanceType } from '../types';

const STORAGE_KEY = 'ai-platform:instances:v1';

function readRaw(): Instance[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as Instance[]) : [];
  } catch {
    return [];
  }
}

function writeRaw(items: Instance[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

export function listInstances(): Instance[] {
  return readRaw();
}

export function addInstance<T extends Instance>(item: T): T {
  const items = readRaw();
  items.push(item);
  writeRaw(items);
  return item;
}

export function updateInstance(id: string, patch: Partial<Instance>): Instance | null {
  const items = readRaw();
  const idx = items.findIndex((i) => i.id === id);
  if (idx === -1) return null;
  const updated: Instance = {
    ...items[idx],
    ...patch,
    id: items[idx].id,
    type: items[idx].type,
    updatedAt: new Date().toISOString()
  } as Instance;
  items[idx] = updated;
  writeRaw(items);
  return updated;
}

export function removeInstance(id: string): boolean {
  const items = readRaw();
  const next = items.filter((i) => i.id !== id);
  if (next.length === items.length) return false;
  writeRaw(next);
  return true;
}

export function exportToJSON(): string {
  const payload: ExportPayload = {
    version: 1,
    exportedAt: new Date().toISOString(),
    instances: readRaw()
  };
  return JSON.stringify(payload, null, 2);
}

function isInstance(value: unknown): value is Instance {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  if (typeof v.id !== 'string' || typeof v.name !== 'string' || typeof v.url !== 'string') return false;
  if (v.type !== 'ragflow' && v.type !== 'dify') return false;
  if (typeof v.createdAt !== 'string' || typeof v.updatedAt !== 'string') return false;
  if (v.type === 'ragflow' && v.authToken !== undefined && typeof v.authToken !== 'string') return false;
  if (v.type === 'dify' && v.apiKey !== undefined && typeof v.apiKey !== 'string') return false;
  return true;
}

export function importFromJSON(json: string): { added: number; skipped: number } {
  const data = JSON.parse(json) as ExportPayload;
  if (!data || data.version !== 1 || !Array.isArray(data.instances)) {
    throw new Error('配置格式不匹配,需要 version: 1');
  }
  const incoming = data.instances.filter(isInstance);
  const existing = readRaw();
  const existingIds = new Set(existing.map((i) => i.id));
  const merged = [...existing];
  let added = 0;
  let skipped = 0;
  for (const item of incoming) {
    if (existingIds.has(item.id)) {
      skipped++;
      console.warn(`[import] 跳过重复 id: ${item.id}`);
    } else {
      merged.push(item);
      existingIds.add(item.id);
      added++;
    }
  }
  writeRaw(merged);
  return { added, skipped };
}

export function instancesByType(type: InstanceType): Instance[] {
  return readRaw().filter((i) => i.type === type);
}
```

- [ ] **Step 3: 验证 TS 编译通过**

```bash
npx tsc -b
```

期望: 0 error。

- [ ] **Step 4: commit**

```bash
git add src/types.ts src/storage/instances.ts
git commit -m "feat: add instance types and localStorage storage layer"
```

---

## Task 3: useInstances hook

**Files:**
- Create: `src/hooks/useInstances.ts`

- [ ] **Step 1: 写 src/hooks/useInstances.ts**

```ts
import { useCallback, useEffect, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import {
  addInstance as addToStorage,
  exportToJSON,
  importFromJSON,
  listInstances,
  removeInstance as removeFromStorage,
  updateInstance as updateInStorage
} from '../storage/instances';
import type { Instance, InstanceType } from '../types';

export function useInstances() {
  const [instances, setInstances] = useState<Instance[]>(() => listInstances());

  const refresh = useCallback(() => {
    setInstances(listInstances());
  }, []);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'ai-platform:instances:v1') refresh();
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [refresh]);

  const add = useCallback(
    (type: InstanceType, payload: Omit<Instance, 'id' | 'type' | 'createdAt' | 'updatedAt'>) => {
      const now = new Date().toISOString();
      const base = { id: uuidv4(), createdAt: now, updatedAt: now, ...payload };
      const item = { ...base, type } as Instance;
      addToStorage(item);
      refresh();
      return item;
    },
    [refresh]
  );

  const update = useCallback(
    (id: string, patch: Partial<Instance>) => {
      const result = updateInStorage(id, patch);
      refresh();
      return result;
    },
    [refresh]
  );

  const remove = useCallback(
    (id: string) => {
      const ok = removeFromStorage(id);
      refresh();
      return ok;
    },
    [refresh]
  );

  const exportConfig = useCallback(() => exportToJSON(), []);

  const importConfig = useCallback(
    (json: string) => {
      const result = importFromJSON(json);
      refresh();
      return result;
    },
    [refresh]
  );

  return { instances, add, update, remove, exportConfig, importConfig, refresh };
}
```

- [ ] **Step 2: 验证 TS 编译通过**

```bash
npx tsc -b
```

期望: 0 error。

- [ ] **Step 3: commit**

```bash
git add src/hooks/useInstances.ts
git commit -m "feat: add useInstances hook for reactive instance state"
```

---

## Task 4: InstancePanel 组件

**Files:**
- Create: `src/components/InstancePanel.tsx`

- [ ] **Step 1: 写 src/components/InstancePanel.tsx**

```tsx
import { useState } from 'react';
import type { Instance } from '../types';

interface Props {
  instance: Instance;
}

export default function InstancePanel({ instance }: Props) {
  const [fullscreen, setFullscreen] = useState(false);

  const sandbox =
    'allow-scripts allow-same-origin allow-forms allow-popups';

  const body = (
    <iframe
      src={instance.url}
      title={instance.name}
      sandbox={sandbox}
      frameBorder={0}
      style={{ width: '100%', height: '100%', border: 0, minHeight: 600 }}
    />
  );

  if (fullscreen) {
    return (
      <div className="panel panel--fullscreen">
        <div className="panel__header">
          <span className="panel__title">{instance.name}</span>
          <button className="btn btn--ghost" onClick={() => setFullscreen(false)}>
            退出全屏
          </button>
        </div>
        <div className="panel__body">{body}</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel__header">
        <span className="panel__title">{instance.name}</span>
        <span className="panel__type">{instance.type.toUpperCase()}</span>
        <button
          className="btn btn--ghost"
          onClick={() => setFullscreen(true)}
          aria-label="全屏"
        >
          ⛶
        </button>
      </div>
      <div className="panel__body">{body}</div>
    </div>
  );
}
```

- [ ] **Step 2: 验证 TS 编译通过**

```bash
npx tsc -b
```

期望: 0 error。

- [ ] **Step 3: commit**

```bash
git add src/components/InstancePanel.tsx
git commit -m "feat: add InstancePanel with fullscreen toggle"
```

---

## Task 5: EmptyState 组件

**Files:**
- Create: `src/components/EmptyState.tsx`

- [ ] **Step 1: 写 src/components/EmptyState.tsx**

```tsx
import { Link } from 'react-router-dom';

export default function EmptyState() {
  return (
    <div className="empty">
      <h2>还没有任何嵌入实例</h2>
      <p>先去配置页登记一个 RAGFlow 或 Dify 实例,回来就能看到。</p>
      <Link to="/settings" className="btn btn--primary">
        前往配置
      </Link>
    </div>
  );
}
```

- [ ] **Step 2: 验证 TS 编译通过**

```bash
npx tsc -b
```

期望: 0 error。

- [ ] **Step 3: commit**

```bash
git add src/components/EmptyState.tsx
git commit -m "feat: add EmptyState component for empty home"
```

---

## Task 6: HomePage 页面

**Files:**
- Create: `src/pages/HomePage.tsx`
- Modify: `src/App.tsx`(替换主页路由)

- [ ] **Step 1: 写 src/pages/HomePage.tsx**

```tsx
import { Link } from 'react-router-dom';
import InstancePanel from '../components/InstancePanel';
import EmptyState from '../components/EmptyState';
import { useInstances } from '../hooks/useInstances';

export default function HomePage() {
  const { instances } = useInstances();

  return (
    <div className="page">
      <header className="topbar">
        <h1 className="topbar__title">AI 工作平台</h1>
        <Link to="/settings" className="btn btn--ghost">⚙ 配置</Link>
      </header>
      <main className="content">
        {instances.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="grid">
            {instances.map((inst) => (
              <InstancePanel key={inst.id} instance={inst} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
```

- [ ] **Step 2: 修改 src/App.tsx 接入 HomePage**

```tsx
import { Routes, Route } from 'react-router-dom';
import HomePage from './pages/HomePage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/settings" element={<div>配置页占位</div>} />
    </Routes>
  );
}
```

- [ ] **Step 3: 验证 build 通过**

```bash
npm run build
```

期望: 0 error。

- [ ] **Step 4: commit**

```bash
git add src/pages/HomePage.tsx src/App.tsx
git commit -m "feat: add HomePage with grid layout for instance panels"
```

---

## Task 7: InstanceForm 组件(modal)

**Files:**
- Create: `src/components/InstanceForm.tsx`

- [ ] **Step 1: 写 src/components/InstanceForm.tsx**

```tsx
import { useEffect, useState } from 'react';
import type { Instance, InstanceType } from '../types';

interface Props {
  type: InstanceType;
  initial?: Instance;
  onSubmit: (payload: { name: string; url: string; authToken?: string; apiKey?: string }) => void;
  onCancel: () => void;
}

export default function InstanceForm({ type, initial, onSubmit, onCancel }: Props) {
  const [name, setName] = useState(initial?.name ?? '');
  const [url, setUrl] = useState(initial?.url ?? '');
  const [secret, setSecret] = useState<string>(
    initial && initial.type === 'ragflow'
      ? initial.authToken ?? ''
      : initial && initial.type === 'dify'
      ? initial.apiKey ?? ''
      : ''
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);

  const label = type.toUpperCase();
  const secretLabel = type === 'ragflow' ? 'Auth Token(可选)' : 'API Key(可选)';
  const secretField = type === 'ragflow' ? 'authToken' : 'apiKey';

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError('名称必填');
    if (!url.trim()) return setError('URL 必填');
    try {
      new URL(url);
    } catch {
      return setError('URL 格式不正确');
    }
    setError(null);
    const payload: { name: string; url: string; authToken?: string; apiKey?: string } = {
      name: name.trim(),
      url: url.trim()
    };
    if (secret.trim()) payload[secretField] = secret.trim();
    onSubmit(payload);
  }

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal__title">
          {initial ? '编辑' : '新增'} {label} 实例
        </h3>
        <form onSubmit={handleSubmit} className="form">
          <label className="form__field">
            <span>名称</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例:内部知识库"
              autoFocus
            />
          </label>
          <label className="form__field">
            <span>URL</span>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={
                type === 'ragflow'
                  ? 'http://127.0.0.1:18080/chats/share?shared_id=...&auth=...'
                  : 'http://127.0.0.1/chatbot/XXXX'
              }
            />
          </label>
          <label className="form__field">
            <span>{secretLabel}</span>
            <input
              type="text"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              placeholder="可留空"
            />
          </label>
          {error && <div className="form__error">{error}</div>}
          <div className="form__actions">
            <button type="button" className="btn btn--ghost" onClick={onCancel}>
              取消
            </button>
            <button type="submit" className="btn btn--primary">
              保存
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 验证 TS 编译通过**

```bash
npx tsc -b
```

期望: 0 error。

- [ ] **Step 3: commit**

```bash
git add src/components/InstanceForm.tsx
git commit -m "feat: add InstanceForm modal with validation"
```

---

## Task 8: SettingsPage 页面

**Files:**
- Create: `src/pages/SettingsPage.tsx`
- Modify: `src/App.tsx`(接入 SettingsPage)

- [ ] **Step 1: 写 src/pages/SettingsPage.tsx**

```tsx
import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import InstanceForm from '../components/InstanceForm';
import { useInstances } from '../hooks/useInstances';
import type { Instance, InstanceType } from '../types';

function Section({
  type,
  items,
  onAdd,
  onEdit,
  onRemove
}: {
  type: InstanceType;
  items: Instance[];
  onAdd: (payload: { name: string; url: string; authToken?: string; apiKey?: string }) => void;
  onEdit: (id: string, payload: { name: string; url: string; authToken?: string; apiKey?: string }) => void;
  onRemove: (id: string) => void;
}) {
  const [editing, setEditing] = useState<Instance | null>(null);
  const [adding, setAdding] = useState(false);

  return (
    <section className="card">
      <h2 className="card__title">{type.toUpperCase()} 实例</h2>
      {items.length === 0 ? (
        <p className="card__empty">还没有 {type.toUpperCase()} 实例。</p>
      ) : (
        <ul className="instance-list">
          {items.map((item) => (
            <li key={item.id} className="instance-item">
              <div className="instance-item__main">
                <div className="instance-item__name">{item.name}</div>
                <div className="instance-item__url" title={item.url}>
                  {item.url}
                </div>
              </div>
              <div className="instance-item__actions">
                <button className="btn btn--ghost" onClick={() => setEditing(item)}>
                  编辑
                </button>
                <button
                  className="btn btn--danger"
                  onClick={() => {
                    if (window.confirm(`确定删除 "${item.name}" 吗?`)) onRemove(item.id);
                  }}
                >
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <button className="btn btn--primary" onClick={() => setAdding(true)}>
        + 新增
      </button>
      {adding && (
        <InstanceForm
          type={type}
          onSubmit={(p) => {
            onAdd(p);
            setAdding(false);
          }}
          onCancel={() => setAdding(false)}
        />
      )}
      {editing && (
        <InstanceForm
          type={type}
          initial={editing}
          onSubmit={(p) => {
            onEdit(editing.id, p);
            setEditing(null);
          }}
          onCancel={() => setEditing(null)}
        />
      )}
    </section>
  );
}

export default function SettingsPage() {
  const { instances, add, update, remove, exportConfig, importConfig } = useInstances();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importMessage, setImportMessage] = useState<string | null>(null);

  const ragItems = instances.filter((i) => i.type === 'ragflow');
  const difyItems = instances.filter((i) => i.type === 'dify');

  function handleExport() {
    const json = exportConfig();
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const date = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `ai-platform-config-${date}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleImportFile(file: File) {
    try {
      const text = await file.text();
      const result = importConfig(text);
      setImportMessage(`导入完成: 新增 ${result.added} 个,跳过 ${result.skipped} 个重复`);
    } catch (e) {
      setImportMessage(`导入失败: ${(e as Error).message}`);
    }
  }

  return (
    <div className="page">
      <header className="topbar">
        <Link to="/" className="btn btn--ghost">← 返回主页</Link>
        <h1 className="topbar__title">配置</h1>
        <div style={{ width: 88 }} />
      </header>
      <main className="content content--narrow">
        <Section
          type="ragflow"
          items={ragItems}
          onAdd={(p) => add('ragflow', p)}
          onEdit={(id, p) => update(id, p)}
          onRemove={remove}
        />
        <Section
          type="dify"
          items={difyItems}
          onAdd={(p) => add('dify', p)}
          onEdit={(id, p) => update(id, p)}
          onRemove={remove}
        />

        <section className="card">
          <h2 className="card__title">备份 / 迁移</h2>
          <div className="row">
            <button className="btn btn--primary" onClick={handleExport}>
              导出配置 JSON
            </button>
            <button className="btn" onClick={() => fileInputRef.current?.click()}>
              导入配置 JSON
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json,.json"
              style={{ display: 'none' }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void handleImportFile(f);
                e.target.value = '';
              }}
            />
          </div>
          {importMessage && <p className="hint">{importMessage}</p>}
        </section>
      </main>
    </div>
  );
}
```

- [ ] **Step 2: 修改 src/App.tsx 接入 SettingsPage**

```tsx
import { Routes, Route } from 'react-router-dom';
import HomePage from './pages/HomePage';
import SettingsPage from './pages/SettingsPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/settings" element={<SettingsPage />} />
    </Routes>
  );
}
```

- [ ] **Step 3: 验证 build 通过**

```bash
npm run build
```

期望: 0 error。

- [ ] **Step 4: commit**

```bash
git add src/pages/SettingsPage.tsx src/App.tsx
git commit -m "feat: add SettingsPage with sections, form modal, import/export"
```

---

## Task 9: 全局样式

**Files:**
- Modify: `src/styles/global.css`(覆盖 Task 1 的最小骨架)

- [ ] **Step 1: 写完整 global.css**

```css
* { box-sizing: border-box; }

html, body, #root {
  margin: 0;
  padding: 0;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  color: #1f2328;
  background: #f6f8fa;
}

a { color: inherit; text-decoration: none; }
button { font: inherit; cursor: pointer; }

.page {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: #ffffff;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.topbar__title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.content {
  flex: 1;
  overflow: auto;
  padding: 20px;
}

.content--narrow {
  max-width: 880px;
  margin: 0 auto;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(480px, 1fr));
  gap: 16px;
  align-items: stretch;
}

.panel {
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  min-height: 600px;
  height: calc(100vh - 120px);
}

.panel--fullscreen {
  position: fixed;
  inset: 0;
  z-index: 100;
  border-radius: 0;
  height: 100vh;
  min-height: 100vh;
}

.panel__header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #f9fafb;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.panel__title {
  font-weight: 600;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel__type {
  font-size: 11px;
  letter-spacing: 0.05em;
  color: #6b7280;
  background: #eef2ff;
  border-radius: 4px;
  padding: 2px 6px;
}

.panel__body {
  flex: 1;
  position: relative;
  background: #ffffff;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #d1d5db;
  background: #ffffff;
  color: #1f2328;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 14px;
  transition: background 0.15s, border-color 0.15s;
}
.btn:hover { background: #f3f4f6; }
.btn--ghost { border-color: transparent; background: transparent; }
.btn--ghost:hover { background: #f3f4f6; }
.btn--primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
}
.btn--primary:hover { background: #1d4ed8; border-color: #1d4ed8; }
.btn--danger {
  background: #ffffff;
  border-color: #fca5a5;
  color: #b91c1c;
}
.btn--danger:hover { background: #fef2f2; }

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 100%;
  gap: 12px;
  color: #4b5563;
}
.empty h2 { margin: 0; }
.empty p { margin: 0; }

.card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 20px;
  margin-bottom: 16px;
}
.card__title { margin: 0 0 12px; font-size: 16px; font-weight: 600; }
.card__empty { color: #6b7280; margin: 0 0 12px; }

.instance-list {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.instance-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}
.instance-item__main { flex: 1; min-width: 0; }
.instance-item__name { font-weight: 500; }
.instance-item__url {
  font-size: 12px;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.instance-item__actions { display: flex; gap: 6px; }

.row { display: flex; gap: 8px; flex-wrap: wrap; }
.hint { margin: 8px 0 0; color: #4b5563; font-size: 13px; }

.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.modal {
  background: #ffffff;
  border-radius: 10px;
  width: min(480px, 92vw);
  padding: 20px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.15);
}
.modal__title { margin: 0 0 12px; font-size: 16px; font-weight: 600; }

.form { display: flex; flex-direction: column; gap: 12px; }
.form__field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.form__field input {
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 14px;
  font-family: inherit;
}
.form__field input:focus { outline: 2px solid #2563eb; outline-offset: -1px; border-color: #2563eb; }
.form__error { color: #b91c1c; font-size: 13px; }
.form__actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
```

- [ ] **Step 2: 验证 build 通过**

```bash
npm run build
```

期望: 0 error。

- [ ] **Step 3: commit**

```bash
git add src/styles/global.css
git commit -m "feat: add global stylesheet for layout, panels, forms, modal"
```

---

## Task 10: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: 写 README.md**

```markdown
# AI 工作平台

本地单页 Web 应用,把 RAGFlow / Dify 的嵌入实例并排展示在一个主页,带独立配置页。

## 启动

```bash
npm install
npm run dev      # 开发模式,http://localhost:5173
npm run build    # 生产构建,产物在 dist/
npm run preview  # 预览生产构建
```

## 使用

1. 打开主页 `http://localhost:5173/`
2. 右上角点 **⚙ 配置** 进入配置页
3. 在 **RAGFlow 实例** / **Dify 实例** 两个区里点 **+ 新增**,填名称、URL(可选 Auth Token / API Key)
4. 保存后点 **← 返回主页**,即可看到实例以 grid 形式并排展示
5. 单个面板右上角 **⛶** 切换全屏;按 **Esc** 或再次点 **退出全屏** 退出

## 配置存储

- 浏览器 `localStorage`,key = `ai-platform:instances:v1`
- 同一浏览器同一域名共享,清浏览器数据会丢
- 配置页底部 **导出配置 JSON** 可下载备份;**导入配置 JSON** 在新浏览器恢复(按 id 去重,不覆盖)

## iframe 安全

`src/components/InstancePanel.tsx` 给 iframe 配的 `sandbox`:

```
allow-scripts allow-same-origin allow-forms allow-popups
```

**不**含 `allow-top-navigation`,防止嵌入页把整个平台劫持到外站。
```

- [ ] **Step 2: commit**

```bash
git add README.md
git commit -m "docs: add README with usage and storage notes"
```

---

## Task 11: 端到端自检

- [ ] **Step 1: 跑 build**

```bash
npm run build
```

期望: 0 error。

- [ ] **Step 2: 启动 dev server**

```bash
npm run dev
```

期望: 输出 `Local: http://localhost:5173/`,浏览器打开后:
- 主页显示空状态 + "前往配置" 按钮
- 点 **前往配置** → `/settings`
- **RAGFlow 实例** 区点 **+ 新增**,填:
  - 名称: `内部知识库`
  - URL: `http://127.0.0.1:18080/chats/share?shared_id=5338072a72bf11f1a82f771aafbe4f81&from=chat&auth=ir7sYP4h2kMSxcjSi2IfailLxbATmCdm&theme=light`
  - Auth Token: 留空
  - 点 **保存**
- **Dify 实例** 区点 **+ 新增**,填:
  - 名称: `Dify 测试`
  - URL: `https://example.com`(占位)
  - 点 **保存**
- 点 **← 返回主页**,看到两个 panel 并排,RAGFlow panel 内 iframe 加载示例链接(显示 RAGFlow UI 或对应域名的内容)
- 点 panel 右上角 **⛶** 验证全屏
- 回 `/settings`,点 **导出配置 JSON**,验证下载 `ai-platform-config-YYYY-MM-DD.json`,打开是合法 JSON 含两个实例
- 删掉所有实例,清空后回主页,显示空状态

- [ ] **Step 3: 关 dev server**

Ctrl-C 结束。

- [ ] **Step 4: 最终 commit(如有微调)**

```bash
git status
# 如果有改动:
git add -A
git commit -m "chore: post-e2e tweaks"
```

---

## Self-Review

1. **Spec coverage**:
   - 主页 grid + iframe → Task 4、Task 6
   - 配置页 / 增 / 改 / 删 → Task 7、Task 8
   - 导出 / 导入 → Task 2、Task 8
   - 全屏切换 → Task 4
   - localStorage 持久化 → Task 2、Task 3
   - iframe sandbox 安全约束 → Task 4
   - URL 校验 → Task 7
   - 空状态 → Task 5
   - README → Task 10
   - 端到端验证 → Task 11
2. **Placeholder scan**: 无 TBD / TODO,所有代码块完整。
3. **Type consistency**: `Instance` / `RAGFlowInstance` / `DifyInstance` 在 Task 2 定义,Task 3 起的 hook 与组件一致使用;`useInstances` 的 `add(type, payload)` 与 SettingsPage 的 `onAdd` 签名对齐(`authToken` / `apiKey` 通过 `secretField` 区分);`update(id, patch)` 用 `Partial<Instance>`。
4. **风险点**: 用户的 RAGFlow URL 当前指向 `127.0.0.1:18080`,只有本地能加载,远程浏览器看不到内容 — 属预期,Task 11 用占位 Dify URL 互补验证。
