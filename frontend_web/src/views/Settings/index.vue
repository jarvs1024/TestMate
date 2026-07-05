<template>
  <div class="set">
    <h1 class="title" style="display:none">⚙️ 设置</h1>
    <p class="lede">平台运行配置 · 改了立刻生效, 不需重启</p>

    <div v-if="!isAdmin" class="card warn-card">
      <div class="warn-ic">🔒</div>
      <div>
        <div class="warn-t">只读模式</div>
        <div class="warn-d">当前账号无 admin 权限, 配置项只能查看不能改. 请用 admin 登录.</div>
      </div>
    </div>

    <div v-for="g in groups" :key="g.category" class="card grp">
      <h2>
        <span>{{ g.label }}</span>
        <span class="grp-cnt">{{ g.items.length }} 项</span>
      </h2>

      <div v-for="(it, idx) in g.items" :key="it.key" class="row" :class="{ first: idx === 0 }">
        <div class="lbl-col">
          <div class="k">
            <code>{{ it.key }}</code>
            <span v-if="it.is_secret" class="secret-tag">secret</span>
            <span v-if="!it.is_default" class="custom-tag">已定制</span>
          </div>
          <div class="d">{{ it.description }}</div>
        </div>
        <div class="inp-col">
          <!-- bool -->
          <label v-if="it.value_type === 'bool'" class="switch">
            <input type="checkbox" :checked="!!drafts[it.key]"
              :disabled="!isAdmin"
              @change="setDraft(it.key, ($event.target as HTMLInputElement).checked)" />
            <span class="sl"></span>
            <span class="stxt">{{ drafts[it.key] ? 'ON' : 'OFF' }}</span>
          </label>

          <!-- secret (mask) -->
          <template v-else-if="it.value_type === 'secret'">
            <div class="secret-wrap">
              <input :type="showSecrets[it.key] ? 'text' : 'password'"
                :value="getInputValue(it)"
                :placeholder="it.is_default ? '(使用 .env 默认值)' : '已设置, 留空不改'"
                :disabled="!isAdmin"
                @input="setDraft(it.key, ($event.target as HTMLInputElement).value)" />
              <button class="eye" type="button" @click="showSecrets[it.key] = !showSecrets[it.key]" :title="showSecrets[it.key] ? '隐藏' : '显示'">
                {{ showSecrets[it.key] ? '🙈' : '👁' }}
              </button>
            </div>
          </template>

          <!-- string / url / int -->
          <input v-else
            :type="it.value_type === 'int' ? 'number' : 'text'"
            :value="drafts[it.key]"
            :placeholder="it.description"
            :disabled="!isAdmin"
            @input="setDraft(it.key, ($event.target as HTMLInputElement).value)" />
        </div>
        <div class="act-col" v-if="isAdmin">
          <button class="primary" :disabled="!isDirty(it) || !!saving" @click="onSave(it)">
            {{ saving === it.key ? '保存中…' : '保存' }}
          </button>
          <button v-if="isDirty(it)" class="ghost" @click="revert(it)">取消</button>
        </div>
      </div>

      <!-- 测试连接 -->
      <div v-if="g.category === 'knowledge' || g.category === 'agents'" class="test-row">
        <button class="test-btn" :disabled="!!testing" @click="onTest(g.category)">
          {{ testing === g.category ? '测试中…' : '🔌 测试连接' }}
        </button>
        <div v-if="testResults[g.category]" class="test-result" :class="`s-${testResults[g.category]?.status}`">
          <span class="dot"></span>
          <span class="msg">{{ testResults[g.category]?.message }}</span>
          <span v-if="testResults[g.category]?.detail" class="det">
            {{ JSON.stringify(testResults[g.category]?.detail) }}
          </span>
        </div>
      </div>
    </div>

    <div class="card info-card">
      <h2>📌 说明</h2>
      <ul class="tips">
        <li><strong>配置优先级</strong> · 显式环境变量 &gt; DB &gt; .env &gt; 代码默认</li>
        <li><strong>改了立即生效</strong> · 不需要重启 backend, 下次调用就拿新值</li>
        <li><strong>已定制</strong> 标记 = 当前值跟你 .env 默认不一样, 是 UI 改过的</li>
        <li><strong>生产部署</strong> · DB 是单一真源, 不要再改 .env (重启会被 seed 覆盖)</li>
        <li><strong>测试连接</strong> · 用当前值去 ping 一下, 验证 key 没过期</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { getSchema, updateSetting, testRagflow, testDify, type SettingItem, type TestResult } from '@/api/settings';
