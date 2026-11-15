<template>
  <div class="kbs">
    <h5>
      👥 用户空间
      <span class="sub-cnt">{{ spaces.length }} 个</span>
      <button class="mini-link" :disabled="loading" @click="load">刷新</button>
    </h5>
    <div class="hint">
      💡 一把 RAGFlow API Key = 一个用户空间。所有空间共用一个 RAGFlow 地址；
      知识库页可切换查看，MCP 工具可用 <code>space_id</code> 指定操作哪个空间，
      不指定时用最早创建的空间。
    </div>

    <div v-if="loadError" class="empty err">
      用户空间加载失败：{{ loadError }}
      <button class="ghost" :disabled="loading" @click="load">重试</button>
    </div>
    <div v-else-if="loading && !spaces.length" class="empty">正在读取用户空间…</div>
    <div v-else-if="!spaces.length" class="empty">还没有用户空间 —— 点下面新增一个</div>

    <table v-else class="kbs-tbl">
      <thead>
        <tr><th>名称</th><th>API Key</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="s in spaces" :key="s.id">
          <td>
            {{ s.name }}
            <code class="sid">{{ s.id }}</code>
          </td>
          <td class="mono">{{ maskLabel(s) }}</td>
          <td class="ops">
            <button class="mini-link" data-test="edit-space" :disabled="busy" @click="openEdit(s)">编辑</button>
            <button class="mini-link" data-test="test-space" :disabled="busy" @click="onTest(s)">测试</button>
            <button
              class="mini-link danger"
              data-test="delete-space"
              :disabled="busy"
              @click="remove(s)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="!editing" class="kbs-actions">
      <button class="mini-btn primary" data-test="add-space" :disabled="busy" @click="openAdd">＋ 新增用户空间</button>
    </div>

    <div v-else class="kbs-form">
      <h6>{{ editing === NEW ? '新增用户空间' : '编辑用户空间' }}</h6>
      <label class="field">
        <span>空间名称 <b>*</b></span>
        <input data-test="space-name" v-model="form.name" maxlength="64" placeholder="例如：测试组 / 产品组" />
      </label>
      <label class="field">
        <span>RAGFlow API Key <b v-if="editing === NEW">*</b><i v-else>(留空 = 不修改)</i></span>
        <input
          data-test="space-key"
          v-model="form.api_key"
          type="password"
          autocomplete="new-password"
          placeholder="ragflow-..." />
      </label>
      <div class="form-ops">
        <button class="mini-btn primary" data-test="save-space" :disabled="busy || !canSave" @click="save">
          {{ busy ? '保存中…' : '保存' }}
        </button>
        <button class="ghost" :disabled="busy" @click="editing = ''">取消</button>
      </div>
      <div v-if="formError" class="form-err">{{ formError }}</div>
    </div>

    <div v-if="testResult" class="test-result" :class="`s-${testResult.status}`">
      <span class="dot"></span>{{ testResult.name }}：{{ testResult.message }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  createKbSpace,
  deleteKbSpace,
  listKbSpaces,
  testKbSpace,
  updateKbSpace,
  type KbSpace,
} from '@/api/kb';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

const NEW = '__new__';

const spaces = ref<KbSpace[]>([]);
const loading = ref(false);
const loadError = ref('');
const busy = ref(false);
const formError = ref('');
const editing = ref('');
const testResult = ref<{ name: string; status: string; message: string } | null>(null);

const form = reactive({ name: '', api_key: '' });

const canSave = computed(() => {
  if (!form.name.trim()) return false;
  return editing.value !== NEW || !!form.api_key.trim();
});

/** 只显示前 4 位 —— 末 4 位露出来, 截图/录屏就等于泄露半截凭据 */
function maskLabel(s: KbSpace): string {
  const masked = s.key_masked || '';
  if (!masked) return '—';
  return masked.slice(0, 4) + '••••';
}

function errorText(error: unknown, fallback: string): string {
  return httpErrorText(errorStatus(error), errorDetail(error), fallback);
}

async function load() {
  loading.value = true;
  loadError.value = '';
  try {
    const result = await listKbSpaces();
    spaces.value = Array.isArray(result?.items) ? result.items : [];
  } catch (error) {
    loadError.value = errorText(error, '用户空间加载失败');
  } finally {
    loading.value = false;
  }
}

function openAdd() {
  editing.value = NEW;
  formError.value = '';
  form.name = '';
  form.api_key = '';
}

function openEdit(s: KbSpace) {
  editing.value = s.id;
  formError.value = '';
  form.name = s.name;
  form.api_key = '';
}

async function save() {
  if (!canSave.value || busy.value) return;
  busy.value = true;
  formError.value = '';
  try {
    if (editing.value === NEW) {
      await createKbSpace({
        name: form.name.trim(),
        api_key: form.api_key.trim(),
      });
      ElMessage.success(`已新增用户空间「${form.name.trim()}」`);
    } else {
      const payload: { name: string; api_key?: string } = {
        name: form.name.trim(),
      };
      if (form.api_key.trim()) payload.api_key = form.api_key.trim();
      await updateKbSpace(editing.value, payload);
      ElMessage.success('用户空间已更新');
    }
    editing.value = '';
    await load();
  } catch (error) {
    formError.value = errorText(error, '保存失败');
  } finally {
    busy.value = false;
  }
}

