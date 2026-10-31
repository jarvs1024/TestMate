/**
 * 平台信息 (名称 / 副标题 / 版本号) —— **设置项驱动**, 不是写死的.
 *
 * ⚠️ 为什么单独一个模块 (2026-10-31 第十八轮):
 *    这三样要在**四个地方**显示, 每一处都自己发一次请求会很难看:
 *      · 页头 (AppHeader)
 *      · 登录页 (Login)
 *      · 浏览器标签页标题 (router 的 afterEach)
 *      · 兜底默认值 (各处组件的初始值)
 *    所以: 一个模块级响应式对象 + 一个 `loadPlatformInfo()`, 谁要用谁读它.
 *
 * ⚠️ **没用 pinia** —— 跟 `stores/capShell.ts` 一个道理:
 *    这是个一次性的全局数据通道, 没有持久化/派生状态需求;
 *    用 pinia 的话所有 mount 组件的单测都得先 `createPinia()`.
 *
 * ⚠️ 平台名以前是**前端写死**的 "TestMate" —— 而设置项 `general.platform_name`
 *    早就存在(描述写着"顶栏 + 标题"), 管理员改了不生效(形同虚设).
 *    现在这一层接上了.
 */
import { ref } from 'vue';

/** 平台显示名 (general.platform_name) —— 页头 / 登录页 / 标签页标题都用它 */
export const platformName = ref('TestMate');
/** 平台版本号 (general.platform_version) —— 显示时前面加 "v" */
export const platformVersion = ref('1.0.0');
/** 平台副标题 (general.platform_tagline) */
export const platformTagline = ref('智能测试辅助平台');

/**
 * 加载平台信息 —— **整个会话只加载一次**.
 *
 * ⚠️ 加载失败**不抛** —— 各处保留兜底默认值 (页头不能因为接口挂了就空白).
 * ⚠️ 失败也**不再重试** —— 这个接口挂掉通常是后端整体挂了,
 *    刷页面自然会重来, 没必要在前端死磕.
 */
let loading: Promise<void> | null = null;

export function loadPlatformInfo(): Promise<void> {
  if (!loading) {
    loading = (async () => {
      try {
        // ⚠️ **动态导入**: 单测里有一堆 `vi.mock('@/api/settings', factory)`,
        //    那些工厂不一定带 getPlatformInfo —— 静态导入会在**模块初始化**时
        //    就炸 ("does not provide an export named ..."), 连带一堆无关用例挂掉.
        //    动态导入把这件事推迟到"真的要取数据"的时候.
        const { getPlatformInfo } = await import('@/api/settings');
        const info = await getPlatformInfo();
        if (info.name) platformName.value = info.name;
        if (info.version) platformVersion.value = info.version;
        if (info.tagline) platformTagline.value = info.tagline;
      } catch {
        /* 保留兜底默认值 */
      }
    })();
  }
  return loading;
}
