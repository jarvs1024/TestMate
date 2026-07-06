<template>
  <div class="runner">
    <!-- 顶栏 -->
    <div class="run-hd">
      <button class="back" @click="$router.push({ name: 'plaza' })">← 返回广场</button>
      <div class="run-title">
        <div class="run-icon" v-if="agent">{{ agent.icon }}</div>
        <div>
          <div class="run-name">
            <span v-if="agent">{{ agent.name }}</span>
            <span v-else>加载中...</span>
            <span v-if="agent" class="run-ver">{{ agent.version }}</span>
          </div>
          <div v-if="agent" class="run-summary">{{ agent.summary }}</div>
        </div>
      </div>
      <div v-if="agent" class="run-badge" :class="`st-${agent.status}`">
        <span class="dot"></span>{{ STATUS_LABELS[agent.status] }}
      </div>
    </div>

    <div v-if="agent && agent.embed_url" class="run-embed">
      <div class="embed-hd">
        <span class="embed-tag">🪟 嵌入模式</span>
        <span class="embed-hint">{{ embedLabel }} · 由 {{ agent.embed_url }} 提供</span>
        <a :href="agent.embed_url" target="_blank" rel="noopener" class="embed-pop">↗ 新窗口打开</a>
      </div>
      <iframe
        :src="agent.embed_url"
        class="embed-frame"
        frameborder="0"
        allow="microphone"
        title="agent-embed"
      ></iframe>
    </div>

    <div v-else-if="agent && agent.status === 'draft'" class="run-body draft-mode">
      <div class="draft-page">
        <div class="draft-emoji">{{ agent.icon }}</div>
        <h3>{{ agent.name }} · 建设中</h3>
        <p class="draft-summary">{{ agent.summary }}</p>
        <p class="draft-meta">本智能体还在规划中, 上线会推送到广场. 现在点
          <router-link :to="{ name: 'plaza' }">返回广场</router-link>
          看其他能用的.
        </p>
      </div>
    </div>
    <div v-else-if="agent" class="run-body">
      <!-- 左:参数配置 -->
      <div class="run-form card">
        <h2>📋 参数配置</h2>

        <div v-for="f in agent.input_schema" :key="f.key" class="field">
          <label>
            {{ f.label }}
            <span v-if="f.required" class="req">*</span>
            <span v-if="f.placeholder" class="hint">— {{ f.placeholder }}</span>
          </label>

          <input v-if="f.type === 'text'" v-model="form[f.key]" type="text"
            :placeholder="f.placeholder || ''" />

          <textarea v-else-if="f.type === 'textarea'" v-model="form[f.key]" rows="3"
            :placeholder="f.placeholder || ''" />

          <input v-else-if="f.type === 'number'" v-model.number="form[f.key]" type="number"
            :min="f.min" :max="f.max" :placeholder="f.placeholder || ''" />

          <select v-else-if="f.type === 'select'" v-model="form[f.key]">
            <option v-for="o in f.options || []" :key="o" :value="o">{{ o }}</option>
          </select>

          <div v-else-if="f.type === 'file'" class="file-pick">
            <input :id="`f-${f.key}`" type="file" :accept="f.accept || '*'" @change="onFile($event, f.key)" />
            <label :for="`f-${f.key}`" class="file-btn">
              📎 选择文件
              <span v-if="files[f.key]" class="file-name">{{ files[f.key]?.name }}</span>
              <span v-else class="file-hint">{{ f.accept || '任意文件' }}</span>
            </label>
          </div>

          <div v-else-if="f.type === 'machine_select'" class="machine-pick">
            <select v-model="form[f.key]">
              <option value="">— 选择机台 —</option>
              <option v-for="m in machines" :key="m.id" :value="m.id">
                {{ m.name }} ({{ m.ip }})
              </option>
            </select>
            <span v-if="machines.length === 0" class="hint">暂无机台, 去 "我的 → 机台" 加</span>
          </div>

          <div v-else-if="f.type === 'machine_multi_select'" class="machine-multi">
            <label v-for="m in machines" :key="m.id" class="check">
              <input type="checkbox" :value="m.id"
                :checked="(form[f.key] || []).includes(m.id)"
                @change="toggleMulti(f.key, m.id, ($event.target as HTMLInputElement).checked)" />
              {{ m.name }} <span class="hint">({{ m.ip }})</span>
            </label>
            <span v-if="machines.length === 0" class="hint">暂无机台</span>
          </div>

          <div v-else class="unknown">⚠ 未实现的字段类型: {{ f.type }}</div>
        </div>

        <div class="actions">
          <button class="primary" :disabled="running" @click="onRun">
            <span v-if="!running">▶ 运行</span>
            <span v-else>⏳ 运行中...</span>
          </button>
          <button class="secondary" @click="onReset">重置</button>
        </div>

        <details class="sop">
          <summary>📖 使用场景 (SOP)</summary>
          <div class="sop-body">
            <div class="sop-when">
              <strong>✓ 适用</strong>
              <pre>{{ agent.use_when }}</pre>
            </div>
            <div class="sop-not">
              <strong>✗ 不适用</strong>
              <pre>{{ agent.not_for || '—' }}</pre>
            </div>
          </div>
        </details>
      </div>

      <!-- 右:运行结果 -->
      <div class="run-output card">
        <div class="out-hd">
          <h2>📡 运行结果</h2>
          <div class="out-status" :class="{ running }">
            <span class="dot"></span>
            <span v-if="!lastRun">待运行</span>
            <span v-else-if="running">运行中 · {{ elapsed }}s</span>
            <span v-else>完成 · 用时 {{ elapsed }}s</span>
          </div>
        </div>

        <div v-if="!lastRun" class="empty">
          <div style="font-size: 36px; opacity: 0.35">📡</div>
          <div>填好左侧参数, 点击 "运行".</div>
          <div class="empty-tip">结果会流式显示在这</div>
        </div>

        <div v-else class="timeline">
          <div v-for="(ev, i) in events" :key="i" class="ev" :class="`ev-${ev.type}`">
            <span class="ev-icon">{{ EV_ICON[ev.type] }}</span>
            <div class="ev-body">
              <div v-if="ev.title" class="ev-title">{{ ev.title }}</div>
              <div class="ev-content">{{ ev.content }}</div>
            </div>
          </div>
          <div v-if="running" class="ev ev-streaming">
            <span class="ev-icon">✎</span>
            <div class="ev-body">
              <div class="ev-content"><span class="cursor"></span></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="loading">加载智能体...</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { getAgent, type AgentSummary, type AgentInputField } from '@/api/agents';