async function onTest(s: KbSpace) {
  busy.value = true;
  testResult.value = null;
  try {
    const result = await testKbSpace(s.id);
    testResult.value = { name: s.name, status: result.status, message: result.message };
  } catch (error) {
    testResult.value = { name: s.name, status: 'err', message: errorText(error, '测试失败') };
  } finally {
    busy.value = false;
  }
}

async function remove(s: KbSpace) {
  if (busy.value) return;
  try {
    await ElMessageBox.confirm(
      `删除后，知识库页将无法再切换到「${s.name}」。确定删除吗？`,
      '删除用户空间',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }
  busy.value = true;
  try {
    await deleteKbSpace(s.id);
    ElMessage.success(`已删除用户空间「${s.name}」`);
    if (editing.value === s.id) editing.value = '';
    await load();
  } catch (error) {
    ElMessage.error(errorText(error, '删除失败'));
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.kbs { margin-top: 4px; }
h5 {
  font-size: 12px; font-weight: 600; color: var(--ink-700);
  margin: 16px 0 8px; display: flex; align-items: center; gap: 6px;
}
.sub-cnt {
  font-size: 10.5px; padding: 1px 6px;
  background: var(--surface-sunken); color: var(--ink-500);
  border-radius: var(--radius-pill); font-weight: 500;
}
.hint {
  margin: 0 0 10px; font-size: 12px; color: var(--ink-500); line-height: 1.6;
  background: var(--surface-sunken); border-radius: 8px; padding: 8px 12px;
}
.hint code {
  font-family: var(--font-mono); color: var(--primary); font-size: 11.5px;
  background: var(--primary-soft); padding: 1px 6px; border-radius: 4px;
}
.empty {
  padding: 14px; text-align: center; font-size: 12.5px; color: var(--ink-500);
  border: 1px dashed var(--border); border-radius: 8px;
}
.empty.err { color: var(--err); border-color: rgba(239, 68, 68, .35); }
/* table-layout: fixed + 固定操作列 —— 不然按钮撑出去, 卡片右侧被截断 */
.kbs-tbl { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 12.5px; }
.kbs-tbl th {
  text-align: left; padding: 8px 10px; color: var(--ink-500); font-weight: 500;
  font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
  border-bottom: 1px solid var(--border);
}
.kbs-tbl th:nth-child(2), .kbs-tbl td:nth-child(2) { width: 120px; }
.kbs-tbl th:nth-child(3), .kbs-tbl td:nth-child(3) { width: 172px; }
.kbs-tbl td { padding: 8px 10px; color: var(--ink-700); border-bottom: 1px solid var(--border); vertical-align: middle; overflow-wrap: anywhere; }
.kbs-tbl .mono { font-family: var(--font-mono); font-size: 11.5px; }
.sid { margin-left: 6px; font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-500); }
.ops { display: flex; gap: 6px; flex-wrap: wrap; }
.mini-link {
  background: transparent; border: 1px solid var(--border); border-radius: 6px;
  color: var(--ink-700); font-size: 11px; padding: 3px 8px;
  cursor: pointer; font-family: inherit;
}
.mini-link:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.mini-link:disabled { opacity: .45; cursor: not-allowed; }
.mini-link.danger { color: var(--err); border-color: rgba(239, 68, 68, .35); }
.mini-link.danger:hover:not(:disabled) { border-color: var(--err); background: rgba(239, 68, 68, .08); }
.kbs-actions { margin-top: 10px; }
.mini-btn {
  border: 1px solid var(--border); background: var(--surface); border-radius: 6px;
  color: var(--ink-700); font-size: 12px; padding: 5px 12px;
  cursor: pointer; font-family: inherit;
}
.mini-btn.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
.mini-btn:disabled { opacity: .45; cursor: not-allowed; }
.kbs-form {
  margin-top: 10px; padding: 12px; border: 1px dashed var(--border);
  border-radius: 8px; display: flex; flex-direction: column; gap: 10px; max-width: 520px;
}
.kbs-form h6 { margin: 0; font-size: 12px; font-weight: 600; color: var(--ink-900); }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--ink-500); }
.field input {
  border: 1px solid var(--border); border-radius: 6px; background: var(--surface);
  color: var(--ink-900); font-size: 12.5px; padding: 6px 9px; font-family: inherit;
}
.field input:focus { outline: none; border-color: var(--primary); }
.field b { color: var(--err); }
.field i { font-style: normal; font-size: 11px; color: var(--ink-500); }
.form-ops { display: flex; gap: 8px; }
.ghost {
  border: 1px solid var(--border); background: transparent; border-radius: 6px;
  color: var(--ink-700); font-size: 12px; padding: 5px 12px;
  cursor: pointer; font-family: inherit;
}
.ghost:hover { border-color: var(--primary); color: var(--primary); }
.form-err { font-size: 12px; color: var(--err); }
.test-result {
  margin-top: 10px; font-size: 12px; display: flex; align-items: center; gap: 6px;
  color: var(--ink-700);
}
.test-result .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.test-result.s-ok { color: #16a34a; }
.test-result.s-err, .test-result.s-off { color: var(--err); }
</style>
