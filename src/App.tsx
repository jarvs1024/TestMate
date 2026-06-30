import { Routes, Route } from 'react-router-dom';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<div>主页占位</div>} />
      <Route path="/settings" element={<div>配置页占位</div>} />
    </Routes>
  );
}