import axios from 'axios';

const route = useRoute();
const code = String(route.params.code);

const agent = ref<AgentSummary | null>(null);
const machines = ref<Array<{ id: number; name: string; ip: string }>>([]);
const form = reactive<Record<string, any>>({});
const files = reactive<Record<string, File | null>>({});
const running = ref(false);
const lastRun = ref(false);
const elapsed = ref(0);
const events = ref<Array<{ type: string; title?: string; content: string }>>([]);

const embedLabel = computed(() => {
  if (!agent.value?.embed_url) return '内嵌外部应用';
  const u = agent.value.embed_url.toLowerCase();
  if (u.includes('chatbot') || u.includes('dify')) return '内嵌 Dify Chatbot';
  if (u.includes('search/share') || u.includes('ragflow')) return '内嵌 RAGFlow 共享搜索';
  return '内嵌外部应用';
});

const STATUS_LABELS: Record<string, string> = {
  draft: '建设中', alpha: '内测', beta: 'Beta', stable: '稳定', deprecated: '弃用',
};
const EV_ICON: Record<string, string> = {
  info: 'ℹ', ok: '✓', warn: '⚠', err: '✗', section: '▣', stream: '✎', log: '›',
};

let timer: number | null = null;

function startTimer() {
  const t0 = Date.now();
  timer = window.setInterval(() => { elapsed.value = Math.floor((Date.now() - t0) / 1000); }, 200);
}
function stopTimer() {
  if (timer) { clearInterval(timer); timer = null; }
}

