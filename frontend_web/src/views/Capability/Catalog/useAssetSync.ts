/**
 * 上架同步状态机 (2026-11-16) —— 从 AssetUploadDialog 抽出来, 便于单测.
 *
 * 状态:
 *   uploading → saving → syncing → done
 *                    ↘ auto-retry ↗   (可恢复失败, 轮询继续)
 *                    ↘ failed         (终态, 停轮询)
 */
import { computed, ref } from 'vue';
import type { AssetItem, AssetJob } from '@/api/assets';
import {
  STAGED_PERCENT, isAutoRetry, jobPercent, parseSyncError,
  retrySecondsLeft, uploadPercent,
} from './syncProgress';

export type SyncReview = 'checking' | 'pending' | 'published';

export interface SyncView {
  phase: 'uploading' | 'saving' | 'syncing' | 'auto-retry' | 'done' | 'failed';
  percent: number;
  title: string;
  sub?: string;
  /** 成功态印章文案, 大写英文 (SUCCESS / SUBMITTED / SYNCED) */
  stamp?: string;
  reason?: string;
  hint?: string;
  detail?: string;
  /** 失败时: 内容是否**已经落盘** —— 决定"资产不会丢"那句提示能不能说 */
  savedOnServer?: boolean;
}

export interface UseAssetSyncOptions {
  isOpen: () => boolean;
  fetchJob: (id: number) => Promise<AssetJob>;
  fetchAsset: (code: string) => Promise<Pick<AssetItem, 'publish_status'>>;
  requestRetry: (id: number) => Promise<AssetJob>;
  onDone: (job: AssetJob, review: Exclude<SyncReview, 'checking'>) => void;
  onTerminalFailure: (job: AssetJob) => void;
  intervalMs?: number;
  maxPolls?: number;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

function formatBytes(n: number): string {
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function useAssetSync(opts: UseAssetSyncOptions) {
  const intervalMs = opts.intervalMs ?? 1000;
  // push 超时是 180s, 再多留一点余量 —— 以前 90s 就静默放弃, 生产慢的时候会"看着卡住"
  const maxPolls = opts.maxPolls ?? 240;
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const now = opts.now ?? (() => Date.now());

  const job = ref<AssetJob | null>(null);
  const submitting = ref(false);
  const uploadPct = ref(0);
  const uploadText = ref('');
  const uploadError = ref('');
  const lastPercent = ref(0);
  const reviewState = ref<SyncReview>('checking');
  const nowTick = ref(0);
  const syncStartedAt = ref(0);

  const elapsedSec = computed(() => {
    if (!syncStartedAt.value) return 0;
    return Math.max(0, Math.round((nowTick.value - syncStartedAt.value) / 1000));
  });

  function percentAt(elapsed: number): number {
    if (!job.value) return STAGED_PERCENT;
    return jobPercent(job.value, elapsed, lastPercent.value);
  }

  function applyJob(j: AssetJob) {
    nowTick.value = now();
    job.value = j;
    if (j.status === 'syncing') {
      if (!syncStartedAt.value) syncStartedAt.value = nowTick.value;
      lastPercent.value = Math.max(lastPercent.value, jobPercent(j, elapsedSec.value, lastPercent.value));
    } else if (j.status === 'pushed') {
      lastPercent.value = 100;
    } else if (j.status === 'staged' || j.status === 'pending') {
      lastPercent.value = Math.max(lastPercent.value, STAGED_PERCENT);
    }
  }

  const syncView = computed<SyncView>(() => {
    if (uploadError.value) {
      return {
        phase: 'failed', percent: lastPercent.value,
        // 请求层面就失败 (409 重名 / 网络中断) —— 服务端什么都没存
        savedOnServer: false,
        title: '上传失败', reason: uploadError.value, detail: '',
      };
    }
    const j = job.value;
    if (!j) {
      return {
        phase: 'uploading', percent: uploadPct.value,
        title: '正在上传安装包…',
        sub: uploadText.value || '正在建立连接…',
      };
    }
    if (j.status === 'pending' || j.status === 'staged') {
      return {
        phase: 'saving', percent: percentAt(elapsedSec.value),
        title: '已保存到服务端，准备同步…',
        sub: '后台队列正在处理，稍后自动推送到 GitLab',
      };
    }
    if (j.status === 'syncing') {
      return {
        phase: 'syncing', percent: percentAt(elapsedSec.value),
        title: '正在推送到 GitLab…',
        sub: `已用 ${elapsedSec.value}s`,
      };
    }
    if (j.status === 'failed' && isAutoRetry(j)) {
      const left = retrySecondsLeft(j.next_retry_at, now());
      return {
        phase: 'auto-retry', percent: lastPercent.value,
        title: '遇到临时问题，正在自动重试',
        sub: `已试 ${j.attempts} 次${left ? ` · ${left}s 后继续` : ' · 马上继续'}`,
      };
    }
    if (j.status === 'failed') {
      const f = parseSyncError(j.error);
      return {
        phase: 'failed', percent: lastPercent.value,
        // 走到这里说明已 staged 落盘, 只是推 GitLab 失败 —— 内容不会丢
        savedOnServer: true,
        title: '推送 GitLab 失败', reason: f.reason, hint: f.hint, detail: j.error,
      };
    }
    // pushed
    const pending = reviewState.value === 'pending';
    const checking = reviewState.value === 'checking';
    return {
      phase: 'done', percent: 100,
      title: checking ? '同步完成，正在确认上架状态…'
        : pending ? '已提交，等待管理员审核' : '已同步到 GitLab',
      // 印章统一用大写英文 (橡胶章风格); 中文说明看上面的标题
      stamp: checking ? 'SYNCED' : pending ? 'SUBMITTED' : 'SUCCESS',
    };
  });

  function beginUpload() {
    submitting.value = true;
    uploadPct.value = 0;
    uploadText.value = '';
    uploadError.value = '';
    lastPercent.value = 0;
    syncStartedAt.value = 0;
    nowTick.value = now();
    reviewState.value = 'checking';
  }

  function noteUploadProgress(loaded: number, total: number) {
    uploadPct.value = uploadPercent(loaded, total);
    if (total > 0) uploadText.value = `${formatBytes(loaded)} / ${formatBytes(total)}`;
  }

  function failUpload(message: string) {
    uploadError.value = message;
    submitting.value = false;
    lastPercent.value = Math.max(lastPercent.value, uploadPct.value);
  }

  function clearUploadFailure() {
    uploadError.value = '';
    uploadPct.value = 0;
    uploadText.value = '';
    lastPercent.value = 0;
    submitting.value = false;
  }

  async function poll(id: number) {
    if (!opts.isOpen()) {
      submitting.value = false;
      return;
    }
    for (let i = 0; i < maxPolls; i++) {
      await sleep(intervalMs);
      if (!opts.isOpen()) {
        submitting.value = false;
        return;
      }
      let j: AssetJob;
      try {
        j = await opts.fetchJob(id);
      } catch {
        continue;
      }
      if (!opts.isOpen()) {
        submitting.value = false;
        return;
      }
      applyJob(j);

      if (j.status === 'pushed') {
        reviewState.value = 'checking';
        try {
          const a = await opts.fetchAsset(j.code);
          reviewState.value = a.publish_status === 'pending' ? 'pending' : 'published';
        } catch {
          reviewState.value = 'published';
        }
        submitting.value = false;
        opts.onDone(j, reviewState.value as Exclude<SyncReview, 'checking'>);
        return;
      }
      if (j.status === 'failed' && !isAutoRetry(j)) {
        submitting.value = false;
        opts.onTerminalFailure(j);
        return;
      }
      // failed + next_retry_at → 后端还在自动重试, 继续等
    }
    submitting.value = false;
  }

  async function acceptJob(created: AssetJob) {
    applyJob(created);
    await poll(created.id);
  }

  async function doRetry(current: AssetJob) {
    submitting.value = true;
    const j = await opts.requestRetry(current.id);
    syncStartedAt.value = 0;
    lastPercent.value = STAGED_PERCENT;
    applyJob(j);
    await poll(j.id);
  }

  function reset() {
    job.value = null;
    submitting.value = false;
    uploadPct.value = 0;
    uploadText.value = '';
    uploadError.value = '';
    lastPercent.value = 0;
    reviewState.value = 'checking';
    nowTick.value = 0;
    syncStartedAt.value = 0;
  }

  return {
    job, submitting, uploadPct, uploadError, reviewState, elapsedSec,
    syncView, percentAt, applyJob,
    beginUpload, noteUploadProgress, failUpload, clearUploadFailure,
    acceptJob, doRetry, reset,
  };
}
