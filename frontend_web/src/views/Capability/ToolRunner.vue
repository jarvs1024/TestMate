<template>
  <div class="runner">
    <!-- 顶栏: 能力详情统一外壳 (跟看板 / 资产 一致) -->
    <CapabilityShell
      v-if="agent"
      :name="agent.name"
      :icon="agent.icon"
      :kind="agent.kind"
      :status="agent.status"
      :version="agent.version"
      :category="agent.category"
    />

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
        <h3>{{ agent.name }} · 规划中</h3>
        <p class="draft-summary">{{ agent.summary }}</p>
        <p class="draft-meta">这项能力还在规划中, 上线后会出现在工作台. 现在点
          <router-link :to="{ name: 'home' }">返回工作台</router-link>
          看其他能用的.
        </p>
      </div>
    </div>
    <div v-else-if="agent" class="run-body">
      <!-- 左:参数配置 -->
      <div class="run-form card">
        <h2>📋 参数配置</h2>
        <!-- 能力描述归位到正文: 外壳不再带 summary (页头对工具型也没有 lede),
             描述跟着它描述的参数走 —— 看完一句话就知道该填什么 -->
        <p v-if="agent.summary" class="run-lead">{{ agent.summary }}</p>

        <div v-for="f in agent.input_schema" :key="f.key" class="field">
          <!-- ⚠️ 2026-10-30: 以前这个 <label> **既没有 for, 也不是控件的祖先**
               (label 和 input 是兄弟节点) —— 点字段标题不会聚焦输入框.
               现在补 for + 给控件补 id, 点标题就能跳到对应控件. -->
          <label :for="`f-${f.key}`">
            {{ f.label }}
            <span v-if="f.required" class="req">*</span>
            <span v-if="f.placeholder" class="hint">— {{ f.placeholder }}</span>
          </label>

          <input v-if="f.type === 'text'" v-model="form[f.key]" type="text"
            :id="`f-${f.key}`" :placeholder="f.placeholder || ''" />

          <textarea v-else-if="f.type === 'textarea'" v-model="form[f.key]" rows="3"
            :id="`f-${f.key}`" :placeholder="f.placeholder || ''" />

          <input v-else-if="f.type === 'number'" v-model.number="form[f.key]" type="number"
            :id="`f-${f.key}`" :min="f.min" :max="f.max" :placeholder="f.placeholder || ''" />

          <select v-else-if="f.type === 'select'" v-model="form[f.key]" :id="`f-${f.key}`">
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
            <select v-model="form[f.key]" :id="`f-${f.key}`">
              <option value="">— 选择机台 —</option>
              <option v-for="m in machines" :key="m.id" :value="m.id">
                {{ m.name }} ({{ m.ip }})
              </option>
            </select>
            <span v-if="machines.length === 0" class="hint">{{ machineHint }}</span>
          </div>

          <div v-else-if="f.type === 'machine_multi_select'" class="machine-multi">
            <label v-for="m in machines" :key="m.id" class="check">
              <input type="checkbox" :value="m.id"
                :checked="(form[f.key] || []).includes(m.id)"
                @change="toggleMulti(f.key, m.id, ($event.target as HTMLInputElement).checked)" />
              {{ m.name }} <span class="hint">({{ m.ip }})</span>
            </label>
            <span v-if="machines.length === 0" class="hint">{{ machineHint }}</span>
          </div>

          <div v-else class="unknown">⚠ 未实现的字段类型: {{ f.type }}</div>

          <!-- ⚠️ 2026-10-30: 必填字段以前只有个红星号, 点「运行」**不做任何校验**,
               空值照跑不误, 用户一点反馈都没有. 现在必填没填就拦下,
               错误贴在**出问题的那个字段下面** (复用 .unknown 的样式). -->
          <div v-if="fieldErrs[f.key]" class="unknown">⚠ {{ fieldErrs[f.key] }}</div>
        </div>

        <div class="actions">
          <button class="primary" :disabled="running" @click="onRun">
            <span v-if="!running">▶ 运行</span>
            <span v-else>⏳ 运行中...</span>
          </button>
          <!-- ⚠️ 2026-10-30: 运行中禁用「重置」 ——
               以前运行中也能点, 点了不清状态 (事件还会冒回来, 状态卡一直「运行中」) -->
          <button class="secondary" :disabled="running" @click="onReset">重置</button>
        </div>

        <details class="sop">
          <summary>📖 什么时候用 / 什么时候别用</summary>
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

    <div v-else-if="loadError" class="loading err">
      <div class="ld-ic">⚠️</div>
      <div class="ld-t">能力加载失败：{{ loadError }}</div>
      <router-link :to="{ name: 'home' }" class="ld-back">← 返回工作台</router-link>
    </div>

    <div v-else class="loading">加载中...</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { getCapability, type Capability, type AgentInputField } from '@/api/capabilities';