function initDefaults(schema: AgentInputField[]) {
  for (const f of schema) {
    if (form[f.key] !== undefined) continue;
    if (f.type === 'machine_multi_select') form[f.key] = [];
    else if (f.default !== undefined) form[f.key] = f.default;
    else if (f.type === 'number') form[f.key] = 0;
    else form[f.key] = '';
  }
}

function onFile(ev: Event, key: string) {
  const t = ev.target as HTMLInputElement;
  files[key] = t.files?.[0] || null;
  form[key] = t.files?.[0]?.name || '';
}

function toggleMulti(key: string, v: number, checked: boolean) {
  const cur: number[] = form[key] || [];
  if (checked && !cur.includes(v)) form[key] = [...cur, v];
  else if (!checked) form[key] = cur.filter((x) => x !== v);
}

/* ===== 日志分析 (demo) ===== */
// 分类规则: (pattern, category, severity, hint)
const LOG_RULES: Array<{ re: RegExp; category: string; severity: 'err' | 'warn' | 'info'; hint: string }> = [
  { re: /nvme[\s\S]*I\/O\s+\d+\s+QID\s+\d+\s+timeout/i, category: 'NVMe IO timeout', severity: 'err', hint: '控制器未在规定时间内完成 IO, 常见原因: FW hang / 热降频 / PCIe 链路异常' },
  { re: /nvme[\s\S]*PCI device unresponsive/i,         category: 'NVMe 链路异常', severity: 'err', hint: 'PCIe 设备无响应, 排查: lspci / 复位链路 / 物理插槽' },
  { re: /nvme[\s\S]*Abort status/i,                    category: 'NVMe Abort',   severity: 'warn', hint: '提交了 abort, IO 被取消, 跟 timeout 关联看' },
  { re: /nvme[\s\S]*resetting controller/i,            category: 'NVMe Reset',   severity: 'warn', hint: '驱动走了控制器 reset 路径, 记录频次' },
  { re: /nvme[\s\S]*Invalid\s+opcode/i,                category: 'NVMe 协议错',  severity: 'err', hint: 'NVMe opcode 不被 FW 接受, FW/驱动版本不匹配可能' },
  { re: /nvme[\s\S]*Media and Data Integrity Errors/i,  category: '介质 / 数据完整性', severity: 'err', hint: 'UNC / 介质错误, 立即停止老化, 走 RMA 流程' },
  { re: /blk_update_request:\s*I\/O error/i,            category: 'blk IO error', severity: 'err', hint: '块层 IO error, 看上层 device-mapper / FS 行为' },
  { re: /EXT4-fs error/i,                                category: '文件系统错误', severity: 'err', hint: 'ext4 元数据异常, 立即 dump + 不要 fsck 自动跑' },
  { re: /XFS\s*\(.*\):\s*Corruption/i,                category: '文件系统错误', severity: 'err', hint: 'XFS 元数据损坏, 走 xfs_repair / 不要 mount -w' },
  { re: /thermal.*critical|temp.*critical|critical temperature/i, category: '温度临界', severity: 'err', hint: '过温保护, 停机 / 查散热 / 降负载' },
  { re: /CPU\s+\d+:\s+Package temperature above threshold/i, category: 'CPU 过温', severity: 'warn', hint: 'CPU 限频可能影响吞吐, 查机台环境' },
  { re: /Out of memory|oom-kill|invoked oom-killer/i,    category: 'OOM',          severity: 'err', hint: '内存不足杀进程, 看 dmesg 时间附近 workload / 内存泄漏' },
  { re: /segfault|general protection fault/i,            category: '应用 crash',   severity: 'err', hint: '应用层段错误, 收集 coredump' },
  { re: /WARNING:/i,                                     category: '通用警告',     severity: 'warn', hint: '非致命警告, 关注是否累积' },
  { re: /ERROR|FATAL|panic/i,                            category: '致命错误',     severity: 'err', hint: '需立即关注' },
  { re: /smartd.*FAILED|ata\d+\.\d+:\s*failed/i,      category: 'SMART 失败',   severity: 'err', hint: 'SMART 自检失败, 准备 RMA' },
  { re: /ata\d+:\s*soft reset|ata\d+:\s*hard reset/i, category: 'SATA 复位',   severity: 'warn', hint: 'SATA 链路 soft/hard reset, 看热插拔 / 链路质量' },
  { re: /nvme[\s\S]*initialization.?complete/i,        category: 'NVMe 正常',   severity: 'info', hint: '驱动加载完成, 正常' },
  { re: /scsi[\s\S]*Synchronize Cache\(10\) failed/i,  category: 'SCSI flush 失败', severity: 'warn', hint: 'flush cache 失败, 跟 PLP / 掉电路径相关' },
];

