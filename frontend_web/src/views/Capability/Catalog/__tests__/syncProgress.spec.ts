/**
 * 上架同步进度映射 (2026-11-16).
 *
 * 需求: 点「上架」后同步到 GitLab, 生产环境偏慢 —— 界面要给一条**会动的**
 * 进度条 (乌龟在轨道上慢慢爬), 完成冲线撒花, 失败要能说清原因.
 *
 * 进度分两段:
 *   · 浏览器 → 服务器上传: 真实字节百分比 (0–50)
 *   · staged / syncing / pushed: 按阶段映射, push 阶段用时间缓动 (65→92)
 * 失败分两种, 必须区别对待:
 *   · failed + next_retry_at 有值 → 后端还在自动退避重试, 轮询不能停
 *   · failed + next_retry_at 为空 → 终态失败, 才显示红色与「重试」
 */
import { describe, expect, it } from 'vitest';
import type { AssetJob } from '@/api/assets';
import {
  jobPercent, isAutoRetry, parseSyncError, retrySecondsLeft, uploadPercent,
} from '../syncProgress';

function jobOf(patch: Partial<AssetJob>): AssetJob {
  return {
    id: 1, action: 'create', status: 'staged', code: 'dml-x',
    asset_name: 'x', kind: 'skill', git_path: 'assets/skills/x',
    commit_sha: '', error: '', attempts: 1,
    staged_at: null, pushed_at: null, next_retry_at: null,
    created_at: null, updated_at: null,
    ...patch,
  };
}

describe('上传进度 → 0–50', () => {
  it('按真实字节比例换算, 封顶 50', () => {
    expect(uploadPercent(0, 1000)).toBe(0);
    expect(uploadPercent(500, 1000)).toBe(25);
    expect(uploadPercent(1000, 1000)).toBe(50);
  });

  it('超出/缺失总量时不会越界', () => {
    expect(uploadPercent(1200, 1000)).toBe(50);
    expect(uploadPercent(10, 0)).toBe(0);
    expect(uploadPercent(-5, 100)).toBe(0);
  });
});

describe('任务阶段 → 进度', () => {
  it('staged: 已落盘, 停在 65', () => {
    expect(jobPercent(jobOf({ status: 'staged' }), 0, 0)).toBe(65);
  });

  it('syncing: 随时间缓动上升, 有下限也有 92 封顶', () => {
    const j = jobOf({ status: 'syncing' });
    expect(jobPercent(j, 0, 0)).toBe(65);
    const at10 = jobPercent(j, 10, 65);
    const at60 = jobPercent(j, 60, at10);
    expect(at10).toBeGreaterThan(70);
    expect(at60).toBeGreaterThan(at10);
    expect(at60).toBeLessThanOrEqual(92);
    expect(jobPercent(j, 10_000, 65)).toBe(92);
  });

  it('pushed: 冲线 100', () => {
    expect(jobPercent(jobOf({ status: 'pushed' }), 0, 65)).toBe(100);
  });

  it('failed: 冻结在失败位置, 不会被拉回 65', () => {
    const j = jobOf({ status: 'failed', error: '[network] x' });
    expect(jobPercent(j, 999, 81)).toBe(81);
    expect(jobPercent(j, 999, 0)).toBe(65);   // 没有历史位置时至少显示到 65
  });
});

describe('可恢复失败 (自动重试)', () => {
  it('failed 且有 next_retry_at → 是自动重试, 不能当终态', () => {
    expect(isAutoRetry(jobOf({ status: 'failed', next_retry_at: '2026-11-16T14:00:04Z' }))).toBe(true);
  });

  it('failed 且没有 next_retry_at → 终态失败', () => {
    expect(isAutoRetry(jobOf({ status: 'failed', next_retry_at: null }))).toBe(false);
  });

  it('非 failed 状态即便残留 next_retry_at 也不算自动重试', () => {
    expect(isAutoRetry(jobOf({ status: 'pushed', next_retry_at: '2026-11-16T14:00:04Z' }))).toBe(false);
  });

  it('倒计时按剩余秒数向上取整, 过期归零', () => {
    const now = Date.parse('2026-11-16T14:00:00Z');
    expect(retrySecondsLeft('2026-11-16T14:00:04Z', now)).toBe(4);
    expect(retrySecondsLeft('2026-11-16T14:00:04.400Z', now)).toBe(5);
    expect(retrySecondsLeft('2026-11-16T13:59:59Z', now)).toBe(0);
    expect(retrySecondsLeft(null, now)).toBe(0);
  });
});

describe('失败原因翻译成人话', () => {
  it('解析后端的 [category] 前缀与 hint', () => {
    const f = parseSyncError('[network] 网络异常, 无法连接 GitLab — 检查网线');
    expect(f.category).toBe('network');
    expect(f.reason).toContain('网络');
    expect(f.hint).toBe('检查网线');
  });

  it('常见分类都有中文解释, 不会把 git 原文直接糊到脸上', () => {
    expect(parseSyncError('[auth] SSH 主机密钥校验失败').reason).toContain('认证');
    expect(parseSyncError('[concurrent] 远端有新提交, 本地被拒绝').reason).toContain('并发');
    expect(parseSyncError('[repo] 远端仓库不存在或无访问权限').reason).toContain('仓库');
    expect(parseSyncError('[disk] 磁盘空间不足').reason).toContain('磁盘');
    expect(parseSyncError('[missing] 资产文件在工作区中不存在').reason).toContain('工作区');
    expect(parseSyncError('[internal] 内部错误: KeyError').reason).toContain('内部');
  });

  it('未知分类保留原始信息, 不吞掉', () => {
    const f = parseSyncError('[weird] something odd happened');
    expect(f.category).toBe('weird');
    expect(f.reason).toContain('something odd happened');
  });

  it('没有分类前缀的旧记录也能解析', () => {
    const f = parseSyncError('fatal: unable to access remote');
    expect(f.category).toBe('');
    expect(f.reason).toContain('unable to access remote');
  });
});
