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
        { path: 'plaza',       name: 'plaza',       meta: { title: '智能体广场' },  component: () => import('@/views/Plaza/index.vue') },
        { path: 'agents/:code', name: 'agent-runner', meta: { title: '运行' },       component: () => import('@/views/AgentRunner/index.vue') },
        { path: 'kb-manage',   name: 'kb-manage',   meta: { title: '知识库' },      component: () => import('@/views/KnowledgeManage/index.vue') },
      ],
    },
  ],
});

router.beforeEach((to, _from, next) => {
  const userStore = useUserStore();
  if (to.meta.requiresAuth && !userStore.token) {
    next({ name: 'login', query: { redirect: to.fullPath } });
  } else {
    next();
  }
});

export default router;