interface LogFinding {
  lineNo: number;
  ts?: string;
  category: string;
  severity: 'err' | 'warn' | 'info';
  raw: string;
  hint: string;
}

function parseTimestamp(line: string): string | undefined {
  // dmesg: "[ 1234.567890]"
  const dm = line.match(/\[\s*(\d+\.\d+)\]/);
  if (dm) return `+${dm[1]}s`;
  // syslog: "Mar 12 14:23:01" / "2026-03-12T14:23:01"
  const sl = line.match(/^([A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2})/);
  if (sl) return sl[1];
  const iso = line.match(/(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2})/);
  if (iso) return iso[1];
  return undefined;
}

function analyzeLog(text: string): {
  findings: LogFinding[];
  stats: { total: number; err: number; warn: number; info: number };
  categories: Record<string, number>;
} {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  const findings: LogFinding[] = [];
  const cats: Record<string, number> = {};
  let errN = 0, warnN = 0, infoN = 0;
  lines.forEach((line, idx) => {
    for (const r of LOG_RULES) {
      if (r.re.test(line)) {
        findings.push({
          lineNo: idx + 1,
          ts: parseTimestamp(line),
          category: r.category,
          severity: r.severity,
          raw: line.length > 200 ? line.slice(0, 200) + '…' : line,
          hint: r.hint,
        });
        cats[r.category] = (cats[r.category] || 0) + 1;
        if (r.severity === 'err') errN++;
        else if (r.severity === 'warn') warnN++;
        else infoN++;
        break; // 一行只归一类, 避免重复
      }
    }
  });
  return {
    findings,
    stats: { total: lines.length, err: errN, warn: warnN, info: infoN },
    categories: cats,
  };
}

