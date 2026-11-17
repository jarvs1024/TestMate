/**
 * 上架同步进度映射 —— 纯函数, 组件只负责画.
 *
 * 进度分两段 (2026-11-16):
 *   0–50   浏览器 → 服务器上传 (真实字节)
 *   50–65  服务端解压 / 落盘 (响应返回即到 65)
 *   65–92  git commit/push (没有真实百分比, 按时间缓动)
 *   100    冲线
 *
 * ⚠️ 失败不能一律当终态: 后端对 lock/network/concurrent 等会退避重试,
 *    那段时间 job.status 也是 failed, 但 next_retry_at 有值 —— 轮询要继续.
 */
import type { AssetJob } from '@/api/assets';

export const UPLOAD_MAX = 50;
export const STAGED_PERCENT = 65;
export const SYNC_CAP = 92;

/** 浏览器上传进度 → 0–50 */
export function uploadPercent(loaded: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0;
  const ratio = Math.max(0, Math.min(1, loaded / total));
  return Math.round(ratio * UPLOAD_MAX);
}

/**
 * 任务阶段 → 进度.
 *
 * @param elapsedSec 进入 syncing 后的秒数 (缓动用)
 * @param lastPercent 失败时冻结的位置 (调用方传上一次的进度)
 */
export function jobPercent(job: AssetJob, elapsedSec: number, lastPercent: number): number {
  switch (job.status) {
    case 'pushed':
      return 100;
    case 'failed':
      return Math.max(STAGED_PERCENT, Math.min(SYNC_CAP, Math.round(lastPercent || STAGED_PERCENT)));
    case 'syncing': {
      const t = Math.max(0, elapsedSec);
      const creep = STAGED_PERCENT + (SYNC_CAP - STAGED_PERCENT) * (1 - Math.exp(-t / 25));
      return Math.min(SYNC_CAP, Math.round(creep));
    }
    default:
      // pending / staged —— 已落盘, 等后台
      return STAGED_PERCENT;
  }
}

/** failed 但后端排了下次重试 → 自动恢复中, 不是终态 */
export function isAutoRetry(job: AssetJob): boolean {
  return job.status === 'failed' && !!job.next_retry_at;
}

/** 距离下次自动重试还有几秒 (向上取整, 过期归零) */
export function retrySecondsLeft(nextRetryAt: string | null, now = Date.now()): number {
  if (!nextRetryAt) return 0;
  const at = Date.parse(nextRetryAt);
  if (!Number.isFinite(at)) return 0;
  return Math.max(0, Math.ceil((at - now) / 1000));
}

const REASON_BY_CATEGORY: Record<string, string> = {
  network: '网络中断或 GitLab 不可达',
  lock: 'Git 仓库正被其他操作占用',
  concurrent: '远端刚有新提交，发生并发冲突',
  commit: '没有检测到需要提交的变更',
  repo: 'GitLab 仓库不可访问（分支或仓库配置有问题）',
  auth: 'GitLab 认证失败（SSH 公钥未被接受）',
  disk: '服务端磁盘空间或目录权限不足',
  missing: '服务端工作区里找不到该资产文件',
  internal: '服务端内部错误',
};

export interface SyncFailure {
  category: string;
  /** 给人看的一句话原因 */
  reason: string;
  /** 后端附带的处理建议 */
  hint: string;
}

/** `[category] message — hint` → 中文原因 + 建议 */
export function parseSyncError(error: string): SyncFailure {
  const raw = (error || '').trim();
  const m = raw.match(/^\[([a-z]+)\]\s*([\s\S]*)$/i);
  const category = (m?.[1] || '').toLowerCase();
  const body = m ? (m[2] || '').trim() : raw;
  const [message, hint = ''] = body.split(/\s+—\s+/, 2);
  return {
    category,
    reason: REASON_BY_CATEGORY[category] || message || '未知错误',
    hint: hint.trim(),
  };
}
