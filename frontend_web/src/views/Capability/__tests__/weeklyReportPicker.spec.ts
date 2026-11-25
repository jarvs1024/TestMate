/**
 * 周报卡 (图1) + 周报抽屉 (图2) 的回归测试 (2026-11-25).
 *
 * 两个需求:
 *   ① 图1 支持选择每周的数据 —— 之前只有最新一份, 历史周报选不了
 *   ② 图2 成功率不要把跳过的算失败 —— 跳过算成功
 *
 * Why 用源码断言而不是 mount: BoardView.vue 有 1000+ 行 + 一堆全局 API 依赖,
 * mount 成本高且脆; 这里关心的两件事都是**纯逻辑/结构**问题,
 * 源码断言能直接钉住, 且失败信息更准.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const BOARD = resolve(process.cwd(), 'src/views/Capability/BoardView.vue');
const src = readFileSync(BOARD, 'utf8');

describe('周报卡 · 支持选择每周的数据', () => {
  it('拉全量周报列表 (不只是最新一份)', () => {
    // 之前 refreshWrLatest 只取 list[0] (limit=1) → 历史周报根本拿不到
    expect(src).toContain('getWeeklyReports(52');
    expect(src).toContain('const wrList = ref<WeeklyReportListItem[]>([])');
  });

  it('抽屉里有周选择器', () => {
    expect(src).toContain('class="wr-week-sel"');
    expect(src).toContain('v-for="w in wrList"');
    expect(src).toContain('@change="selectWeeklyReport');
  });

  it('切换周会重新拉那一份周报', () => {
    expect(src).toContain('async function selectWeeklyReport');
    expect(src).toContain('await getWeeklyReport(name, { silent: true })');
  });

  it('周列表只在抽屉打开时拉 (主页不每 30s 拉一堆大 JSON)', () => {
    expect(src).toContain('async function ensureWrList');
    expect(src).toContain('await ensureWrList()');
  });

  it('用户手动选过的周不会被自动刷新覆盖', () => {
    // 30s 自动刷新会写回 wrLatest —— 如果无条件覆盖 wrSelectedName,
    // 用户正在看的周会被换掉
    expect(src).toContain('if (!wrSelectedName.value) wrSelectedName.value = first.name;');
  });

  it('周标签从文件名解析 (weekly-2026-W47.json → 2026-W47)', () => {
    expect(src).toContain('function wrWeekLabel');
    expect(src).toContain('/weekly-(\\d{4}-W\\d{1,2})/');
  });

  it('选中的周文件名只从列表项取 (周报内容里没有 name 字段)', () => {
    // 后端 /weekly-reports/{name} 拆了 .json 透出 → 内容里**没有** name
    // 曾在这里写成 weeklyReport.value?.name → TS 报错 + 逻辑错
    expect(src).not.toContain('weeklyReport.value?.name');
    expect(src).not.toContain('wrLatest.value?.name');
  });
});

describe('周报抽屉 · 成功率跳过算成功', () => {
  it('成功率用本地公式 (跳过算成功)', () => {
    expect(src).toContain('function wrCalcSuccessRate');
    expect(src).toContain('(success + skipped) / total');
  });

  it('抽屉里的成功率用的是新公式', () => {
    expect(src).toContain('const wrSuccessRate = computed');
    expect(src).toContain('{{ wrSuccessRate }}%');
  });

  it('卡片副标题也用新公式', () => {
    expect(src).toContain('const wrLatestSuccessRate = computed');
    expect(src).toContain('{{ wrLatestSuccessRate }}%');
  });

  it('不再直接用 JSON 里的 success_rate (那是旧口径)', () => {
    expect(src).not.toContain('telemetry.data.success_rate');
  });

  it('提示语说清口径', () => {
    expect(src).toContain('(成功 + 跳过) / 总运行');
  });

  it('分母含 running (还在跑的不算成功, 但也不该被高估)', () => {
    // 公式分母是 total (含 running), 不是 success + skipped
    expect(src).toMatch(/success \+ skipped\) \/ total/);
  });
});