async function runLogAnalysis() {
  const text = String(form.log_text || '');
  if (!text.trim()) {
    events.value.push({ type: 'err', title: '参数缺失', content: 'log_text 不能为空' });
    return;
  }
  const logType = String(form.log_type || 'auto');
  events.value.push({ type: 'info', title: '日志分析 (demo 模式)', content: `日志类型: ${logType} · 引擎: builtin (本地规则匹配)` });
  await sleep(250);

  events.value.push({ type: 'log', content: '解析时间戳 + 分行...' });
  const r = analyzeLog(text);
  await sleep(300);

  // 总览
  const pct = r.stats.total === 0 ? 0 : Math.round((r.stats.err * 100) / r.stats.total);
  events.value.push({
    type: 'section',
    title: '▣ 概览',
    content: `共 ${r.stats.total} 行 · 错误 ${r.stats.err} (${pct}%) · 警告 ${r.stats.warn} · 信息 ${r.stats.info}`,
  });
  await sleep(400);

  // 错误分类统计
  if (Object.keys(r.categories).length > 0) {
    const lines = Object.entries(r.categories)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `  ${k.padEnd(18)} ${v}`);
    events.value.push({
      type: 'section',
      title: '📊 错误分类 (按命中行数排序)',
      content: lines.join('\n'),
    });
  } else {
    events.value.push({ type: 'section', title: '✓ 未发现已知错误模式', content: 'demo 规则集覆盖: NVMe / blk / ext4 / XFS / thermal / OOM / SMART / SATA / SCSI flush' });
  }
  await sleep(500);

  // 关键事件 (只列 err / warn)
  const critical = r.findings.filter((f) => f.severity !== 'info');
  if (critical.length > 0) {
    events.value.push({ type: 'section', title: `🚨 关键事件 (${critical.length} 条)`, content: '' });
    await sleep(200);
    // 流式输出前 10 条
    const top = critical.slice(0, 10);
    for (const f of top) {
      const tag = f.severity === 'err' ? '✗' : '⚠';
      events.value.push({
        type: f.severity === 'err' ? 'err' : 'warn',
        title: `${tag} L${f.lineNo}${f.ts ? ` ${f.ts}` : ''} · ${f.category}`,
        content: f.raw + '\n  → ' + f.hint,
      });
      await sleep(280);
    }
    if (critical.length > top.length) {
      events.value.push({ type: 'log', content: `… 还有 ${critical.length - top.length} 条未列出 (按规则只展示前 ${top.length} 条关键事件)` });
    }
  }
  await sleep(300);

  // 推测根因
  const topCat = Object.entries(r.categories).sort((a, b) => b[1] - a[1])[0];
  const summary = topCat
    ? `最高频类别: ${topCat[0]} (${topCat[1]} 次). 建议优先排查: ${topCat[0] === 'NVMe IO timeout' || topCat[0] === 'NVMe 链路异常' ? 'FW / PCIe 链路 / 供电' : topCat[0] === '温度临界' || topCat[0] === 'CPU 过温' ? '机台环境 / 散热 / 降负载' : topCat[0] === '介质 / 数据完整性' ? '立即停机 RMA' : '见上方分类'}.`
    : 'demo 规则集未命中任何已知模式, 建议人工研读或升级规则集.';
  events.value.push({ type: 'section', title: '💡 AI 推测根因 (demo)', content: summary });
  await sleep(300);

  events.value.push({
    type: r.stats.err > 0 ? 'warn' : 'ok',
    title: r.stats.err > 0 ? `✓ 完成 · 发现 ${r.stats.err} 个错误` : '✓ 完成 · 日志干净',
    content: `本次为客户端规则 demo, 真实 AI 推理待接入 Dify workflow (engine_config.demo=true).`,
  });
}


async function loadMachines() {
  try {
    const { data } = await axios.get('/api/v1/machines', {
      headers: { Authorization: `Bearer ${localStorage.getItem('testmate:token')}` },
    });
    machines.value = data.machines || [];
  } catch {
    machines.value = [];
  }
}

async function onRun() {
  try {
  if (!agent.value) return;
  events.value = [];
  lastRun.value = true;
  running.value = true;
  elapsed.value = 0;
  startTimer();

  // 0. 启动
  events.value.push({ type: 'info', title: '开始运行', content: `${agent.value.name} ${agent.value.version}` });

  // 1. 模拟参数校验
  events.value.push({ type: 'log', content: '校验参数...' });
  await sleep(300);

  // 1.5 引擎分发: log-analysis 走真实 demo (客户端规则), 其他 agent 走通用 mock
  if (agent.value.code === 'log-analysis') {
    await runLogAnalysis();
    return;
  }

  // 2. 模拟引擎调用
  events.value.push({ type: 'log', content: `调用 ${agent.value.engine} 引擎: ${agent.value.engine_config.workflow_id || 'default'}` });
  await sleep(400);

  // 3. 模拟数据源拉取
  if (agent.value.data_sources.length > 0) {
    events.value.push({ type: 'log', content: `拉取数据源: ${agent.value.data_sources.join(', ')}` });
    await sleep(500);
  }

  // 4. 模拟流式输出
  const sections = [
    { type: 'section', title: '▣ 事件时间线', content: '暂无异常事件' },
    { type: 'section', title: '💡 AI 推测根因', content: '(demo 模式) 请在 .env 配置 DIFY_BASE_URL + DIFY_API_KEY 启用真实 AI 推理' },
    { type: 'section', title: '📑 关联历史', content: '无 (RAGFlow 未配置)' },
    { type: 'ok', title: '✓ 运行完成', content: '本次为 mock 演示, 真实 AI 输出需要配置 Dify workflow' },
  ];

  for (const s of sections) {
    if (!running.value) break;
    events.value.push(s as any);
    await sleep(700);
  }

  } catch (e: any) {
    events.value.push({ type: 'err', title: '运行出错', content: e?.message || String(e) });
    console.error('onRun error', e);
  } finally {
    running.value = false;
    stopTimer();
  }
}

