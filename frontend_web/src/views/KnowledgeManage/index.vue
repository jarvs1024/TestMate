<template>
  <div class="kb">
    <h1 class="title">📚 知识库</h1>
    <p class="lede">所有智能体共享的私有知识源 · 喂入文档 / Spec / 历史 Case / 缺陷档</p>

    <!-- 顶部: 概览 + 上传 -->
    <div class="row-grid">
      <div class="card">
        <h2><span>概览</span></h2>
        <div class="stats">
          <div class="stat">
            <div class="num">{{ datasets.length }}</div>
            <div class="lbl">数据集</div>
          </div>
          <div class="stat">
            <div class="num">{{ totalDocs }}</div>
            <div class="lbl">文档</div>
          </div>
          <div class="stat">
            <div class="num">{{ totalChunks }}</div>
            <div class="lbl">分段</div>
          </div>
          <div class="stat">
            <div class="num">—</div>
            <div class="lbl">已用 token</div>
          </div>
        </div>
      </div>
      <div class="card">
        <h2><span>新增文档</span></h2>
        <div class="upload">
          <input id="kb-file" type="file" multiple
            accept=".pdf,.md,.txt,.docx,.html,.json"
            @change="onPick" />
          <label for="kb-file" class="up-btn">
            📎 选择文件 · 支持 PDF / Word / Markdown / HTML
          </label>
          <div v-if="pending.length > 0" class="pending">
            <div v-for="(f, i) in pending" :key="i" class="pf">
              <span class="pn">{{ f.name }}</span>
              <span class="ps">{{ formatSize(f.size) }}</span>
              <button class="x" @click="remove(i)">×</button>
            </div>
            <div class="up-actions">
              <label class="field-mini">
                目标数据集
                <select v-model="targetDs">
                  <option v-for="d in datasets" :key="d.code" :value="d.code">{{ d.name }}</option>
                  <option value="__new__">+ 新建数据集</option>
                </select>
              </label>
              <button class="primary" :disabled="uploading" @click="onUpload">
                {{ uploading ? `上传中 ${progress}%` : `上传 ${pending.length} 个文件` }}
              </button>
            </div>
            <div v-if="uploading" class="bar">
              <div class="bar-fill" :style="{ width: progress + '%' }"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 数据集列表 -->
    <div class="card">
      <div class="ds-hd">
        <h2><span>数据集</span></h2>
        <button class="ghost" @click="newDs = !newDs">+ 新建数据集</button>
      </div>

      <div v-if="newDs" class="new-ds">
        <input v-model="newDsName" placeholder="数据集名 (例: NVMe 1.4 Spec)" />
        <input v-model="newDsDesc" placeholder="说明" />
        <button class="primary" @click="onCreateDs" :disabled="!newDsName.trim()">创建</button>
        <button class="ghost" @click="newDs = false">取消</button>
      </div>

      <table class="ds-tbl">
        <thead>
          <tr>
            <th>名称</th><th>说明</th><th>文档数</th><th>状态</th><th>最后更新</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in datasets" :key="d.code">
            <td class="nm">
              <span class="ds-ic">📁</span>
              <span>{{ d.name }}</span>
            </td>
            <td class="ds">{{ d.description || '—' }}</td>
            <td class="mono">{{ d.doc_count }}</td>
            <td><span class="ds-status" :class="`ds-${d.status}`">{{ d.statusText }}</span></td>
            <td class="mono">{{ d.updated_at || '—' }}</td>
            <td class="acts">
              <button class="mini" @click="onOpen(d)">查看</button>
              <button class="mini danger" @click="onDel(d)">删除</button>
            </td>
          </tr>
          <tr v-if="datasets.length === 0">
            <td colspan="6" class="empty">暂无数据集, 点击右上角 + 新建</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 关联的智能体 -->
    <div class="card">
      <h2><span>谁在用这些数据</span></h2>
      <p class="hint" style="margin: 0 0 12px;">数据被哪些智能体引用, 改文档后智能体下次调用会用到新内容 (RAG 实时检索)</p>
      <div class="users">
        <div v-for="a in usingAgents" :key="a.code" class="ua">
          <span class="ua-ic">{{ a.icon }}</span>
          <span class="ua-nm">{{ a.name }}</span>
          <span class="ua-ver">{{ a.version }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { listAgents, type AgentSummary } from '@/api/agents';

interface Dataset {
  code: string;
  name: string;
  description: string;
  doc_count: number;
  status: 'ready' | 'indexing' | 'error';
  statusText: string;
  updated_at: string;
}

const datasets = ref<Dataset[]>([
  { code: 'nvme-spec',  name: 'NVMe Spec 1.4 / 2.0',  description: 'NVMe 协议规范全文', doc_count: 12, status: 'ready', statusText: '已就绪', updated_at: '2026-07-04 14:20' },
  { code: 'jedec',      name: 'JEDEC SSD 标准',       description: 'JEDEC 行业标准',     doc_count: 8,  status: 'ready', statusText: '已就绪', updated_at: '2026-06-28 10:15' },
  { code: 'fw-bug',     name: 'FW 历史缺陷档',         description: '本组维护的 bug 库',  doc_count: 247, status: 'indexing', statusText: '索引中', updated_at: '2026-07-04 16:00' },
]);

const totalDocs = computed(() => datasets.value.reduce((s, d) => s + d.doc_count, 0));
const totalChunks = computed(() => totalDocs.value * 32);

const usingAgents = ref<AgentSummary[]>([]);
onMounted(async () => {
  try {
    const r = await listAgents();
    usingAgents.value = r.items.filter((a) => a.data_sources.some((s) => s.startsWith('ragflow:') || s === 'fw_library'));
  } catch {}
});

const pending = ref<File[]>([]);
const targetDs = ref('nvme-spec');
const uploading = ref(false);
const progress = ref(0);

function onPick(ev: Event) {
  const t = ev.target as HTMLInputElement;
  if (!t.files) return;
  pending.value = [...pending.value, ...Array.from(t.files)];
  t.value = '';
}
function remove(i: number) { pending.value.splice(i, 1); }
function formatSize(b: number) {
  if (b < 1024) return b + ' B';
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
  return (b / 1024 / 1024).toFixed(2) + ' MB';
}

async function onUpload() {
  if (pending.value.length === 0) return;
  uploading.value = true;
  progress.value = 0;
  // P0: mock
  for (let i = 0; i < pending.value.length; i++) {
    await new Promise((r) => setTimeout(r, 400));
    progress.value = Math.floor(((i + 1) / pending.value.length) * 100);
  }
  ElMessage.success(`已入队 ${pending.value.length} 个文件到 [${targetDs.value}], RAGFlow 索引中`);
  pending.value = [];
  uploading.value = false;
  progress.value = 0;
}

const newDs = ref(false);
const newDsName = ref('');
const newDsDesc = ref('');

function onCreateDs() {
  if (!newDsName.value.trim()) return;
  const code = newDsName.value.trim().toLowerCase().replace(/\s+/g, '-');
  datasets.value.unshift({
    code,
    name: newDsName.value.trim(),
    description: newDsDesc.value,
    doc_count: 0,
    status: 'ready',
    statusText: '已就绪',
    updated_at: new Date().toISOString().slice(0, 16).replace('T', ' '),
  });
  newDsName.value = '';
  newDsDesc.value = '';
  newDs.value = false;
  ElMessage.success('数据集创建成功');
}

function onOpen(d: Dataset) {
  ElMessage.info(`查看 ${d.name} · P1 实现`);
}
function onDel(d: Dataset) {
  if (confirm(`确认删除 [${d.name}] ?`)) {
    datasets.value = datasets.value.filter((x) => x.code !== d.code);
    ElMessage.success('已删除');
  }
}
</script>

<style scoped>
.kb { display: flex; flex-direction: column; gap: 18px; }
.title { font-size: 30px; font-weight: 800; margin: 0 0 8px; letter-spacing: -0.4px; color: var(--ink-900); }
.lede { color: var(--ink-700); margin: 0; font-size: 14.5px; }

.row-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 768px) { .row-grid { grid-template-columns: 1fr; } }

