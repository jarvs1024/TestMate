<template>
  <header class="tm-header">
    <BrandLogo :size="38" />
    <div class="brand">
      <span class="t1">{{ platformName }}</span>
      <!-- ⚠️ 2026-10-31 (第十八轮): 副标题 + 版本号**从设置项里取** ——
           以前这两样是写死的 ("SSD 测试伙伴" + 后端 APP_VERSION),
           现在管理员在设置页就能改, 改完立刻生效. -->
      <span class="t2">{{ platformTagline }} · v{{ platformVersion }}</span>
    </div>
    <!-- 当前页面标题 (居中显示, 跟左侧 brand 视觉对称) -->
    <div v-if="pageTitle" class="page-title">
      <div class="pt-name">
        <!-- ⚠️ 2026-10-31 (第十五轮): 能力身份条**并进标题行** ——
             原来它在页面内容区第一行, 跟这里的标题**重复**(两边都写"插件·技能·连接"),
             还多占一整行. 现在合成一行: 图标 + 名称 + 版本 + 角色·分类 + 状态徽标. -->
        <span v-if="capIdent" class="pt-icon">{{ capIdent.icon }}</span>
        <span class="pt-txt">{{ pageTitle }}</span>
        <span v-if="capIdent?.version" class="pt-ver">{{ capIdent.version }}</span>
        <template v-if="capIdent">
          <span class="pt-sep">·</span>
          <span class="pt-kind">{{ kindMeta(capIdent.kind).icon }} {{ kindMeta(capIdent.kind).label }}</span>
          <span class="pt-sep">·</span>
          <span class="pt-cat">{{ categoryLabel(capIdent.category) }}</span>
          <span class="pt-badge" :class="`st-${statusTone(capIdent.kind, capIdent.status)}`">
            <span class="dot"></span>{{ statusLabel(capIdent.kind, capIdent.status) }}
          </span>
        </template>
      </div>
      <div v-if="pageLede" class="pt-lede">{{ pageLede }}</div>
    </div>
    <!-- 通用滚动通知栏 (匿名访问 / 系统公告等, 跨页面共享).
         NoticeBar 自己管 dismiss 持久化 (sessionStorage/localStorage, 走 dismissScope),
         这里只需要提供 notices 列表即可, 不必监听 dismiss 事件. -->
    <NoticeBar :notices="notices" class="tm-notice" @navigate="onNoticeNavigate" />
    <div class="right">
      <!-- ⚠️ 2026-10-31 (第十五轮): 页面自己的操作区 (看板的时间窗/刷新等)
           也搬到这里 —— 身份条并进页头后, 页面内容区第一行就空出来了,
           操作区跟着身份走更顺 (都在页头这一行). -->
      <component :is="capActs" v-if="capActs" class="cap-actions" />
      <ThemeSwitcher />
      <UserMenu />
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import BrandLogo from './BrandLogo.vue';
import ThemeSwitcher from './ThemeSwitcher.vue';
import UserMenu from './UserMenu.vue';
import NoticeBar, { type NoticeItem } from './NoticeBar.vue';
import { useUserStore } from '@/stores/user';
import { capActions, capIdentity } from '@/stores/capShell';
import { platformName, platformTagline, platformVersion } from '@/stores/platform';
import { categoryLabel, kindMeta, statusLabel, statusTone } from '@/constants/capabilityKinds';

const route = useRoute();
const pageTitle = computed(() => (route.meta?.title as string) || '');
const pageLede = computed(() => (route.meta?.lede as string) || '');

/**
 * 能力身份条 (2026-10-31 第十五轮) —— 由页面通过 `CapabilityShell` 写进来.
 *
 * ⚠️ 没有身份 (首页 / 设置页 / 登录页等) → 这一行就只显示普通标题, 不多占位.
 */
const capIdent = computed(() => capIdentity.value);
const capActs = computed(() => capActions.value);

/**
 * 平台名称 + 副标题 + 版本号 (2026-10-31 第十八轮).
 *
 * ⚠️ 真源在**设置项**(`general.platform_name` / `general.platform_tagline` /
 *    `general.platform_version`), 管理员在设置页改完立刻生效 —— 不用改代码, 也不用发版.
 *
 * ⚠️ 数据走 `@/stores/platform` 这个共享模块 (页头 / 登录页 / 标签页标题都要用),
 *    加载在 `main.ts` 启动时做一次 —— 这里只读, 不自己发请求.
 */

// 通知数据源 (AppHeader 全局管理, 跨页面共享).
// 当前: 匿名访问提示. 后续要加系统公告 / 实验功能提示, push 到 list 即可.
// dismiss 行为 (sessionStorage 持久 / 关掉后从可见列表移除) 由 NoticeBar 自己管, 不必回调.
const userStore = useUserStore();
const router = useRouter();
/**
 * 匿名用户点通知里的「登录」→ 跳登录页, 并**记住原来在哪**.
 *
 * ⚠️ 以前 redirect 写死成 '/' —— 匿名用户停在 /code-review 时点「登录」,
 *    登录完回**首页**, 不是原来那页.
 *    登录页靠 route.query.redirect 决定跳回哪 (views/Login/index.vue).
 */
const loginHref = computed(() => `/login?redirect=${encodeURIComponent(route.fullPath)}`);

/**
 * 通知栏里的站内链接 → 走 router.push, 不整页刷新.
 *
 * ⚠️ 以前是原生 <a href>, 点一下整页导航 —— SPA 白屏重启, 所有接口重拉.
 */
function onNoticeNavigate(href: string) {
  router.push(href).catch(() => { /* 重复导航等 → 忽略 */ });
}