function onReset() {
  if (agent.value) initDefaults(agent.value.input_schema);
  for (const k of Object.keys(files)) files[k] = null;
  events.value = [];
  lastRun.value = false;
  elapsed.value = 0;
  stopTimer();
}

function sleep(ms: number) { return new Promise((r) => setTimeout(r, ms)); }

onMounted(async () => {
  try {
    const a = await getAgent(code);
    agent.value = a;
    initDefaults(a.input_schema);
    await loadMachines();
  } catch (e) {
    console.error(e);
  }
});
</script>

<style scoped>
.runner { display: flex; flex-direction: column; gap: 16px; }

.run-hd {
  display: flex; align-items: center; gap: 16px;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 16px 20px; box-shadow: var(--shadow-sm);
}
.back {
  background: transparent; border: 1px solid var(--border);
  padding: 6px 12px; border-radius: 8px;
  color: var(--ink-700); font-size: 12.5px; cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
}
.back:hover { background: var(--surface-sunken); color: var(--ink-900); }
.run-title { display: flex; align-items: center; gap: 14px; flex: 1; }
.run-icon {
  width: 48px; height: 48px; border-radius: 12px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center; font-size: 24px;
  box-shadow: var(--primary-shadow);
}
.run-name { display: flex; align-items: baseline; gap: 8px; }
.run-name > span:first-child { font-size: 20px; font-weight: 800; color: var(--ink-900); }
.run-ver { font-size: 12px; color: var(--ink-500); font-family: var(--font-mono); }
.run-summary { font-size: 13px; color: var(--ink-700); margin-top: 2px; }

.run-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px; border-radius: var(--radius-pill);
  font-size: 11px; font-weight: 600;
  background: var(--surface-sunken); color: var(--ink-700);
}
.run-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.st-stable { background: rgba(16, 185, 129, 0.12); color: var(--ok); }
.st-beta { background: rgba(245, 158, 11, 0.12); color: var(--warn); }
.st-alpha { background: rgba(245, 158, 11, 0.14); color: var(--warn); }
.st-draft { background: var(--surface-sunken); color: var(--ink-500); }