h2 { font-size: 15px; font-weight: 700; margin: 0 0 14px; color: var(--ink-900); display: flex; align-items: center; gap: 8px; }

.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.stat {
  text-align: center; padding: 14px 8px;
  background: var(--surface-sunken);
  border-radius: 10px;
}
.num { font-size: 22px; font-weight: 800; color: var(--primary); font-family: var(--font-mono); line-height: 1; }
.lbl { font-size: 11px; color: var(--ink-500); margin-top: 6px; }

.upload { display: flex; flex-direction: column; gap: 12px; }
.upload input { display: none; }
.up-btn {
  display: block; text-align: center;
  padding: 14px; border: 1.5px dashed var(--border-strong);
  border-radius: 10px; cursor: pointer;
  font-size: 13px; color: var(--ink-700);
  background: var(--surface);
  transition: all 0.15s ease;
}
.up-btn:hover { border-color: var(--primary); background: var(--primary-soft); color: var(--primary); }

.pending {
  background: var(--surface-sunken); border-radius: 10px; padding: 12px;
  display: flex; flex-direction: column; gap: 6px;
}
.pf { display: flex; align-items: center; gap: 8px; padding: 4px 6px; font-size: 12.5px; }
.pn { flex: 1; color: var(--ink-900); }
.ps { color: var(--ink-500); font-family: var(--font-mono); font-size: 11px; }
.x {
  background: transparent; border: 0; cursor: pointer;
  color: var(--ink-500); font-size: 16px; padding: 0 4px;
}
.x:hover { color: var(--err); }
.up-actions { display: flex; align-items: center; gap: 10px; margin-top: 6px; }
.field-mini { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-700); }
.field-mini select {
  padding: 4px 8px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface); color: var(--ink-900); font-size: 12px;
  font-family: inherit;
}
.bar { height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; margin-top: 4px; }
.bar-fill { height: 100%; background: var(--primary); transition: width 0.2s ease; }