import request from '@/utils/request';
import CapabilityShell from '@/components/CapabilityShell.vue';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

const route = useRoute();
const code = String(route.params.code);

const agent = ref<Capability | null>(null);
/**
 * 能力加载失败 —— 页面内提示用.
 *
 * ⚠️ 以前 catch 里只 console.error, 而模板的 v-else 分支是「加载中...」——
 *    接口挂了页面就**永远**停在"加载中", 用户以为还在转圈.
 */
const loadError = ref('');
const machines = ref<Array<{ id: number; name: string; ip: string }>>([]);
/** 后端说"机台字典还没接"时给的说明 (跟"取不到"要分开说) */
const machineNote = ref('');
/** 机台列表读取失败 */
const machineError = ref('');
/** 机台下拉旁边的提示 —— 「还没接字典」vs「取不到」vs「真的没有」 */
const machineHint = computed(() => {
  if (machineError.value) return `机台列表读取失败: ${machineError.value}`;
  if (machineNote.value) return `暂无机台（${machineNote.value}）`;
  return '暂无机台（机台字典尚未接入）';
});
const form = reactive<Record<string, any>>({});
const files = reactive<Record<string, File | null>>({});
const running = ref(false);
const lastRun = ref(false);
const elapsed = ref(0);
const events = ref<Array<{ type: string; title?: string; content: string }>>([]);
/**
 * 字段级错误 (key → 文案) —— 2026-10-30.
 *
 * ⚠️ 以前必填字段只有一个红星号, 点「运行」时**完全不做校验**,
 *    空值照跑不误, 用户拿不到任何反馈.
 *    现在按 agent.input_schema 里的 required 逐个查, 错的贴到字段下面.
 */
const fieldErrs = reactive<Record<string, string>>({});

/**
 * 必填校验 —— 返回是否通过.
 *
 * ⚠️ 判据来自后端给的 `input_schema` (AgentInputField.required),
 *    不是前端写死的字段名 —— 后端加字段/改必填都不用动这里.
 */
function validateRequired(): boolean {
  for (const k of Object.keys(fieldErrs)) delete fieldErrs[k];
  const schema = agent.value?.input_schema || [];
  let ok = true;
  for (const f of schema) {
    if (!f.required) continue;
    const v = form[f.key];
    const empty =
      v === undefined || v === null ||
      (typeof v === 'string' && !v.trim()) ||
      (Array.isArray(v) && v.length === 0);
    if (empty) {
      fieldErrs[f.key] = `请填写 ${f.label}`;
      ok = false;
    }
  }
  return ok;
}

const embedLabel = computed(() => {
  if (!agent.value?.embed_url) return '内嵌外部应用';
  const u = agent.value.embed_url.toLowerCase();
  if (u.includes('chatbot')) return '内嵌 Chatbot';
  if (u.includes('search/share') || u.includes('ragflow')) return '内嵌 RAGFlow 共享搜索';
  return '内嵌外部应用';
});

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
async function loadMachines() {
  try {
    const r = (await request.get('/machines', { silent: true })) as {
      machines?: Array<{ id: number; name: string; ip: string }>;
      note?: string;
    };
    machines.value = r?.machines || [];
    machineNote.value = r?.note || '';
    machineError.value = '';
  } catch (e: any) {
    machines.value = [];
    machineNote.value = '';
    machineError.value = errText(e, '未知错误');
  }
}

async function onRun() {
  try {
  if (!agent.value) return;
  // ⚠️ 2026-10-30: 兜底防重入 —— 按钮禁用之外再加一道, 双击「运行」不该跑两遍
  if (running.value) return;
  // ⚠️ 必填校验 —— 以前这里什么都不查, 空参数也照跑
  if (!validateRequired()) return;
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

  // 2. 模拟引擎调用
  events.value.push({ type: 'log', content: `调用 ${agent.value.engine} 引擎: ${agent.value.engine_config?.workflow_id || 'default'}` });
  await sleep(400);

  // 3. 模拟数据源拉取
  if (agent.value.data_sources.length > 0) {
    events.value.push({ type: 'log', content: `拉取数据源: ${agent.value.data_sources.join(', ')}` });
    await sleep(500);
  }

  // 4. 模拟流式输出
  const sections = [
    { type: 'section', title: '▣ 事件时间线', content: '暂无异常事件' },
    { type: 'section', title: '💡 AI 推测根因', content: '(demo 模式) 本次为本地规则演示, 未调用外部 AI 服务' },
    { type: 'section', title: '📑 关联历史', content: '无 (RAGFlow 未配置)' },
    { type: 'ok', title: '✓ 运行完成', content: '本次为本地演示输出' },
  ];

  for (const s of sections) {
    if (!running.value) break;
    events.value.push(s as any);
    await sleep(700);
  }

  } catch (e: any) {
    events.value.push({ type: 'err', title: '运行出错', content: httpErrorText(errorStatus(e), errorDetail(e), String(e)) });
    console.error('onRun error', e);
  } finally {
    running.value = false;
    stopTimer();
  }
}

