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

    <div class="set-layout">
      <!-- 左 sticky 目录 -->
      <aside class="set-toc">
        <div class="toc-hd">配置目录</div>
        <template v-for="s in sections" :key="s.id">
          <div :class="['toc-item', { active: activeTop === s.id }]"
               @click="onPickTop(s.id)">
            <span class="toc-ic">{{ s.icon }}</span>
            <span class="toc-lb">{{ s.label }}</span>
            <span v-if="!s.children?.length" class="toc-cnt">{{ s.count }}</span>
          </div>
          <ul v-if="s.children && s.children.length" class="toc-sub">
            <li v-for="c in s.children" :key="c.id"
                :class="{ active: activeTop === s.id && activeSub === c.id }"
                @click.stop="onPickSub(s.id, c.id)">
              <span class="toc-dot"></span>
              <span class="toc-lb">{{ c.label }}</span>
              <span class="toc-cnt">{{ c.count }}</span>
            </li>
          </ul>
        </template>
      </aside>

      <!-- 右侧 sections -->
      <main class="set-main">
        <!-- 📚 知识库 (大组) -->
        <section v-if="activeTop === 'sec-knowledge'" :id="'sec-knowledge'" class="card grp">
          <h2>
            <span>📚 知识库</span>
            <span class="grp-cnt">{{ knowledgeSource.length + searchItems.length + chatItems.length }} 项</span>
          </h2>

          <!-- 子组: 数据源 -->
          <div :id="'sec-knowledge-source'" class="sub-grp">
            <h3>📡 数据源 (RAGFlow) <span class="sub-cnt">{{ knowledgeSource.length }} 项</span></h3>
            <div v-for="(it, idx) in knowledgeSource" :key="it.key" class="row" :class="{ first: idx === 0 }">
              <div class="lbl-col">
                <div class="k">
                  <code>{{ it.key }}</code>
                  <span v-if="it.is_secret" class="secret-tag">secret</span>
                  <span v-if="!it.is_default" class="custom-tag">已定制</span>
                </div>
                <div class="d">{{ it.description }}</div>
              </div>
              <div class="inp-col">
                <label v-if="it.value_type === 'bool'" class="switch">
                  <input type="checkbox" :checked="!!drafts[it.key]"
                    :disabled="!isAdmin"
                    @change="setDraft(it.key, ($event.target as HTMLInputElement).checked)" />
                  <span class="sl"></span>
                  <span class="stxt">{{ drafts[it.key] ? 'ON' : 'OFF' }}</span>
                </label>
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
            <div class="test-row">
              <button class="test-btn" :disabled="!!testing" @click="onTest('knowledge-source')">
                {{ testing === 'knowledge-source' ? '测试中…' : '🔌 测试 RAGFlow 连接' }}
              </button>
              <div v-if="testResults['knowledge-source']" class="test-result" :class="`s-${testResults['knowledge-source']?.status}`">
                <span class="dot"></span>
                <span class="msg">{{ testResults['knowledge-source']?.message }}</span>
                <span v-if="testResults['knowledge-source']?.detail" class="det">
                  {{ JSON.stringify(testResults['knowledge-source']?.detail) }}
                </span>
              </div>
            </div>
          </div>

          <!-- 子组: 知识检索 -->
          <div :id="'sec-search'" class="sub-grp">
            <h3>🔎 知识检索 <span class="sub-cnt">{{ searchItems.length }} 项</span></h3>
            <SettingRow v-for="(it, idx) in searchItems" :key="it.key"
              :item="it" :is-first="idx === 0" :is-admin="isAdmin"
              :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
              :saving="saving === it.key" :secret-display="getInputValue(it)"
              @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
            <div class="hint">
              💡 这组控制 <code>/kb</code> 页"知识检索"卡片的嵌入 URL. 换 RAGFlow 共享 Search App / Dify chatbot / 任意可嵌入页面都改这里, 不需要改代码.
            </div>
          </div>

          <!-- 子组: 知识对话 -->
          <div :id="'sec-chat'" class="sub-grp">
            <h3>💬 知识对话 <span class="sub-cnt">{{ chatItems.length }} 项</span></h3>
            <SettingRow v-for="(it, idx) in chatItems" :key="it.key"
              :item="it" :is-first="idx === 0" :is-admin="isAdmin"
              :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
              :saving="saving === it.key" :secret-display="getInputValue(it)"
              @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
            <div class="hint">
              💡 这组控制 <code>/kb</code> 页"知识对话"tab 的嵌入 URL (RAGFlow 共享 Chat App / 任意可嵌入聊天页).
            </div>
          </div>

        </section>

        <!-- 🤖 智能体 -->
        <section v-if="activeTop === 'sec-agents'" :id="'sec-agents'" class="card grp">
          <h2>
            <span>🤖 智能体 / Dify</span>
            <span class="grp-cnt">{{ agentsItems.length }} 项</span>
          </h2>
          <div v-for="(it, idx) in agentsItems" :key="it.key" class="row" :class="{ first: idx === 0 }">
            <div class="lbl-col">
              <div class="k">
                <code>{{ it.key }}</code>
                <span v-if="it.is_secret" class="secret-tag">secret</span>
                <span v-if="!it.is_default" class="custom-tag">已定制</span>
              </div>
              <div class="d">{{ it.description }}</div>
            </div>
            <div class="inp-col">
              <label v-if="it.value_type === 'bool'" class="switch">
                <input type="checkbox" :checked="!!drafts[it.key]"
                  :disabled="!isAdmin"
                  @change="setDraft(it.key, ($event.target as HTMLInputElement).checked)" />
                <span class="sl"></span>
                <span class="stxt">{{ drafts[it.key] ? 'ON' : 'OFF' }}</span>
              </label>
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
          <div class="test-row">
            <button class="test-btn" :disabled="!!testing" @click="onTest('agents')">
              {{ testing === 'agents' ? '测试中…' : '🔌 测试 Dify 连接' }}
            </button>
            <div v-if="testResults['agents']" class="test-result" :class="`s-${testResults['agents']?.status}`">
              <span class="dot"></span>
              <span class="msg">{{ testResults['agents']?.message }}</span>
              <span v-if="testResults['agents']?.detail" class="det">
                {{ JSON.stringify(testResults['agents']?.detail) }}
              </span>
            </div>
          </div>
        </section>

        <!-- ⚙️ 通用 -->
        <section v-if="activeTop === 'sec-general'" :id="'sec-general'" class="card grp">
          <h2>
            <span>⚙️ 通用</span>
            <span class="grp-cnt">{{ generalItems.length }} 项</span>
          </h2>
          <div v-for="(it, idx) in generalItems" :key="it.key" class="row" :class="{ first: idx === 0 }">
            <div class="lbl-col">
              <div class="k">
                <code>{{ it.key }}</code>
                <span v-if="it.is_secret" class="secret-tag">secret</span>
                <span v-if="!it.is_default" class="custom-tag">已定制</span>
              </div>
              <div class="d">{{ it.description }}</div>
            </div>
            <div class="inp-col">
              <label v-if="it.value_type === 'bool'" class="switch">
                <input type="checkbox" :checked="!!drafts[it.key]"
                  :disabled="!isAdmin"
                  @change="setDraft(it.key, ($event.target as HTMLInputElement).checked)" />
                <span class="sl"></span>
                <span class="stxt">{{ drafts[it.key] ? 'ON' : 'OFF' }}</span>
              </label>
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
        </section>

        <!-- 🔔 通知 (P1) -->
        <section v-if="activeTop === 'sec-notification'" :id="'sec-notification'" class="card grp">
          <h2>
            <span>🔔 通知</span>
            <span class="grp-cnt">P1 规划中</span>
          </h2>
          <div class="empty-hint">
            <div class="eh-ic">🚧</div>
            <div class="eh-t">通知模块规划中</div>
            <div class="eh-d">钉钉群机器人 / 告警规则 / 通知日志 等配置项将在 P1 阶段开放.</div>
          </div>
        </section>

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
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { getSchema, updateSetting, testRagflow, testDify, type SettingItem, type TestResult } from '@/api/settings';
import SettingRow from './components/SettingRow.vue';
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

