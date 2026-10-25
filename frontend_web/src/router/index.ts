import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { useUserStore } from '@/stores/user';

/**
 * 路由表 —— 单独导出, 方便单测直接断言 (名字 / meta / 跳转规则).
 */
export const routes: RouteRecordRaw[] = [
    { path: '/login', name: 'login', component: () => import('@/views/Login/index.vue') },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        // ===== 首页 = 能力墙 (2026-10-25) =====
        // 匿名可读: 首页对未登录用户开放只读 (能看能力清单与角色),
        // 进详情页需要登录 —— 唯一例外是标记 publicRead 的代码检视看板.
        { path: '', name: 'home', meta: { publicRead: true, title: '工作台', lede: '测试伙伴能干的活都在这儿 —— 工具、看板、底座, 点卡片直接进去' }, component: () => import('@/views/Home/index.vue') },
        // 旧地址 (原「智能体广场」): 保留跳转, 免得旧书签 404
        { path: 'plaza', redirect: { name: 'home' } },

        // ===== 看板型: 代码检视 (匿名只读) =====
        // publicRead 标记: 未登录也放行, 走完整布局 (导航栏/侧栏都显示, 跟登录用户一致).
        // axios 拦截器对 publicRead 路由: 登录用 user token, 未登录用 VITE_ANONYMOUS_READ_TOKEN.
        { path: 'code-review', name: 'code-review', meta: { publicRead: true, title: '代码检视', lede: '代码评审数据看板 —— MR 生命周期 / 建议采纳率 / 规则命中 / 作者分布' }, component: () => import('@/views/Capability/BoardView.vue') },

        // ===== 工具型: 运行页 =====
        { path: 'c/:code', name: 'tool-runner', meta: { title: '运行' }, component: () => import('@/views/Capability/ToolRunner.vue') },
        // 旧地址 (原 /agents/:code): 保留跳转
        { path: 'agents/:code', redirect: (to) => ({ name: 'tool-runner', params: to.params }) },

        // ===== 底座型: AI 资产市场 =====
        { path: 'market', name: 'market', meta: { title: 'AI 资产市场', lede: '智能体的技能沉淀 —— 插件 / 技能 / 连接器, 挑一个装进你的 Agent' }, component: () => import('@/views/Capability/Catalog/index.vue') },

        // ===== 底座型: 知识库 =====
        // 以前知识库是侧栏跟「广场」平级的顶级项, 现在它是能力墙上的一张卡.
        { path: 'kb-manage', name: 'kb-manage', meta: { title: '知识库', lede: 'RAG 知识源 —— 数据集 / 文档 / 分段, 检索即用' }, component: () => import('@/views/Capability/Library/index.vue') },

        { path: 'settings', name: 'settings', meta: { title: '设置', lede: '平台配置 · RAGFlow / Dify / 用户管理' }, component: () => import('@/views/Settings/index.vue') },
      ],
    },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to, _from, next) => {
  // publicRead 路由 (首页能力墙 / 代码检视): 匿名也放行, 走完整 MainLayout 布局
  if (to.meta.publicRead) return next();
  const userStore = useUserStore();
  if (to.meta.requiresAuth && !userStore.token) {
    next({ name: 'login', query: { redirect: to.fullPath } });
  } else {
    next();
  }
});

export default router;
