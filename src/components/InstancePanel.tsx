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
      allow="microphone"
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