import { useUserStore } from '@/stores/user';

const userStore = useUserStore();
const isAdmin = computed(() => userStore.user?.role === 'admin');

const groups = ref<{ category: string; label: string; items: SettingItem[] }[]>([]);
const drafts = reactive<Record<string, any>>({});
const originals = reactive<Record<string, any>>({});
const showSecrets = reactive<Record<string, boolean>>({});
const saving = ref<string | null>(null);
const testing = ref<string | null>(null);
const testResults = reactive<Record<string, TestResult | null>>({});

function setDraft(k: string, v: any) { drafts[k] = v; }

function getInputValue(it: SettingItem) {
  if (it.is_secret && it.value && !isDirty(it)) return it.value;  // mask 时显示掩码
  if (isDirty(it)) return drafts[it.key];
  return it.value || '';
}

function isDirty(it: SettingItem) {
  const d = drafts[it.key];
  // 改了任何值 (string 长度不同, bool 翻转, int 数字不同) 就算 dirty
  if (it.value_type === 'bool') return Boolean(d) !== Boolean(it.value);
  if (d === undefined) return false;
  if (it.is_secret && (d === '' || d === null)) return false;  // secret 留空 = 不改
  return String(d) !== String(it.value);
}

function revert(it: SettingItem) { drafts[it.key] = it.value; }

async function onSave(it: SettingItem) {
  saving.value = it.key;
  try {
    const v = drafts[it.key];
    // secret 留空 = 不改, update_secret=false
    const isEmptySecret = it.is_secret && (v === '' || v === null);
    await updateSetting(it.key, v, !isEmptySecret);
    originals[it.key] = v;
    if (!isEmptySecret) it.value = v;  // 本地同步
    it.is_default = false;
    ElMessage.success(`已保存 ${it.key}`);
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e?.response?.data?.detail || e?.message));
  } finally {
    saving.value = null;
  }
}

async function onTest(category: string) {
  testing.value = category;
  try {
    const r = category === 'knowledge' ? await testRagflow() : await testDify();
    testResults[category] = r;
    if (r.ok) ElMessage.success(r.message);
    else ElMessage.warning(r.message);
  } catch (e: any) {
    testResults[category] = { ok: false, status: 'off', message: e?.message || '测试失败', detail: null };
    ElMessage.error('测试失败');
  } finally {
    testing.value = null;
  }
}

onMounted(async () => {
  try {
    const r = await getSchema();
    groups.value = r.groups;
    for (const g of r.groups) {
      for (const it of g.items) {
        drafts[it.key] = it.value;
        originals[it.key] = it.value;
      }
    }
  } catch (e: any) {
    ElMessage.error('加载配置失败');
  }
});
</script>

<style scoped>
.set { display: flex; flex-direction: column; gap: 16px; }
.title { font-size: 30px; font-weight: 800; margin: 0 0 8px; letter-spacing: -0.4px; color: var(--ink-900); }
.lede { color: var(--ink-700); margin: 0; font-size: 14.5px; }

.warn-card {
  display: flex; align-items: center; gap: 12px;
  background: rgba(217, 119, 6, 0.06);
  border-color: var(--warn);
}
.warn-ic { font-size: 24px; }
.warn-t { font-weight: 600; color: var(--ink-900); }
.warn-d { font-size: 12.5px; color: var(--ink-700); }

.grp h2 {
  font-size: 16px; font-weight: 700; margin: 0 0 14px; color: var(--ink-900);
  display: flex; align-items: center; gap: 8px;
}
.grp-cnt {
  font-size: 10.5px; padding: 2px 7px; background: var(--surface-sunken);
  color: var(--ink-500); border-radius: var(--radius-pill); font-weight: 500;
}

