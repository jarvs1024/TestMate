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
