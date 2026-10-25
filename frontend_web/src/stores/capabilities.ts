/**
 * 能力 store —— 首页能力墙与侧栏导航器**共用同一份数据**.
 *
 * 为什么要有这个 store (2026-10-25):
 *   首页网格和侧栏导航器展示的是同一批能力, 如果各自拉一次接口,
 *   就会出现"侧栏有、首页没有"的不一致 —— 这是老架构 (广场 / 知识库平级分区)
 *   最容易冒出来的割裂感. 现在两边都读这个 store, 拉一次就够.
 */
import { defineStore } from 'pinia';
import { listCapabilities, type Capability } from '@/api/capabilities';
import { CAPABILITY_KINDS, type CapabilityKind } from '@/constants/capabilityKinds';

export const useCapabilityStore = defineStore('capabilities', {
  state: () => ({
    items: [] as Capability[],
    loading: false,
    /** 已经拉过 —— 避免首页和侧栏各打一次接口 */
    loaded: false,
    error: '' as string,
  }),
  getters: {
    /** 平台上的全部能力 (后端已过滤掉 deprecated) */
    all: (s) => s.items,

    /**
     * 按形态分组 —— 侧栏导航器直接用.
     * 顺序跟 CAPABILITY_KINDS 一致, 空形态不占位.
     */
    grouped: (s) => {
      return CAPABILITY_KINDS
        .map((meta) => ({
          meta,
          items: s.items.filter((c) => c.kind === meta.value),
        }))
        .filter((g) => g.items.length > 0);
    },

    /** 每个形态有几项 (首页筛选 chips 上的计数) */
    countByKind: (s) => {
      const map: Record<string, number> = { all: s.items.length };
      for (const k of CAPABILITY_KINDS) map[k.value] = 0;
      for (const c of s.items) map[c.kind] = (map[c.kind] || 0) + 1;
      return map;
    },

    /** 按 code 找一项能力 */
    byCode: (s) => (code: string) => s.items.find((c) => c.code === code),
  },
  actions: {
    /**
     * 拉能力列表.
     * @param force 强制重新拉 (默认复用已有数据)
     *
     * ⚠️ 失败**不抛异常**: 首页要能降级成"空墙"而不是白屏 ——
     *    匿名用户打这个接口失败时尤其不能炸.
     */
    async load(force = false) {
      if (this.loaded && !force) return;
      if (this.loading) return;
      this.loading = true;
      this.error = '';
      try {
        const data = await listCapabilities();
        this.items = data.items || [];
        this.loaded = true;
      } catch (e: any) {
        this.error = e?.message || '能力列表加载失败';
        this.items = [];
      } finally {
        this.loading = false;
      }
    },
  },
});

export type { CapabilityKind };