// 当前选中的顶级 section + 子级 (sub group)
const activeTop = ref<string>('sec-knowledge');
const activeSub = ref<string>('sec-knowledge-source');

// ===== 按 category 拆分 (后端 schema 是单一来源) =====
const knowledgeSource = computed(() => itemsByCategory('knowledge-source'));
const searchItems = computed(() => itemsByCategory('search'));
const chatItems = computed(() => itemsByCategory('chat'));
const agentsItems = computed(() => itemsByCategory('agents'));
const generalItems = computed(() => itemsByCategory('general'));

function itemsByCategory(cat: string): SettingItem[] {
  for (const g of groups.value) {
    if (g.category === cat) return g.items;
  }
  return [];
}

// ===== 左侧目录 (sections 定义) =====
const sections = computed(() => [
  {
    id: 'sec-knowledge',
    icon: '📚',
    label: '知识库',
    count: 0, // 父级不显示数字, 子级显示
    children: [
      { id: 'sec-knowledge-source', label: '数据源 (RAGFlow)', count: knowledgeSource.value.length },
      { id: 'sec-search',            label: '知识检索',         count: searchItems.value.length },
      { id: 'sec-chat',              label: '知识对话',         count: chatItems.value.length },
    ],
  },
  { id: 'sec-agents',       icon: '🤖', label: '智能体', count: agentsItems.value.length,   children: [] },
  { id: 'sec-general',      icon: '⚙️', label: '通用',   count: generalItems.value.length,  children: [] },
  { id: 'sec-notification', icon: '🔔', label: '通知',   count: 0,                          children: [] },
]);