/* 嵌入模式 (Dify / RAGFlow iframe) */
.run-embed {
  display: flex;
  flex-direction: column;
  background: var(--card, var(--surface-soft));
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  /* 用 dvh 让 iframe 撑到 viewport - AppHeader - 上 padding */
  min-height: calc(100dvh - 110px);
  max-height: calc(100dvh - 110px);
}
.embed-hd {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px;
  background: var(--surface-sunken);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--ink-700);
  flex-shrink: 0;
}
.embed-tag {
  font-weight: 600;
  color: var(--primary);
  padding: 2px 8px;
  background: var(--primary-soft);
  border-radius: 5px;
  font-size: 11px;
}
.embed-hint { flex: 1; color: var(--ink-500); font-family: var(--font-mono, monospace); font-size: 11px; }
.embed-pop {
  color: var(--primary, #3b82f6);
  text-decoration: none;
  font-size: 12px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  transition: all 0.15s;
}
.embed-pop:hover { background: var(--primary-soft, #dbeafe); }
.embed-frame {
  width: 100%;
  flex: 1;
  border: 0;
  display: block;
  background: var(--surface);
}

.run-body {
  display: grid; grid-template-columns: 360px 1fr;
  gap: 16px; align-items: start;
}
@media (max-width: 1024px) { .run-body { grid-template-columns: 1fr; } }

.run-form h2, .run-output h2 { font-size: 15px; font-weight: 700; margin: 0 0 14px; color: var(--ink-900); }

.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.field label { font-size: 12.5px; color: var(--ink-700); font-weight: 500; }
.field label .req { color: var(--err); }
.field label .hint { color: var(--ink-500); font-weight: normal; }
.field input, .field textarea, .field select {
  width: 100%; padding: 9px 12px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--surface); color: var(--ink-900);
  font-size: 13px; font-family: inherit;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.field input:focus, .field textarea:focus, .field select:focus {
  outline: none; border-color: var(--primary);
  /* 清新版: 单层 focus ring */
  box-shadow: 0 0 0 3px var(--primary-soft);
}
.field textarea { resize: vertical; min-height: 64px; }

.file-pick input { display: none; }
.file-btn {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 12px; border: 1px dashed var(--border-strong);
  border-radius: 8px; cursor: pointer; background: var(--surface);
  font-size: 12.5px; color: var(--ink-700);
  transition: all 0.15s ease;
}
.file-btn:hover { border-color: var(--primary); background: var(--primary-soft); }
.file-name { color: var(--primary); font-weight: 600; }
.file-hint { color: var(--ink-500); }

.machine-multi { display: flex; flex-direction: column; gap: 6px; }
.check {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 8px; border-radius: 6px; cursor: pointer;
  font-size: 12.5px; color: var(--ink-700);
}
.check:hover { background: var(--surface-sunken); }

.actions { display: flex; gap: 10px; margin-top: 8px; margin-bottom: 12px; }
button.primary {
  background: var(--primary-grad); color: #fff; border: 0;
  padding: 10px 20px; border-radius: 9px;
  font-size: 13.5px; font-weight: 600; font-family: inherit; cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px;
  transition: transform 0.05s ease, box-shadow 0.15s ease, filter 0.15s ease;
}
button.primary:hover:not(:disabled) {
  filter: brightness(1.05);
  /* 单色柔和投影 + 上抬 */
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.28);
  transform: translateY(-1px);
}
button.primary:active:not(:disabled) { transform: translateY(1px); }
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
button.secondary {
  background: var(--surface-soft); color: var(--ink-700);
  border: 1px solid var(--border); padding: 10px 16px; border-radius: 9px;
  font-size: 13px; font-weight: 500; font-family: inherit; cursor: pointer;
  transition: all 0.15s ease;
}
button.secondary:hover { border-color: var(--border-strong); color: var(--ink-900); }

.sop { margin-top: 8px; border-top: 1px dashed var(--border); padding-top: 12px; }
.sop summary { font-size: 12.5px; color: var(--ink-500); cursor: pointer; padding: 4px 0; }
.sop-body { padding: 8px 0; display: flex; flex-direction: column; gap: 10px; }
.sop-when strong { color: var(--ok); font-size: 12px; }
.sop-not strong { color: var(--err); font-size: 12px; }
.sop pre {
  margin: 4px 0 0; font-size: 12px; color: var(--ink-700);
  background: var(--surface-sunken); padding: 8px 10px;
  border-radius: 6px; white-space: pre-wrap; font-family: inherit;
  line-height: 1.6;
}

.run-output { min-height: 400px; display: flex; flex-direction: column; }
.out-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.out-hd h2 { margin: 0; }
.out-status {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11.5px; color: var(--ink-500);
  padding: 4px 10px; background: var(--surface-sunken);
  border-radius: var(--radius-pill);
}
.out-status .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ink-500); }
.out-status.running { color: var(--primary); }
.out-status.running .dot { background: var(--primary); animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

.empty {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 8px; color: var(--ink-500);
  font-size: 13.5px; padding: 60px 20px;
}
.empty-tip { font-size: 11.5px; color: var(--ink-500); opacity: 0.7; }

.timeline { display: flex; flex-direction: column; gap: 10px; }
.ev {
  display: flex; gap: 10px; padding: 10px 12px;
  border-radius: 8px; background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--border);
}
.ev-icon {
  width: 22px; height: 22px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700;
  background: var(--surface-sunken); color: var(--ink-700);
  border-radius: 6px;
}
.ev-body { flex: 1; min-width: 0; }
.ev-title { font-size: 12.5px; font-weight: 600; color: var(--ink-900); margin-bottom: 2px; }
.ev-content { font-size: 12.5px; color: var(--ink-700); line-height: 1.55; white-space: pre-wrap; }