function onReset() {
  // ⚠️ 2026-10-30: 以前没置 running = false ——
  //    运行中点「重置」只清了事件, onRun 的循环条件 `if (!running.value) break;`
  //    还在成立 (running 仍是 true) → 事件又陆续冒回来, 状态卡一直显示「运行中 · 0s」,
  //    直到原来那条 sleep 链跑完才恢复. 现在先停掉运行态.
  running.value = false;
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
    const a = await getCapability(code);
    agent.value = a;
    initDefaults(a.input_schema);
    await loadMachines();
  } catch (e: any) {
    // ⚠️ 页面里要能看到失败 (见 loadError 的说明), 不能只 console.error
    loadError.value = errText(e, '未知错误');
  }
});

// ⚠️ 运行中离开页面必须停表 —— setInterval 不清理会一直跑 (组件都销毁了
//     elapsed 还在写), 同时把 running 置 false 让 onRun 的 sleep 链提前退出.
onUnmounted(() => {
  running.value = false;
  stopTimer();
});

/** 后端的 detail 可能是字符串也可能是对象 —— 取不到就退化到 message */
function errText(e: any, fallback: string): string {
  // ⚠️ 状态码也要翻译 —— 502/503 的原始报文 ("Request failed with status code 502")
  //    对用户是天书, 而这恰恰是本地部署最常见的故障 (后端没在跑).
  return httpErrorText(errorStatus(e), errorDetail(e), fallback);
}
</script>

<style scoped>
.runner { display: flex; flex-direction: column; gap: 16px; }

/* 嵌入模式 (外部页面 iframe) */
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
/* ⚠️ 2026-10-30: 去掉 var(--primary, #3b82f6) / var(--primary-soft, #dbeafe) 的 fallback ——
   --primary / --primary-soft 在 tokens.css 里**一定存在**, fallback 永远用不上,
   属于误导性写法 (看着像"没有主题色时降级", 实际是死的). */
.embed-pop {
  color: var(--primary);
  text-decoration: none;
  font-size: 12px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  transition: all 0.15s;
}
.embed-pop:hover { background: var(--primary-soft); }
.embed-frame {
  width: 100%;
  flex: 1;
  border: 0;
  display: block;
  background: var(--surface);
}

.run-body {
  /* ⚠️ 2026-10-30: 1fr → minmax(0, 1fr) ——
     `1fr` 轨道的**自动最小尺寸**就是内容的 min-content, 一条 300 字符无空格
     的 token (2516px) 就能把整页撑到 2622px, 375px 视口下横向要滑 7 屏.
     minmax(0,1fr) 允许轨道收缩到 0, 溢出交给内容自己换行. */
  display: grid; grid-template-columns: 360px minmax(0, 1fr);
  gap: 16px; align-items: start;
}
@media (max-width: 1024px) { .run-body { grid-template-columns: minmax(0, 1fr); } }

.run-form h2, .run-output h2 { font-size: 15px; font-weight: 700; margin: 0 0 14px; color: var(--ink-900); }
/* 能力描述 (从外壳移到这里) */
.run-lead {
  margin: -8px 0 14px; font-size: 12.5px; color: var(--ink-500);
  line-height: 1.55;
}

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
button.secondary:hover:not(:disabled) { border-color: var(--border-strong); color: var(--ink-900); }
/* ⚠️ 2026-10-30: 运行中「重置」是禁用的 —— 禁用态得画出来, 否则看着还能点 */
button.secondary:disabled { opacity: 0.5; cursor: not-allowed; }

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
  /* ⚠️ 2026-10-30: 同样补断词 —— pre-wrap 不等于会断长 token */
  overflow-wrap: anywhere; word-break: break-word;
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
/* ⚠️ 2026-10-30: 补 overflow-wrap / word-break ——
   只有 white-space: pre-wrap 的话, 一条没空格的长 token 仍然不换行, 照样撑爆卡片 */
.ev-content {
  font-size: 12.5px; color: var(--ink-700); line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere; word-break: break-word;
}

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
/* 加载失败 —— 跟"还在加载"区分开 (以前失败也停在这儿, 永远转圈) */
.loading.err { color: var(--err); border-color: rgba(239, 68, 68, 0.3); }
.loading.err .ld-ic { font-size: 30px; }
.loading.err .ld-t { margin-top: 8px; font-size: 13.5px; }
.loading.err .ld-back { display: inline-block; margin-top: 12px; color: var(--primary); font-size: 12.5px; }

.unknown {
  padding: 8px 12px; background: rgba(239, 68, 68, 0.05);
  border: 1px dashed rgba(239, 68, 68, 0.3);
  border-radius: 6px; color: var(--err); font-size: 11.5px;
}
</style>