.ds-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.ds-hd h2 { margin: 0; }
.ghost {
  background: transparent; border: 1px solid var(--border);
  padding: 5px 12px; border-radius: 7px;
  color: var(--ink-700); font-size: 12px; cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
}
.ghost:hover { border-color: var(--primary); color: var(--primary); }
.primary {
  background: var(--primary); color: #fff; border: 0;
  padding: 7px 14px; border-radius: 7px;
  font-size: 12.5px; font-weight: 600; font-family: inherit; cursor: pointer;
}
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
button.primary:not(:disabled):hover { box-shadow: 0 4px 12px rgba(28, 100, 242, 0.25); }

.new-ds {
  display: flex; gap: 8px; margin-bottom: 12px;
  padding: 10px; background: var(--surface-sunken); border-radius: 8px;
}
.new-ds input {
  flex: 1; padding: 6px 10px; border: 1px solid var(--border);
  border-radius: 6px; background: var(--surface); color: var(--ink-900);
  font-size: 12.5px; font-family: inherit;
}

.ds-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.ds-tbl th {
  text-align: left; padding: 10px 12px; color: var(--ink-500);
  font-weight: 500; font-size: 11.5px;
  text-transform: uppercase; letter-spacing: 0.04em;
  border-bottom: 1px solid var(--border);
}
.ds-tbl td { padding: 10px 12px; color: var(--ink-700); border-bottom: 1px solid var(--border); }
.ds-tbl tr:last-child td { border-bottom: none; }
.ds-tbl tr:hover { background: var(--surface-sunken); }
.nm { display: flex; align-items: center; gap: 8px; color: var(--ink-900); font-weight: 500; }
.ds-ic { font-size: 16px; }
.mono { font-family: var(--font-mono); font-size: 12px; }
.ds-status { font-size: 11px; padding: 2px 7px; border-radius: var(--radius-pill); font-weight: 500; }
.ds-ready { background: rgba(22, 163, 74, 0.1); color: var(--ok); }
.ds-indexing { background: rgba(245, 158, 11, 0.1); color: var(--warn); }
.ds-error { background: rgba(220, 38, 38, 0.1); color: var(--err); }
.acts { display: flex; gap: 4px; }
.mini {
  background: transparent; border: 1px solid var(--border);
  padding: 3px 8px; border-radius: 5px;
  color: var(--ink-700); font-size: 11px; cursor: pointer;
  font-family: inherit;
}
.mini:hover { border-color: var(--primary); color: var(--primary); }
.mini.danger:hover { border-color: var(--err); color: var(--err); }
.empty { text-align: center; color: var(--ink-500); padding: 30px; }

.users { display: flex; flex-wrap: wrap; gap: 8px; }
.ua {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 10px;
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  font-size: 12px;
}
.ua-ic { font-size: 14px; }
.ua-nm { color: var(--ink-900); font-weight: 500; }
.ua-ver { color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
</style>
