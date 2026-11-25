/**
 * 「规则命中」卡片的回归测试 (2026-11-25).
 *
 * 用户反馈: "TestMate 上的规则名字感觉没全, 有漏的?"
 *
 * 根因 (两个):
 *   ① 前端硬编码 slice(0, 10) → 399 个规则键只渲染 10 个,
 *      但卡片标题写「378 条」→ 用户以为看到的是全部.
 *   ② 后端 per_rule_stats 写死 `limit: 200` → 生产已有 223 个 MR,
 *      漏掉 23 个 (6% 的建议不在统计里).
 *
 * 修复 (A+C):
 *   A 前端: 默认 Top 10 + 「显示全部」按钮 + 搜索框 + 名字列不截断
 *   C 后端: _get_all_mrs() 分页拉全量 MR
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const BOARD = resolve(process.cwd(), 'src/views/Capability/BoardView.vue');
const src = readFileSync(BOARD, 'utf8');
// ⚠️ 后端文件在**仓库根**下 (不在 frontend_web/) → 用 ../ 往上走
const CLIENT = resolve(process.cwd(), '../backend_gateway/app/core/review_agent_client.py');
const clientSrc = readFileSync(CLIENT, 'utf8');

describe('A · 前端: 规则命中可展开全部 + 可搜索', () => {
  it('不再硬编码 slice(0, 10) 截断', () => {
    // ⚠️ 不能断言整个文件不含 '.slice(0, 10)' —— dismissalsSorted 和
    //    周报 MR 列表是**别的**功能, 它们的 slice(0, 10) 是合理的.
    //    只查「规则排序」这一处.
    expect(src).not.toContain(
      'rules.value].sort((a, b) => ruleCited(b) - ruleCited(a)).slice(0, 10)');
    expect(src).toContain('const rulesTopLimit = 10;');
  });

  it('有「显示全部 / 收起」按钮', () => {
    expect(src).toContain('class="rule-toggle"');
    expect(src).toContain('rulesAllOpen = !rulesAllOpen');
    expect(src).toContain('显示全部');
  });

  it('有搜索框', () => {
    expect(src).toContain('class="rule-search"');
    expect(src).toContain("const ruleSearch = ref('')");
    expect(src).toContain('搜规则名');
  });

  it('搜索是大小写不敏感的包含匹配', () => {
    expect(src).toContain('toLowerCase().includes(q)');
  });

  it('渲染用 rulesVisible (不是旧的 rulesTop 硬切)', () => {
    expect(src).toContain('const rulesVisible = computed');
    expect(src).toContain('v-for="r in rulesVisible"');
    // ⚠️ 不能留一个没人用的 rulesTop 别名 —— vue-tsc 会报 TS6133 (未使用)
    expect(src).not.toContain('const rulesTop = computed');
  });

  it('搜索无结果时有空状态提示', () => {
    expect(src).toContain('没有匹配');
  });

  it('规则名不再被 ellipsis 截断', () => {
    // 名字列固定 220px + text-overflow: ellipsis → 「CODE-RULE-...-REQUIRE…」
    expect(src).not.toContain('.rule-k { font-family: var(--font-mono); font-size: 11.5px; color: var(--ink-700); overflow: hidden; text-overflow: ellipsis;');
    expect(src).toContain('overflow-wrap: anywhere');
  });

  it('柱状图比例按全部规则的最大值算 (展开后比例不被放大)', () => {
    // maxCited 必须基于 rulesSorted (全量), 不能基于可见的 10 条
    expect(src).toContain('const maxCited = computed(() => Math.max(1, ...rulesSorted.value.map(ruleCited)))');
  });

  it('窄屏有降级布局 (4 列 grid 在窄屏会挤爆)', () => {
    expect(src).toContain('@media (max-width: 900px)');
  });
});

describe('C · 后端: 规则统计拉全量 MR (分页)', () => {
  it('不再写死 limit: 200', () => {
    expect(clientSrc).not.toContain('await _get("/mrs", {"limit": 200})');
  });

  it('有分页拉全量的 helper', () => {
    expect(clientSrc).toContain('async def _get_all_mrs(');
    expect(clientSrc).toContain('mrs_list = await _get_all_mrs()');
  });

  it('用 until 游标翻页 (exclusive, 不重复)', () => {
    expect(clientSrc).toContain('params["until"] = until');
    expect(clientSrc).toContain('until = created');
  });

  it('按 (project_id, mr_iid) 去重', () => {
    expect(clientSrc).toContain('seen: set[tuple[Any, Any]] = set()');
    expect(clientSrc).toContain('if key in seen:');
  });

  it('分页有上限保护 (不会无限翻页)', () => {
    expect(clientSrc).toContain('max_pages: int = 20');
    expect(clientSrc).toContain('for _ in range(max_pages):');
  });

  it('页大小不超过 ReviewAgent 端点上限 1000', () => {
    expect(clientSrc).toContain('page_size: int = 500');
  });
});