.row {
  display: grid; grid-template-columns: 1.4fr 2fr auto;
  gap: 16px; align-items: start;
  padding: 14px 0;
  border-top: 1px dashed var(--border);
}
.row.first { border-top: none; padding-top: 4px; }
@media (max-width: 768px) { .row { grid-template-columns: 1fr; } }

.lbl-col .k { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.lbl-col code { font-size: 12.5px; background: var(--surface-sunken); padding: 2px 8px; border-radius: 5px; color: var(--primary); font-family: var(--font-mono); }
.lbl-col .d { font-size: 12px; color: var(--ink-500); margin-top: 4px; line-height: 1.5; }

.secret-tag { font-size: 9.5px; padding: 1px 6px; background: rgba(220, 38, 38, 0.1); color: var(--err); border-radius: var(--radius-pill); font-weight: 600; }
.custom-tag { font-size: 9.5px; padding: 1px 6px; background: var(--primary-soft); color: var(--primary); border-radius: var(--radius-pill); font-weight: 600; }

.inp-col input {
  width: 100%; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 7px; background: var(--surface); color: var(--ink-900);
  font-size: 13px; font-family: var(--font-mono);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.inp-col input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
.inp-col input:disabled { background: var(--surface-sunken); color: var(--ink-500); }

.secret-wrap { position: relative; }
.secret-wrap input { padding-right: 36px; }
.eye {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  background: transparent; border: 0; cursor: pointer;
  font-size: 14px; padding: 2px 6px;
  color: var(--ink-500);
}
.eye:hover { color: var(--ink-900); }

.switch { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; }
.switch input { display: none; }
.sl {
  width: 40px; height: 22px; background: var(--border-strong);
  border-radius: 999px; position: relative;
  transition: background 0.2s ease;
}
.sl::before {
  content: ''; position: absolute; width: 18px; height: 18px;
  background: #fff; border-radius: 50%; top: 2px; left: 2px;
  transition: transform 0.2s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}
.switch input:checked + .sl { background: var(--primary); }
.switch input:checked + .sl::before { transform: translateX(18px); }
.switch input:disabled + .sl { opacity: 0.5; }
.stxt { font-family: var(--font-mono); font-size: 11px; color: var(--ink-500); min-width: 24px; }

.act-col { display: flex; flex-direction: column; gap: 4px; align-items: stretch; min-width: 70px; }
.primary {
  background: var(--primary); color: #fff; border: 0;
  padding: 6px 14px; border-radius: 7px;
  font-size: 12.5px; font-weight: 600; font-family: inherit; cursor: pointer;
}
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.primary:not(:disabled):hover { box-shadow: 0 4px 12px rgba(28, 100, 242, 0.25); }
.ghost {
  background: transparent; border: 1px solid var(--border);
  padding: 5px 12px; border-radius: 7px;
  color: var(--ink-700); font-size: 12px; cursor: pointer; font-family: inherit;
}
.ghost:hover { border-color: var(--primary); color: var(--primary); }

.test-row {
  display: flex; align-items: center; gap: 12px;
  margin-top: 8px; padding-top: 12px;
  border-top: 1px solid var(--border);
  flex-wrap: wrap;
}
.test-btn {
  background: var(--surface-sunken); border: 1px solid var(--border);
  padding: 6px 14px; border-radius: 7px;
  font-size: 12.5px; color: var(--ink-700); cursor: pointer; font-family: inherit;
}
.test-btn:hover { border-color: var(--primary); color: var(--primary); }
.test-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.test-result {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: var(--radius-pill);
  font-size: 11.5px; font-family: var(--font-mono);
}
.test-result .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.s-ok { background: rgba(22, 163, 74, 0.1); color: var(--ok); }
.s-warn { background: rgba(217, 119, 6, 0.1); color: var(--warn); }
.s-off { background: rgba(220, 38, 38, 0.1); color: var(--err); }
.det { color: var(--ink-500); font-size: 10.5px; }

.info-card h2 { font-size: 15px; font-weight: 700; margin: 0 0 12px; color: var(--ink-900); }
.tips { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: var(--ink-700); line-height: 1.6; }
.tips strong { color: var(--ink-900); }
</style>
