/**
 * **能力身份条**的跨组件传递 (2026-10-31 · 第十五轮).
 *
 * ⚠️ 为什么需要这个模块:
 *   身份条 (图标 / 名称 / 版本 / 角色·分类 / 状态徽标) 原来由 `CapabilityShell`
 *   渲染在**页面内容区**的第一行 —— 于是页头 (AppHeader) 已经有标题+lede,
 *   下面又来一条"插件·技能·连接 v0.1.0 …", **同一句话说两遍**,
 *   而且多占掉一整行 (~50px). 用户要求: 把它**并进页头**, 去掉「返回工作台」按钮.
 *
 *   但页头是全局的 (MainLayout 里), 身份信息是**每个页面自己的**
 *   (工具页的名字/图标还是接口异步取回来的) —— 父组件没法直接往子组件传 props,
 *   所以需要一个"页面写、页头读"的通道.
 *
 * ⚠️ 为什么**不用 pinia**:
 *   这是个一次性的跨组件通道, 没有任何持久化/派生状态的需求.
 *   用 pinia 的话, 所有 mount 组件的单测都得先 `createPinia()` ——
 *   而 CapabilityShell 被四个页面用着, 等于给几十个测试文件加样板代码
 *   (实测: 直接上 pinia 炸了 104 条用例).
 *   普通模块级响应式对象就够 —— Vue 的响应式不依赖 pinia.
 *
 * ⚠️ 为什么 actions 存的是**组件**而不是数据:
 *   看板页的操作区 (时间窗下拉 + 刷新时间) 是模板片段, 不是几个字段能表达的.
 *   `CapabilityShell` 把插槽内容包成一个小组件交出来, 页头用
 *   `<component :is>` 渲染它 —— 这样页面**一行模板都不用改**.
 */
import { markRaw, reactive, shallowRef, type Component } from 'vue';

export interface CapIdentity {
  /** 图标 (emoji) */
  icon: string;
  /** 能力名 (跟页头标题一般是同一个, 但工具页是动态的) */
  name: string;
  /** 版本号 (如 v0.1.0) */
  version?: string;
  /** 角色 (asset / tool / board / platform) */
  kind: string;
  /** 业务域 */
  category?: string;
  /** 状态 (draft / alpha / beta / stable / deprecated) */
  status: string;
}

/** 身份信息 —— null = 这个页面没有身份条 (首页 / 设置页等) */
export const capIdentity = reactive<{ value: CapIdentity | null }>({ value: null });

/**
 * 页面自己的操作区 (看板的时间窗等) —— **组件**, 不是数据.
 *
 * ⚠️ 用 shallowRef: 组件对象放 reactive 里会被深度代理, Vue 会警告
 *    "Vue received a Component which was made a reactive object".
 */
export const capActions = shallowRef<Component | null>(null);

export function setCapIdentity(id: CapIdentity | null) {
  capIdentity.value = id;
}

export function setCapActions(c: Component | null) {
  capActions.value = c ? markRaw(c) : null;
}

/** 页面卸载时清干净 —— 不然下次进别的页面还挂着上一个的身份 */
export function clearCapShell() {
  capIdentity.value = null;
  capActions.value = null;
}