.ev-info {
  /* 左边 3px 渐变线: box-shadow inset 不支持渐变, 用 background gradient + mask 模拟 */
  border-left: 3px solid;
  border-image: var(--primary-grad) 1 100%;
  border-image-slice: 1;
  /* 配同色系极淡底色, 让"当前步骤"视觉重心更明显, 不只是 3px 细线 */
  background: var(--primary-grad-soft);
}
.ev-info .ev-icon { background: var(--primary-soft); color: var(--primary); }
.ev-ok {
  border-left-color: var(--ok);
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.06) 0%, rgba(16, 185, 129, 0.02) 100%);
}
.ev-ok .ev-icon { background: rgba(16, 185, 129, 0.1); color: var(--ok); }
.ev-warn {
  border-left-color: var(--warn);
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.06) 0%, rgba(245, 158, 11, 0.02) 100%);
}
.ev-warn .ev-icon { background: rgba(245, 158, 11, 0.1); color: var(--warn); }
.ev-err {
  border-left-color: var(--err);
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.06) 0%, rgba(239, 68, 68, 0.02) 100%);
}
.ev-err .ev-icon { background: rgba(239, 68, 68, 0.1); color: var(--err); }
.ev-section { border-left-color: var(--primary-2); }
.ev-section .ev-icon { background: rgba(13, 148, 136, 0.10); color: var(--primary-2); }
.ev-log { background: var(--surface-sunken); border-color: var(--border); }
.ev-log .ev-content { color: var(--ink-500); font-family: var(--font-mono); font-size: 11.5px; }
.ev-streaming .ev-icon { animation: pulse 1.2s ease-in-out infinite; }
.cursor { display: inline-block; width: 6px; height: 14px; background: var(--primary); animation: blink 1s steps(2) infinite; }
@keyframes blink { 0%,50% { opacity: 1; } 50.01%,100% { opacity: 0; } }

.draft-page {
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  text-align: center;
  padding: 80px 24px;
  gap: 12px;
  width: 100%;
}
.draft-page h3 { font-size: 22px; font-weight: 700; color: var(--ink-900); margin: 0; }
.draft-page .draft-emoji {
  font-size: 56px;
  background: linear-gradient(135deg, var(--primary-soft), var(--primary-grad-soft));
  padding: 28px;
  border-radius: 24px;
  filter: grayscale(0.4);
}
.draft-page .draft-summary { font-size: 14px; color: var(--ink-700); max-width: 560px; margin: 0; line-height: 1.6; }
.draft-page .draft-meta { font-size: 12.5px; color: var(--ink-500); margin: 8px 0 0; }
.draft-page .draft-meta a { color: var(--primary); }

.loading {
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 60px; text-align: center; color: var(--ink-500);
}

.unknown {
  padding: 8px 12px; background: rgba(239, 68, 68, 0.05);
  border: 1px dashed rgba(239, 68, 68, 0.3);
  border-radius: 6px; color: var(--err); font-size: 11.5px;
}
</style>
