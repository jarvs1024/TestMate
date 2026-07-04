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
        { path: '', redirect: '/kb' },
        { path: 'kb',         name: 'kb',     meta: { title: '知识库检索' },    component: () => import('@/views/KnowledgeBase/index.vue') },
        { path: 'diagnosis',  name: 'diag',   meta: { title: '日志分析' },      component: () => import('@/views/LogDiagnosis/index.vue') },
        { path: 'cases',      name: 'cases',  meta: { title: '用例生成' },      component: () => import('@/views/TestCaseBuilder/index.vue') },
        { path: 'ops',        name: 'ops',    meta: { title: '环境运维' },      component: () => import('@/views/MachineOps/index.vue') },
        { path: 'plan',       name: 'plan',   meta: { title: '测试方案' },      component: () => import('@/views/TestPlanBuilder/index.vue') },
        { path: 'settings',   name: 'settings', meta: { title: '系统设置' },    component: () => import('@/views/Settings/index.vue') },
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
