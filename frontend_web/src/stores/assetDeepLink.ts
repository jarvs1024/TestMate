/** 资产深链的「再打开一次」信号.
 *
 * 深链本身靠路由 query (?asset=&comment=) 传: 首次进入 / 刷新 / 分享都够用.
 * 但用户已经停在这条深链上时 (关掉抽屉后再点同一条通知),
 * push 属于同地址导航 —— 路由不动, query watch 也不会触发.
 * 这里用递增序号把「再打开一次」的意图送给扩展库.
 */
import { defineStore } from 'pinia';

export const useAssetDeepLinkStore = defineStore('assetDeepLink', {
  state: () => ({
    asset: '',
    comment: null as number | null,
    seq: 0,
  }),
  actions: {
    open(asset: string, comment?: number | null) {
      this.asset = asset;
      this.comment = comment ?? null;
      this.seq += 1;
    },
  },
});