// 通知数据源 (AppHeader 全局管理, 跨页面共享).
// 当前: 匿名访问提示. 后续要加系统公告 / 实验功能提示, push 到 list 即可.
// dismiss 行为 (sessionStorage 持久 / 关掉后从可见列表移除) 由 NoticeBar 自己管, 不必回调.
const notices = computed<NoticeItem[]>(() => {
  const list: NoticeItem[] = [];
  if (!userStore.token) {
    list.push({
      id: 'anon-readonly',
      type: 'info',
      text: `您正在匿名访问,能力清单可看,进入具体能力需 [登录](${loginHref.value}) 后使用`,
      marquee: true,
      dismissKey: 'cr:anon-notice-dismissed',
      dismissScope: 'session',
      dismissTitle: '本次会话内不再提示 (刷新会重新出现)',
    });
  }
  return list;
});
</script>

<style scoped>
.tm-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 24px;
  background: var(--surface-soft);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.brand { display: flex; flex-direction: column; min-width: 180px; }
.t1 { font-size: 17px; font-weight: 700; color: var(--ink-900); letter-spacing: -0.2px; line-height: 1.2; }
.t2 { font-size: 12.5px; color: var(--ink-500); margin-top: 1px; }

.right { margin-left: auto; display: flex; align-items: center; gap: 8px; }

/* 当前页面标题: 在 brand 之后, 通知栏之前 */
.page-title {
  margin-left: 32px;          /* 跟 brand 留点空 */
  padding-left: 24px;
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}
.pt-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--ink-900);
  line-height: 1.2;
  letter-spacing: -0.2px;
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  flex-wrap: wrap;
}
/* 能力图标 —— 小方块渐变, 跟首页能力墙的卡片图标同一套语言 */
.pt-icon {
  width: 26px; height: 26px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
  box-shadow: var(--primary-shadow);
}
.pt-txt { white-space: nowrap; }
.pt-ver { font-size: 12px; font-weight: 600; color: var(--ink-500); font-family: var(--font-mono); }
.pt-sep { opacity: .4; font-weight: 400; }
/* 角色 (说"这张卡扮演什么") —— 比分类更重要, 跟首页卡片一致 */
.pt-kind { font-size: 12px; color: var(--primary-2); font-weight: 600; white-space: nowrap; }
.pt-cat { font-size: 12px; color: var(--ink-500); font-family: var(--font-mono); white-space: nowrap; }
.pt-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 8px; border-radius: var(--radius-pill);
  font-size: 10.5px; font-weight: 600;
  flex-shrink: 0;
  /* ⚠️ 这里**故意不写** background / color ——
     颜色一律由全局的语义色调类 (.st-ok / .st-warn / .st-muted / .st-danger) 给.
     ⚠️ 原因: scoped 样式编译成 `.pt-badge[data-v-xxx]` (特异度 0,2,0),
        比全局的 `.st-ok` (0,1,0) **高** —— 只要这里还写着 background/color,
        它就会把全局色调**盖掉**, 徽标永远是灰的. */
}
.pt-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
/* ⚠️ 2026-10-31 (第十九轮): 状态徽标的颜色 (.st-ok / .st-warn / .st-muted / .st-danger)
   已提到 **全局** styles/main.css 一份 —— 原来这里跟 CapabilityCard.vue 各抄了一份,
   class 还按**原始 status** 生成 (st-beta / st-stable), 导致「正常」出现两个颜色.
   现在按**语义色调** (statusTone) 生成, 这里不用再定义任何 .st-* 规则. */

/* 页面自己的操作区 (看板的时间窗等) —— 跟着身份条一起进页头 */
.cap-actions { display: inline-flex; align-items: center; gap: 8px; }
.pt-lede {
  font-size: 12px;
  color: var(--ink-500);
  margin-top: 1px;
  line-height: 1.2;
  max-width: 600px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 通知栏 (header 内嵌版): 视觉上跟标题块/主题按钮同处一行, 但权重更轻 ——
   不抢标题戏, 用微染色背景 + 细边框, 文字色走 ink-700 而不是 info 主色,
   让它看起来像 AppHeader 的一部分, 而不是塞进去的卡片.
   padding / height 跟 lede 一行高度对齐. */
.tm-notice {
  margin-left: 18px;
  margin-bottom: 0;
  flex: 1;
  min-width: 0;
  padding: 4px 8px 4px 12px;
  min-height: 28px;
  font-size: 12px;
  border-radius: 14px;
  /* 覆盖 NoticeBar 默认的卡片样式: 微染色 + 细边 + ink-700 文字,
     跟 AppHeader 的中性色更搭 */
  background: color-mix(in srgb, var(--info, var(--primary)) 7%, transparent);
  border: 1px solid color-mix(in srgb, var(--info, var(--primary)) 20%, transparent);
  color: color-mix(in srgb, var(--ink-700) 90%, var(--info, var(--primary)) 10%);
}
/* 通知内部元素轻量化: icon 小一号, ✕ 更隐形, link 不下划线虚线那么突出. */
.tm-notice :deep(.nb-icon) { font-size: 13px; opacity: 0.85; }
.tm-notice :deep(.nb-body) { font-weight: 500; }
.tm-notice :deep(.nb-link) { border-bottom: 1px solid color-mix(in srgb, currentColor 35%, transparent); }
.tm-notice :deep(.nb-link:hover) { border-bottom-color: currentColor; }
.tm-notice :deep(.nb-nav-btn) { width: 20px; height: 20px; font-size: 12px; }
.tm-notice :deep(.nb-count) { min-width: 30px; }
.tm-notice :deep(.nb-close) { padding: 2px 6px; font-size: 12px; opacity: 0.45; }
.tm-notice :deep(.nb-close:hover) { opacity: 0.9; }
</style>
