/** 站内通知的全局状态 —— 未读数 + 轮询.
 *
 * 轮询口径: 60s 一次, 页面隐藏时跳过 (切回来由 visibilitychange 补一次);
 * 拉取失败静默 —— 消息提醒不该用红条打断用户正在做的事.
 */
import { defineStore } from 'pinia';
import { getUnreadCount } from '@/api/notifications';

const POLL_MS = 60_000;

export const useNotificationsStore = defineStore('notifications', {
  state: () => ({
    unread: 0,
    _timer: null as ReturnType<typeof setInterval> | null,
    _onVisible: null as (() => void) | null,
  }),
  actions: {
    async refreshUnread() {
      try {
        const r = await getUnreadCount();
        this.unread = r.count || 0;
      } catch {
        // 静默: 断网 / 401 时保留上一次数字, 下次轮询再试
      }
    },
    startPolling() {
      if (this._timer) return;
      const tick = () => {
        if (!document.hidden) void this.refreshUnread();
      };
      void this.refreshUnread();
      this._timer = setInterval(tick, POLL_MS);
      this._onVisible = tick;
      document.addEventListener('visibilitychange', tick);
    },
    stopPolling() {
      if (this._timer) {
        clearInterval(this._timer);
        this._timer = null;
      }
      if (this._onVisible) {
        document.removeEventListener('visibilitychange', this._onVisible);
        this._onVisible = null;
      }
    },
  },
});
