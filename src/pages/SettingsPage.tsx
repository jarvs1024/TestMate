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
