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
