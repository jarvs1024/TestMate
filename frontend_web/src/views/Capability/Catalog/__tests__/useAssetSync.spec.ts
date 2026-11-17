/**
 * 上架同步状态机 (2026-11-16).
 *
 * 要点:
 *   · 上传阶段用真实字节进度; 落盘/推送阶段按阶段映射
 *   · failed + next_retry_at → 后端还在自动重试, 轮询必须继续
 *   · failed 终态才停轮询、显示失败卡片
 *   · 关掉抽屉 = 停轮询, 不再在别的页面弹提示
 */
import { describe, expect, it, vi } from 'vitest';
import type { AssetJob } from '@/api/assets';
import { useAssetSync } from '../useAssetSync';

function jobOf(patch: Partial<AssetJob>): AssetJob {
  return {
    id: 7, action: 'create', status: 'staged', code: 'dml-x',
    asset_name: 'x', kind: 'skill', git_path: 'assets/skills/x',
    commit_sha: '', error: '', attempts: 1,
    staged_at: null, pushed_at: null, next_retry_at: null,
    created_at: null, updated_at: null,
    ...patch,
  };
}

function setup(opts: {
  jobs?: AssetJob[];
  publishStatus?: 'pending' | 'rejected' | 'published';
  editingMeta?: boolean;
  open?: () => boolean;
  retryJob?: AssetJob;
} = {}) {
  const queue = [...(opts.jobs || [])];
  const fetchJob = vi.fn(async () => {
    if (!queue.length) throw new Error('no more jobs');
    return queue.shift()!;
  });
  const fetchAsset = vi.fn(async () => ({ publish_status: opts.publishStatus || 'published' }));
  const requestRetry = vi.fn(async () => opts.retryJob || jobOf({ status: 'staged' }));
  const onDone = vi.fn();
  const onTerminalFailure = vi.fn();
  const isOpen = opts.open || (() => true);
  const sync = useAssetSync({
    isOpen, fetchJob, fetchAsset, requestRetry, onDone, onTerminalFailure,
    editingMeta: () => !!opts.editingMeta,
    sleep: async () => {},
    now: () => 0,
  });
  return { sync, fetchJob, fetchAsset, requestRetry, onDone, onTerminalFailure, isOpen };
}

describe('上传阶段', () => {
  it('真实字节进度落在 0–50, 文案带已传大小', () => {
    const { sync } = setup();
    sync.beginUpload();
    sync.noteUploadProgress(512 * 1024, 1024 * 1024);
    expect(sync.syncView.value.phase).toBe('uploading');
    expect(sync.syncView.value.percent).toBe(25);
    expect(sync.syncView.value.sub).toContain('MB');
    expect(sync.submitting.value).toBe(true);
  });

  it('上传请求失败 → 冻结在当前位置, 可回表单', () => {
    const { sync } = setup();
    sync.beginUpload();
    sync.noteUploadProgress(1024, 4096);
    sync.failUpload('网络中断');

    expect(sync.syncView.value.phase).toBe('failed');
    expect(sync.syncView.value.title).toContain('上传失败');
    expect(sync.syncView.value.reason).toBe('网络中断');
    expect(sync.syncView.value.percent).toBe(13);
    // ⚠️ 请求都没成功, 什么都没落盘 —— 不能显示"已保存在服务端工作区"
    expect(sync.syncView.value.savedOnServer).toBe(false);
    expect(sync.submitting.value).toBe(false);

    sync.clearUploadFailure();
    expect(sync.syncView.value.phase).toBe('uploading');
    expect(sync.syncView.value.percent).toBe(0);
  });
});

