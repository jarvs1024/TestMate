import { createRouter, createWebHistory } from 'vue-router';
import { useUserStore } from '@/stores/user';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/Login/index.vue') },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        // 默认进广场
        { path: '', redirect: '/plaza' },
        { path: 'plaza',       name: 'plaza',       meta: { title: '智能体广场', lede: 'SSD 测试域专用 AI 智能体 · 点击卡片进入运行页' },  component: () => import('@/views/Plaza/index.vue') },
        // 代码检视: ReviewAgent (原 pr-agent 版已下线, 合并到这一个).
        // publicRead 标记: 未登录也放行, 走完整布局 (导航栏/侧栏都显示, 跟登录用户一致).
        // axios 拦截器对 publicRead 路由: 登录用 user token, 未登录用 VITE_ANONYMOUS_READ_TOKEN.
        { path: 'code-review', name: 'code-review', meta: { publicRead: true, title: '代码检视', lede: 'ReviewAgent 评审数据看板 · MR / 建议采纳率 / 规则命中 / 作者分布' }, component: () => import('@/views/CodeReviewV2/index.vue') },
        { path: 'agents/:code', name: 'agent-runner', meta: { title: '运行' },       component: () => import('@/views/AgentRunner/index.vue') },
        { path: 'kb-manage',   name: 'kb-manage',   meta: { title: '知识库', lede: '所有智能体共享的私有知识源 · 已对接 RAGFlow' },      component: () => import('@/views/KnowledgeManage/index.vue') },
        { path: 'settings',   name: 'settings',   meta: { title: '设置', lede: '平台配置 · RAGFlow / Dify / 用户管理' },         component: () => import('@/views/Settings/index.vue') },
      ],
    },
  ],
});

router.beforeEach((to, _from, next) => {
  // publicRead 路由 (代码检视): 匿名也放行, 走完整 MainLayout 布局
  if (to.meta.publicRead) return next();
  const userStore = useUserStore();
  if (to.meta.requiresAuth && !userStore.token) {
    next({ name: 'login', query: { redirect: to.fullPath } });
  } else {
    next();
  }
});

export default router;
