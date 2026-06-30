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