describe('任务阶段', () => {
  it('staged 停在 65, pushed 冲线 100', async () => {
    const { sync, fetchAsset, onDone } = setup({ jobs: [jobOf({ status: 'pushed' })] });
    sync.beginUpload();
    await sync.acceptJob(jobOf({ status: 'staged' }));
    expect(sync.syncView.value.phase).toBe('done');
    expect(sync.syncView.value.percent).toBe(100);
    expect(sync.syncView.value.stamp).toBe('SUCCESS');
    expect(fetchAsset).toHaveBeenCalledWith('dml-x');
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ status: 'pushed' }), 'published');
  });

  it('待审资产: 印章改成大写 SUBMITTED, 标题说清等待审核', async () => {
    const { sync } = setup({ jobs: [jobOf({ status: 'pushed' })], publishStatus: 'pending' });
    sync.beginUpload();
    await sync.acceptJob(jobOf({ status: 'staged' }));
    expect(sync.syncView.value.stamp).toBe('SUBMITTED');
    expect(sync.syncView.value.title).toContain('等待管理员审核');
  });

  it('编辑信息: 在架资产与管理员直改一致 (SUCCESS)', async () => {
    const { sync, onDone } = setup({
      jobs: [jobOf({ status: 'pushed' })], publishStatus: 'published', editingMeta: true,
    });
    sync.beginUpload();
    await sync.acceptJob(jobOf({ status: 'staged' }));
    expect(sync.syncView.value.stamp).toBe('SUCCESS');
    expect(sync.syncView.value.title).toBe('已同步到 GitLab');
    expect(onDone).toHaveBeenCalledWith(expect.anything(), 'published');
  });

  it('编辑信息: 待审资产只保存资料, 不说成"重新提交"', async () => {
    const { sync } = setup({
      jobs: [jobOf({ status: 'pushed' })], publishStatus: 'pending', editingMeta: true,
    });
    sync.beginUpload();
    await sync.acceptJob(jobOf({ status: 'staged' }));
    expect(sync.syncView.value.stamp).toBe('SAVED');
    expect(sync.syncView.value.title).toContain('修改已保存');
    expect(sync.syncView.value.title).not.toContain('已提交');
  });

  it('编辑信息: 驳回资产内容只在暂存区, 不能再谎报已同步 GitLab', async () => {
    const { sync, onDone } = setup({
      jobs: [jobOf({ status: 'pushed' })], publishStatus: 'rejected', editingMeta: true,
    });
    sync.beginUpload();
    await sync.acceptJob(jobOf({ status: 'staged' }));
    expect(sync.syncView.value.stamp).toBe('SAVED');
    expect(sync.syncView.value.title).toContain('驳回');
    expect(sync.syncView.value.title).not.toContain('GitLab');
    expect(onDone).toHaveBeenCalledWith(expect.anything(), 'rejected');
  });

  it('syncing 随时间缓动, 但封顶 92', () => {
    const { sync } = setup();
    sync.applyJob(jobOf({ status: 'syncing' }));
    expect(sync.syncView.value.percent).toBe(65);
    sync.applyJob(jobOf({ status: 'syncing' }));
    expect(sync.syncView.value.percent).toBe(65);
    // 注入一个大时间跨度 (绕过轮询) —— 直接验证封顶
    expect(sync.percentAt(10_000)).toBe(92);
  });
});

describe('失败分支', () => {
  it('可恢复失败: 轮询继续, 最终成功后回调 onDone', async () => {
    const { sync, fetchJob, onDone, onTerminalFailure } = setup({
      jobs: [
        jobOf({ status: 'failed', next_retry_at: new Date(Date.now() + 4000).toISOString(), error: '[network] x' }),
        jobOf({ status: 'syncing' }),
        jobOf({ status: 'pushed' }),
      ],
    });
    sync.beginUpload();
    await sync.acceptJob(jobOf({ status: 'staged' }));
    expect(fetchJob.mock.calls.length).toBe(3);
    expect(onTerminalFailure).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('终态失败: 立即停轮询, 给出人话原因与原始详情', async () => {
    const { sync, fetchJob, onDone, onTerminalFailure } = setup({
      jobs: [jobOf({
        status: 'failed', attempts: 3,
        error: '[auth] SSH 认证失败 (公钥未被接受) — 确认公钥已添加到 GitLab',
      })],
    });
    sync.beginUpload();
    await sync.acceptJob(jobOf({ status: 'staged' }));

    const view = sync.syncView.value;
    expect(fetchJob).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
    expect(onTerminalFailure).toHaveBeenCalledTimes(1);
    expect(view.phase).toBe('failed');
    expect(view.title).toContain('失败');
    expect(view.reason).toContain('认证');
    expect(view.hint).toContain('公钥');
    expect(view.detail).toContain('SSH 认证失败');
    // 已落盘再同步失败 —— 这时候"资产不会丢"才是真的
    expect(view.savedOnServer).toBe(true);
  });

  it('关掉抽屉 → 轮询立刻停, 不发任何回调', async () => {
    let open = true;
    const { sync, fetchJob, onDone } = setup({
      jobs: [jobOf({ status: 'pushed' })],
      open: () => open,
    });
    open = false;
    sync.beginUpload();
    await sync.acceptJob(jobOf({ status: 'staged' }));
    expect(fetchJob).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
  });
});

describe('重试', () => {
  it('终态失败后重试: 先请后端重新入队, 再重新轮询到成功', async () => {
    const { sync, requestRetry, onDone } = setup({
      jobs: [jobOf({ status: 'failed', error: '[network] x' }), jobOf({ status: 'pushed' })],
      retryJob: jobOf({ status: 'staged' }),
    });
    sync.beginUpload();
    await sync.acceptJob(jobOf({ status: 'staged' }));
    expect(sync.syncView.value.phase).toBe('failed');
    expect(sync.submitting.value).toBe(false);

    await sync.doRetry(sync.job.value!);
    expect(requestRetry).toHaveBeenCalledWith(7);
    expect(sync.syncView.value.phase).toBe('done');
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
