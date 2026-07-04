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
        { path: '', redirect: '/diagnosis' },
        { path: 'diagnosis', name: 'diagnosis', component: () => import('@/views/LogDiagnosis/index.vue') },
        { path: 'kb', name: 'kb', component: () => import('@/views/KnowledgeBase/index.vue') },
        { path: 'settings', name: 'settings', component: () => import('@/views/Settings/index.vue') },
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
