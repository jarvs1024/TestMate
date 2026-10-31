import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { nextTick, watch } from 'vue';
import { useUserStore } from '@/stores/user';
import { platformName } from '@/stores/platform';

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
        { path: '', name: 'home', meta: { publicRead: true, title: '工作台', lede: '测试伙伴能干的活都在这儿 —— 资产、工具、看板, 点卡片直接进去' }, component: () => import('@/views/Home/index.vue') },
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

        // ===== 资产型: 插件·技能·连接 =====
        { path: 'market', name: 'market', meta: { title: '插件·技能·连接', lede: '可复用的扩展资产 —— 插件 / 技能 / 连接器, 挑一个装进你的 Agent' }, component: () => import('@/views/Capability/Catalog/index.vue') },

        // ===== 资产型: 知识库 =====
        // 以前知识库是侧栏跟「广场」平级的顶级项, 现在它是能力墙上的一张卡.
        { path: 'kb-manage', name: 'kb-manage', meta: { title: '知识库', lede: 'RAG 知识源 —— 数据集 / 文档 / 分段, 检索即用' }, component: () => import('@/views/Capability/Library/index.vue') },

        // ===== 资产型: 软件库 =====
        // 内部软件的分发入口 —— 任意格式的软件包 (≤5G), 服务端磁盘存储.
        // ⚠️ 独立页面 (不塞进 /market 的 Tab): 软件包是二进制、落服务端磁盘,
        //    跟「插件·技能·连接」(GitLab 里的文本包) 在存储/权限/审核三个维度都不同.
        // ⚠️ lede 是页头**一行**, max-width 600px + nowrap + 省略号 —— 写长了被截掉.
        //    所以只说「放什么 + 拿来干什么」, 不列表单字段 (那是详情页的事).
        { path: 'software', name: 'software', meta: { title: '软件库', lede: '公司内部软件的统一入口 —— 自研工具与基于开源改造的版本都在这儿, 找到就能下, 也能发新版本' }, component: () => import('@/views/Software/index.vue') },

        // ⚠️ **adminOnly** (2026-10-28): 设置页整个只给管理员.
        //    设置项里全是平台级配置 (存储路径 / 仓库地址 / 审核白名单 / 账号管理),
        //    非管理员进来既改不了, 又会看到一堆"看得见摸不着"的只读项 —— 纯干扰.
        //    守卫在这里拦 (不渲染页面), 菜单里也不出现入口 (见 UserMenu.vue).
        { path: 'settings', name: 'settings', meta: { title: '设置', adminOnly: true, lede: '平台配置 · 账号管理 —— 按能力分类组织 (资产 / 工具 / 看板), 改完立刻生效, 不需重启' }, component: () => import('@/views/Settings/index.vue') },
      ],
    },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
  /**
   * 路由切换后的滚动处理.
   *
   * ⚠️ 内部滚动容器是 `.tm-main` (MainLayout 里 `height:100vh; overflow:hidden`),
   *    **不是 window** —— 浏览器原生的 scrollRestoration 只管 window,
   *    恢复不到 .tm-main, 于是新页面直接停在上一个页面的 2000px 处, 首屏是空的.
   *    vue-router 4 没有 scrollBehavior 时**什么都不做**, 所以必须自己接.
   *
   * ⚠️ 同页跳转 (to.path === from.path) 必须返回 false 让位 ——
   *    设置页里点目录会用 scrollIntoView 做同页锚点滚动, 被这里接管就废了.
   *
   * ⚠️ "切页面回到顶部"**不在这里做** (见下面的 afterEach) ——
   *    scrollBehavior 的 el 选项是在**新页面渲染之前**执行的, 那时 .tm-main
   *    还不存在, 实测直接报 "Couldn't find element using selector .tm-main".
   *    这里只留"后退/前进恢复位置"这一件必须靠它的事.
   */
  scrollBehavior: (to, from, savedPosition) => {
    if (to.path === from.path) return false;   // 同页 hash 跳转不接管
    if (savedPosition) return { el: '.tm-main', top: savedPosition.top };
    return false;
  },
});

/**
 * 标签页标题跟着页面走 + 切页面把内部滚动容器复位.
 *
 * ⚠️ 标题以前永远是「TestMate」—— 开几个标签页分不清哪个是哪个.
 *    路由表里每个页面都已有 meta.title (见上面的 routes), 这里拼成
 *    「设置 · TestMate」这种形式; 没有 title 的 (如登录页) 退回裸的 TestMate.
 *
 * ⚠️ 2026-10-31 (第十八轮): 结尾的 **TestMate 改成平台显示名** ——
 *    平台名是设置项 (`general.platform_name`), 管理员改了要跟着变.
 *    ⚠️ 而且名字是**异步**加载的 → 名字到了必须**重算一次**标题,
 *       否则标签页会一直停在旧名字.
 */
function applyDocumentTitle(to: { meta?: Record<string, unknown> }) {
  const t = (to.meta?.title as string | undefined) || '';
  document.title = t ? `${t} · ${platformName.value}` : platformName.value;
}

router.afterEach((to, from) => {
  applyDocumentTitle(to);

  // ⚠️ 切页面 → 把 .tm-main 滚回顶部 (等 DOM 更新完再动, 这时元素必定在).
  //    window 根本不滚, 浏览器原生的 scrollRestoration 只管 window → 管不到这里.
  if (to.path === from.path) return;   // 同页锚点跳转不碰
  nextTick(() => {
    const main = document.querySelector('.tm-main') as HTMLElement | null;
    if (main) main.scrollTop = 0;
  });
});

// ⚠️ 平台名加载完 → 标题重算 (第一次导航时名字可能还没到)
watch(platformName, () => applyDocumentTitle(router.currentRoute.value));

router.beforeEach((to, _from, next) => {
  // publicRead 路由 (首页能力墙 / 代码检视): 匿名也放行, 走完整 MainLayout 布局
  if (to.meta.publicRead) return next();
  const userStore = useUserStore();
  if (to.meta.requiresAuth && !userStore.token) {
    next({ name: 'login', query: { redirect: to.fullPath } });
  } else if (to.meta.adminOnly && !userStore.isAdmin) {
    // ⚠️ 非管理员进设置页 → 踢回工作台 (2026-10-28).
    //    不能只靠"菜单里不显示入口" —— 用户可以手敲 /settings 或者收藏旧书签.
    //    ⚠️ 用 replace 而不是 push —— 免得浏览器后退又回到设置页, 再被踢一次,
    //    用户卡在"后退 → 跳转 → 后退"的死循环里.
    next({ name: 'home', replace: true });
  } else {
    next();
  }
});

export default router;