// ===== 点击目录 =====
function onPickTop(topId: string) {
  activeTop.value = topId;
  // 滚到右侧 section 顶部 (不滚到子级)
  nextTick(() => {
    const el = document.getElementById(topId);
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

function onPickSub(topId: string, subId: string) {
  activeTop.value = topId;
  activeSub.value = subId;
  // 滚到右侧子 group 顶部
  nextTick(() => {
    const el = document.getElementById(subId);
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

// ===== 加载 / 渲染 =====
async function load() {
  const resp = await getSchema();
  groups.value = resp.groups;
  for (const g of resp.groups) {
    for (const it of g.items) {
      drafts[it.key] = it.value;
      originals[it.key] = it.value;
    }
  }
}

function isDirty(it: SettingItem) {
  if (it.is_secret) {
    const v = drafts[it.key];
    // secret: 空串或纯占位 = 没改, 跟原值有差异才算改
    if (v === '' || (typeof v === 'string' && /^•+$/.test(v))) return false;
    return v !== originals[it.key];
  }
  return drafts[it.key] !== originals[it.key];
}

function setDraft(key: string, v: any) {
  drafts[key] = v;
}
function toggleShow(key: string) {
  showSecrets[key] = !showSecrets[key];
}

function getInputValue(it: SettingItem) {
  if (it.is_secret) {
    const v = drafts[it.key];
    if (v === '' || v === undefined || v === null) return '';
    return v;
  }
  return drafts[it.key];
}

function revert(it: SettingItem) {
  drafts[it.key] = originals[it.key];
}

async function onSave(it: SettingItem) {
  saving.value = it.key;
  try {
    const updateSecret = it.is_secret;
    const v = drafts[it.key];
    await updateSetting(it.key, v, updateSecret);
    originals[it.key] = v;
    drafts[it.key] = v;
    ElMessage.success(`已保存: ${it.key}`);
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e?.message || e}`);
  } finally {
    saving.value = null;
  }
}

async function onTest(category: string) {
  testing.value = category;
  try {
    let r: TestResult;
    if (category === 'knowledge-source') r = await testRagflow();
    else if (category === 'agents') r = await testDify();
    else r = { ok: false, status: 'off', message: '未知分类', detail: null };
    testResults[category] = r;
  } catch (e: any) {
    testResults[category] = { ok: false, status: 'off', message: e?.message || '请求失败', detail: null };
  } finally {
    testing.value = null;
  }
}

onMounted(load);
</script>

<style scoped>
.set { padding: 4px 4px 40px; }
.lede { color: var(--ink-500); font-size: 13px; margin: 0 0 18px; }

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.warn-card {
  display: flex; gap: 14px; align-items: center;
  margin-bottom: 16px;
  background: rgba(245, 158, 11, 0.06);
  border-color: var(--warn);
}
.warn-ic { font-size: 24px; }
.warn-t { font-weight: 600; color: var(--ink-900); }
.warn-d { font-size: 12.5px; color: var(--ink-700); }

/* ====== 布局: 左 toc + 右 sections ====== */
.set-layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 24px;
  align-items: start;
}

.set-toc {
  position: sticky;
  top: 16px;
  max-height: calc(100vh - 32px);
  overflow: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 8px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.toc-hd {
  font-size: 11px; font-weight: 700; color: var(--ink-500);
  padding: 4px 10px 8px; letter-spacing: 0.04em; text-transform: uppercase;
}
.toc-item, .toc-sub li {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--ink-700);
  font-size: 13px;
  transition: background 0.15s ease, color 0.15s ease;
  user-select: none;
}
.toc-item:hover, .toc-sub li:hover { background: var(--surface-sunken); color: var(--ink-900); }
.toc-item.active, .toc-sub li.active {
  /* 用 3 段渐变 soft 版当底, 跟 Sidebar / Plaza filter 统一 */
  background: var(--primary-grad-soft);
  font-weight: 600;
  box-shadow: inset 0 0 0 1px var(--border);
}
.toc-item.active .toc-lb, .toc-sub li.active .toc-lb {
  background: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}
.toc-item.active .toc-ic, .toc-sub li.active .toc-ic {
  color: var(--primary);
  opacity: 1;
}
.toc-ic { font-size: 14px; width: 18px; text-align: center; flex-shrink: 0; }
.toc-lb { flex: 1; min-width: 0; }
.toc-cnt {
  font-size: 10.5px;
  padding: 1px 7px;
  background: var(--surface-sunken);
  color: var(--ink-500);
  border-radius: var(--radius-pill);
  font-weight: 500;
  flex-shrink: 0;
}
.toc-item.active .toc-cnt, .toc-sub li.active .toc-cnt {
  background: var(--primary-grad-text);
  color: #fff;
}
.toc-sub {
  list-style: none;
  margin: 2px 0 6px;
  padding: 0 0 0 18px;
  display: flex; flex-direction: column; gap: 1px;
}
.toc-sub li { font-size: 12.5px; padding: 5px 10px; }
.toc-dot {
  width: 4px; height: 4px; border-radius: 50%;
  background: currentColor; opacity: 0.5;
  flex-shrink: 0;
}

.set-main { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.set-main > .card { animation: fade-in 0.2s ease; }
@keyframes fade-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

/* ====== groups / rows / inputs (沿用旧版) ====== */
.grp h2 {
  font-size: 16px; font-weight: 700; margin: 0 0 14px; color: var(--ink-900);
  display: flex; align-items: center; gap: 8px;
}
.grp-cnt {
  font-size: 10.5px; padding: 2px 7px; background: var(--surface-sunken);
  color: var(--ink-500); border-radius: var(--radius-pill); font-weight: 500;
}

.sub-grp {
  padding: 16px 0 4px;
  border-top: 1px dashed var(--border);
  margin-top: 4px;
}
.sub-grp:first-of-type { border-top: none; padding-top: 8px; }
.sub-grp h3 {
  font-size: 13px; font-weight: 600;
  color: var(--ink-700);
  margin: 0 0 12px;
  display: flex; align-items: center; gap: 6px;
  scroll-margin-top: 16px;
}
.sub-cnt {
  font-size: 10.5px; padding: 1px 6px;
  background: var(--surface-sunken); color: var(--ink-500);
  border-radius: var(--radius-pill); font-weight: 500;
}
.hint {
  margin-top: 10px; font-size: 12px; color: var(--ink-500); line-height: 1.6;
  background: var(--surface-sunken); border-radius: 8px; padding: 8px 12px;
}
.hint code {
  font-family: var(--font-mono);
  color: var(--primary);
  font-size: 11.5px;
  background: var(--primary-soft);
  padding: 1px 6px;
  border-radius: 4px;
}

.empty-hint {
  display: flex; flex-direction: column; align-items: center;
  padding: 28px 20px; text-align: center;
  background: var(--surface-sunken); border-radius: 10px;
  border: 1px dashed var(--border);
}
.eh-ic { font-size: 32px; margin-bottom: 8px; opacity: 0.6; }
.eh-t { font-size: 14px; font-weight: 600; color: var(--ink-700); margin-bottom: 4px; }
.eh-d { font-size: 12.5px; color: var(--ink-500); }



































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
.s-ok { background: rgba(16, 185, 129, 0.1); color: var(--ok); }
.s-warn { background: rgba(245, 158, 11, 0.1); color: var(--warn); }
.s-off { background: rgba(239, 68, 68, 0.1); color: var(--err); }
.det { color: var(--ink-500); font-size: 10.5px; }

.info-card h2 { font-size: 15px; font-weight: 700; margin: 0 0 12px; color: var(--ink-900); }
.tips { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: var(--ink-700); line-height: 1.6; }
.tips strong { color: var(--ink-900); }

@media (max-width: 900px) {
  .set-layout { grid-template-columns: 1fr; }
  .set-toc { position: static; }
}
</style>
