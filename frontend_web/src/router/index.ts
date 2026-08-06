import { createRouter, createWebHistory } from 'vue-router';
import { useUserStore } from '@/stores/user';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/Login/index.vue') },
    // 公共只读看板: 不需要登录, axios 用 VITE_ANONYMOUS_READ_TOKEN 调 API (后端 get_optional_user).
    // 独立顶层路由 (不在 MainLayout 下), 不显示导航栏, 避免暴露 /settings /kb-manage 等入口.
    { path: '/code-review-v2', name: 'code-review-v2', meta: { publicRead: true, title: '代码检视 V2', layout: 'bare' }, component: () => import('@/views/CodeReviewV2/index.vue') },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        // 默认进广场
        { path: '', redirect: '/plaza' },
        { path: 'plaza',       name: 'plaza',       meta: { title: '智能体广场', lede: 'SSD 测试域专用 AI 智能体 · 点击卡片进入运行页' },  component: () => import('@/views/Plaza/index.vue') },
        { path: 'code-review', name: 'code-review', meta: { title: '代码检视', lede: 'pr-agent 评审数据看板 · MR / 建议采纳率 / 规则命中 / 作者分布' }, component: () => import('@/views/CodeReview/index.vue') },
        { path: 'agents/:code', name: 'agent-runner', meta: { title: '运行' },       component: () => import('@/views/AgentRunner/index.vue') },
        { path: 'kb-manage',   name: 'kb-manage',   meta: { title: '知识库', lede: '所有智能体共享的私有知识源 · 已对接 RAGFlow' },      component: () => import('@/views/KnowledgeManage/index.vue') },
        { path: 'settings',   name: 'settings',   meta: { title: '设置', lede: '平台配置 · RAGFlow / Dify / 用户管理' },         component: () => import('@/views/Settings/index.vue') },
      ],
    },
  ],
});

router.beforeEach((to, _from, next) => {
  // publicRead 路由 (匿名看板): 直接放行, axios 拦截器会用 anonymous token
  if (to.meta.publicRead) return next();
  const userStore = useUserStore();
  if (to.meta.requiresAuth && !userStore.token) {
    next({ name: 'login', query: { redirect: to.fullPath } });
  } else {
    next();
  }
});

export default router;
