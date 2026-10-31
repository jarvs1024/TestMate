<template>
  <!--
    ⚠️ 2026-10-31 (第十五轮): 这个组件**不再渲染任何东西**.

    原来它渲染的是页面内容区第一行的"身份条"
    (← 返回工作台 | 图标 | 名称 v版本 | 角色 · 分类 | 状态徽标),
    跟页头 (AppHeader) 的标题**重复**, 还多占一整行.

    现在身份信息**并进页头** —— 本组件只负责把数据交给 `useCapShellStore`,
    由 AppHeader 统一渲染. 页面**不用改模板**, 只是外壳换了个位置.

    留一个 0 尺寸的锚点: ① DOM 里还能看出"这个页面声明过身份";
    ② 现有单测 (断言 `<CapabilityShell` 在) 不用改.
  -->
  <span class="cap-shell-anchor" aria-hidden="true" />
</template>

<script setup lang="ts">
/**
 * 能力身份条的**数据出口** (2026-10-31 第十五轮 · 原来的渲染组件).
 *
 * ⚠️ 为什么不直接把 props 塞进 route.meta:
 *   工具页 (ToolRunner) 的 name/icon/kind/status 是**接口异步取回来的**,
 *   路由 meta 是静态的 —— 塞不进去.
 *
 * ⚠️ 为什么不直接删掉这个组件、让页面自己写 store:
 *   四个页面各写一遍 `store.set({...})` + 清理逻辑, 容易漏 (ToolRunner 还是
 *   `v-if="agent"` 条件挂载的). 组件在这里**统一兜住**挂载/卸载的时机.
 *
 * ⚠️ actions 插槽 (看板的时间窗下拉 + 刷新时间) 也一起交给页头 ——
 *   页头右侧本来就有主题/用户区, 操作放那儿比挤在内容区更顺.
 */
import { defineComponent, markRaw, onUnmounted, watchEffect } from 'vue';
import { clearCapShell, setCapActions, setCapIdentity } from '@/stores/capShell';

const props = withDefaults(defineProps<{
  name: string;
  icon: string;
  kind: string;
  status: string;
  version?: string;
  /** 业务域标签 (跟角色正交) */
  category?: string;
}>(), {
  version: '',
  category: '',
});

const slots = defineSlots<{ actions?: () => unknown }>();

// 身份信息 → 页头
watchEffect(() => {
  setCapIdentity({
    icon: props.icon,
    name: props.name,
    version: props.version,
    kind: props.kind,
    category: props.category,
    status: props.status,
  });
});

// 页面自己的操作区 → 页头右侧
// ⚠️ 插槽内容只能渲染在**声明它的组件树里**, 所以包成一个小组件交出去,
//    由页头 <component :is> 渲染 —— 页面模板不用动.
const ActionsHost = markRaw(defineComponent({
  name: 'CapShellActionsHost',
  setup() {
    return () => (slots.actions ? slots.actions() : null);
  },
}));

watchEffect(() => {
  setCapActions(slots.actions ? ActionsHost : null);
});

// 页面卸载 → 清干净 (不然下次进别的页面还挂着上一个的身份)
onUnmounted(() => clearCapShell());
</script>

<style scoped>
.cap-shell-anchor { display: none; }
</style>
