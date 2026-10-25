<template>
  <div class="set">
    <h1 class="title" style="display:none">⚙️ 设置</h1>
    <!-- 描述只在页头说一次 (AppHeader 的 lede) —— 原来页头下面又跟一行灰字,
         两行说的是同一件事, 白占一行的正文空间. "改完立刻生效" 已经并进页头 lede. -->

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
            <span class="grp-cnt">{{ searchItems.length + chatItems.length }} 项</span>
          </h2>
          

          <!-- 子组: 知识检索 -->
          <div :id="'sec-search'" class="sub-grp">
            <h3>🔎 知识检索 <span class="sub-cnt">{{ searchItems.length }} 项</span></h3>
            <SettingRow v-for="(it, idx) in searchItems" :key="it.key"
              :item="it" :is-first="idx === 0" :is-admin="isAdmin"
              :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
              :saving="saving === it.key" :secret-display="getInputValue(it)"
              @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
            <div class="hint">
              💡 这组控制 <code>/kb</code> 页"知识检索"卡片的嵌入 URL. 换 RAGFlow 共享 Search App 或任意可嵌入页面都改这里, 不需要改代码.
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
            <span>🤖 智能体</span>
            <span class="grp-cnt">{{ agentItems.length + marketItems.length }} 项</span>
          </h2>

          <div class="sub-grp">
            <h3>🧪 智能体业务 <span class="sub-cnt">{{ agentItems.length }} 项</span></h3>
            <SettingRow v-for="(it, idx) in agentItems" :key="it.key"
              :item="it" :is-first="idx === 0" :is-admin="isAdmin"
              :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
              :saving="saving === it.key" :secret-display="getInputValue(it)"
              @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
            <div v-if="agentItems.length === 0" class="hint">
              暂无智能体业务配置. 智能体引擎 / 模型 / 工具等参数会出现在这里.
            </div>
          </div>

          <!-- 🧩 资产市场: 团队共享的插件 / 技能 / 连接器 -->
          <div class="sub-grp">
            <h3>🧩 资产市场 <span class="sub-cnt">{{ marketItems.length }} 项</span></h3>
            <div class="hint">
              💡 资产市场的后端配置 —— GitLab 仓库在哪、项目列表怎么配、谁能发布、
              怎么对外暴露 marketplace.json. 改完<strong>立即生效</strong>, 不用重启后端.
            </div>
            <SettingRow v-for="(it, idx) in marketItems" :key="it.key"
              :item="it" :is-first="idx === 0" :is-admin="isAdmin"
              :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
              :saving="saving === it.key" :secret-display="getInputValue(it)"
              @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />

            <!-- ⚠️ 测试连接 = **admin only** (后端已收紧) ——
                 非管理员点了只会吃一个 403, 不如不显示. -->
            <div v-if="isAdmin" class="test-row">
              <button class="test-btn" :disabled="!!testing" @click="onTest('gitlab')">
                {{ testing === 'gitlab' ? '测试中…' : '🔌 测试仓库连接' }}
              </button>
              <div v-if="testResults['gitlab']" class="test-result" :class="`s-${testResults['gitlab']?.status}`">
                <span class="dot"></span>
                <span class="msg">{{ testResults['gitlab']?.message }}</span>
              </div>
            </div>
            <div class="workdir mono">
              <div>工作区 <code>{{ marketWorkspace }}</code>
                <span class="muted">（容器内路径, 运行时不可改 —— 换了会丢掉现有工作副本）</span>
              </div>
              <div>远端 <code>{{ marketRemote }}</code>
                <span class="muted">（当前生效值, 改上面的「GitLab 仓库地址」后立即生效）</span>
              </div>
            </div>
          </div>

          <div class="hint">
            💡 所有外部数据源 (RAGFlow / ReviewAgent / 后续接入) 统一在 <strong>通用 → 📡 数据源</strong> 配置.
          </div>
        </section><section v-if="activeTop === 'sec-general'" :id="'sec-general'" class="card grp">
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

          <!-- 📡 数据源 (RAGFlow / ReviewAgent 统一配置入口, 按 prefix 分组) -->
          <div id="sec-general-data-source" class="sub-grp">
            <h3>📡 数据源 <span class="sub-cnt">{{ dataSourceItems.length }} 项</span></h3>
            <div class="hint">
              💡 所有外部数据源统一入口: 每个数据源一组配置 + 一个测试连接, 后续接入新外部服务在 SOURCE_GROUPS 数组里加一项即可.
            </div>
            <div v-for="grp in sourceGroups" :key="grp.id" class="ds-grp">
              <div class="ds-head">
                <span class="ds-icon">{{ grp.icon }}</span>
                <span class="ds-label">{{ grp.label }}</span>
                <span class="sub-cnt">{{ grp.items.length }} 项</span>
                <span class="ds-hint">{{ grp.hint }}</span>
              </div>
              <SettingRow v-for="(it, idx) in grp.items" :key="it.key"
                :item="it" :is-first="idx === 0" :is-admin="isAdmin"
                :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
                :saving="saving === it.key" :secret-display="getInputValue(it)"
                @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />
              <!-- ⚠️ 测试连接 = admin only (后端已收紧) -->
              <div v-if="isAdmin" class="test-row">
                <button class="test-btn" :disabled="!!testing" @click="onTest(grp.testKey)">
                  {{ testing === grp.testKey ? '测试中…' : '🔌 测试连接' }}
                </button>
                <div v-if="testResults[grp.testKey]" class="test-result" :class="`s-${testResults[grp.testKey]?.status}`">
                  <span class="dot"></span>
                  <span class="msg">{{ testResults[grp.testKey]?.message }}</span>
                  <span v-if="testResults[grp.testKey]?.detail" class="det">{{ JSON.stringify(testResults[grp.testKey]?.detail) }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 🔔 通知 (钉钉机器人 · 市场上下架通知) -->
        <section v-if="activeTop === 'sec-notification'" :id="'sec-notification'" class="card grp">
          <h2>
            <span>🔔 通知</span>
            <span class="grp-cnt">{{ notificationItems.length }} 项</span>
          </h2>
          <div class="hint">
            💡 通知分<strong>两个群</strong>:
            <strong>审核群</strong>收「上架待审核」「下架申请」—— 需要管理员处理的事;
            <strong>市场群</strong>收「上架成功」「版本更新」「彻底下架」(都 @所有人)
            和「审核不通过」(只 @发布者)。
            两个群的 webhook / 加签密钥 / 关键词各配各的 —— 测试环境可以把两边配成一样的。
            <br />下架要走审核: 申请阶段通知**审核群**, 等管理员确认、资产真的被移除才在**市场群**通知一次。
            配好 webhook 后点对应的「测试发送」自检一下; 群里立刻收到一条自检消息, 配不对会直接告诉你原因。
          </div>

          <SettingRow v-for="(it, idx) in notificationItems" :key="it.key"
            :item="it" :is-first="idx === 0" :is-admin="isAdmin"
            :draft="drafts[it.key]" :dirty="isDirty(it)" :show="!!showSecrets[it.key]"
            :saving="saving === it.key" :secret-display="getInputValue(it)"
            @update="setDraft" @toggle-show="toggleShow" @save="onSave" @revert="revert" />

          <!-- ⚠️ 测试发送 = admin only (后端已收紧) -->
          <div v-if="isAdmin" class="test-row">
            <button class="test-btn" :disabled="!!testing" @click="onTest('dingtalk-market')">
              {{ testing === 'dingtalk-market' ? '发送中…' : '📨 测试市场群' }}
            </button>
            <button class="test-btn" :disabled="!!testing" @click="onTest('dingtalk-review')">
              {{ testing === 'dingtalk-review' ? '发送中…' : '📨 测试审核群' }}
            </button>
            <div v-if="testResults['dingtalk-market']" class="test-result" :class="`s-${testResults['dingtalk-market']?.status}`">
              <span class="dot"></span>
              <span class="msg">{{ testResults['dingtalk-market']?.message }}</span>
            </div>
            <div v-if="testResults['dingtalk-review']" class="test-result" :class="`s-${testResults['dingtalk-review']?.status}`">
              <span class="dot"></span>
              <span class="msg">{{ testResults['dingtalk-review']?.message }}</span>
            </div>
          </div>

          <!-- 最近通知 (送达回执) -->
          <div class="sub-grp notif-log">
            <h3>📜 最近通知 <span class="sub-cnt">{{ notifyLog.length }} 条</span>
              <button class="mini-link" @click="loadNotifyLog">刷新</button>
            </h3>
            <div v-if="!notifyLog.length" class="notif-empty">还没有通知记录</div>
            <ul v-else class="notif-list">
              <li v-for="n in notifyLog" :key="n.id" :class="n.status">
                <span class="nl-act">{{ NOTIFY_EVENTS[n.event] || n.event }}</span>
                <code v-if="n.code" class="nl-code">{{ n.code }}</code>
                <span class="nl-chip" :class="n.status">
                  {{ n.status === 'sent' ? '已送达' : n.status === 'failed' ? '失败' : n.status === 'skipped' ? '未发送' : '待发' }}
                </span>
                <span class="nl-time mono">{{ fmtTime(n.last_attempt_at || n.created_at) }}</span>
                <span v-if="n.error" class="nl-err" :title="n.error">{{ n.error }}</span>
              </li>
            </ul>
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
import { getSchema, updateSetting, testRagflow, testReviewAgent, testDingTalk, testGitLab, type SettingItem, type TestResult } from '@/api/settings';
import { getMarketConfig, listNotifications, type AssetNotification } from '@/api/assets';
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
const activeSub = ref<string>('sec-search');

// ===== 按 category 拆分 (后端 schema 是单一来源) =====
const searchItems = computed(() => itemsByCategory('search'));
const chatItems = computed(() => itemsByCategory('chat'));
const generalItems = computed(() => itemsByCategory('general'));
// 通知 (钉钉机器人: webhook / 关键词 / 加签 / 触发开关)
const notificationItems = computed(() => itemsByCategory('notification'));
// 资产市场 (GitLab 仓库 / 安装目录 / 发布白名单 / 对外暴露方式)
const marketItems = computed(() => itemsByCategory('marketplace'));

// 市场当前生效的配置 (只读, 用来展示"工作区在哪 / 远端是哪个")
const marketWorkspace = ref('');
const marketRemote = ref('');
async function loadMarketConfig() {
  try {
    const c = await getMarketConfig();
    marketWorkspace.value = c.workspace || '(未知)';
    marketRemote.value = c.remote || '(未配置)';
  } catch {
    marketWorkspace.value = '(读取失败)';
    marketRemote.value = '';
  }
}

// ===== 通知回执 (送达记录) =====
const notifyLog = ref<AssetNotification[]>([]);
/**
 * 通知事件 → 中文 (回执列表用).
 *
 * ⚠️ 必须跟后端的 _EVENT_TEXT (app/core/dingtalk.py) **一一对应** ——
 *    以前这里只写了 4 个, 缺的 review / unpublish_request / reject
 *    在列表里直接显示原始 event id, 看不懂.
 */
const NOTIFY_EVENTS: Record<string, string> = {
  review: '新资产待审核',
  unpublish_request: '申请下架, 待确认',
  publish: '新资产上架',
  update: '版本更新',
  unpublish: '资产已下架',
  reject: '审核未通过',
  delete: '资产已删除',
};
async function loadNotifyLog() {
  try {
    const r = await listNotifications(20);
    notifyLog.value = r.items || [];
  } catch {
    notifyLog.value = [];
  }
}
function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// ===== 智能体 section: 业务配置 (引擎 / 模型 / 工具等) =====
// 数据源 (RAGFlow / ReviewAgent) 统一在 '通用 → 数据源' sub-group 配置
// AGENT_PREFIXES: 智能体业务配置 key 前缀, 后续加新智能体就在这里 append
const AGENT_PREFIXES: string[] = [];

function itemsByPrefix(prefix: string): SettingItem[] {
  const out: SettingItem[] = [];
  for (const g of groups.value) {
    for (const it of g.items) {
      if (it.key.startsWith(prefix)) out.push(it);
    }
  }
  return out;
}

// ===== 数据源 sub-group: 按 prefix 拆子组 (RAGFlow / ReviewAgent) =====
// 配置项都标 category='data-source', 这里按 key 前缀再细分, 让"测试连接"按钮紧贴对应配置.
// 后续接新数据源: 在 SOURCE_GROUPS 数组里加一项即可.
const dataSourceItems = computed(() => itemsByCategory('data-source'));

interface DataSourceGroup {
  id: string;          // 模板里渲染用, 也是测试结果 key
  prefix: string;      // key 必须以这个开头
  icon: string;
  label: string;       // 显示名
  testKey: string;     // 调用 settings.onTest 用的分类
  hint: string;
  items: SettingItem[];   // 经 vue computed 注入实际匹配项
}
// SOURCE_GROUPS 是静态声明 (没有 items 字段), 经 sourceGroups computed 注入实际匹配项.
type SourceGroupDef = Omit<DataSourceGroup, 'items'>;
const SOURCE_GROUPS: SourceGroupDef[] = [
  { id: 'ragflow',  prefix: 'ragflow.',  icon: '📚', label: 'RAGFlow (知识库 API)', testKey: 'ragflow',  hint: 'KB 知识库 · 数据集 / 文档 / chunking API' },
  { id: 'review-agent', prefix: 'review_agent.', icon: '🧬', label: 'ReviewAgent (代码检视)', testKey: 'review-agent', hint: '代码检视 · HTTP / 健康检查' },
];
const sourceGroups = computed<DataSourceGroup[]>(() =>
  SOURCE_GROUPS.map(g => ({
    ...g,
    items: dataSourceItems.value.filter(it => it.key.startsWith(g.prefix)),
  })).filter(g => g.items.length > 0),
);

const agentItems = computed(() =>
  AGENT_PREFIXES.flatMap(p => itemsByPrefix(p))
);


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
      { id: 'sec-search',            label: '知识检索',         count: searchItems.value.length },
      { id: 'sec-chat',              label: '知识对话',         count: chatItems.value.length },
    ],
  },
  { id: 'sec-agents',       icon: '🤖', label: '智能体', count: agentItems.value.length + marketItems.value.length, children: [] },
  { id: 'sec-general',      icon: '⚙️', label: '通用',   count: generalItems.value.length + dataSourceItems.value.length, children: [
    { id: 'sec-general-data-source', label: '📡 数据源', count: dataSourceItems.value.length },
  ] },
  { id: 'sec-notification', icon: '🔔', label: '通知',   count: notificationItems.value.length, children: [] },
]);

// ===== 点击目录 =====
function onPickTop(topId: string) {
  activeTop.value = topId;
  // 滚到右侧 section 顶部 (不滚到子级)
  nextTick(() => {
    const el = document.getElementById(topId);
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  // 通知区带送达回执, 进区就拉一次
  if (topId === 'sec-notification') loadNotifyLog();
  // 资产市场区展示当前生效的工作区/远端
  if (topId === 'sec-agents') loadMarketConfig();
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
/** bool 开关统一成真正的布尔 —— 后端可能回 "false" 字符串, !!"false" 是 true, 界面会骗人 */
function toBool(v: any, def = false): boolean {
  if (typeof v === 'boolean') return v;
  if (v === null || v === undefined || v === '') return def;
  if (typeof v === 'number') return v !== 0;
  const s = String(v).trim().toLowerCase();
  if (['true', '1', 'yes', 'on'].includes(s)) return true;
  if (['false', '0', 'no', 'off'].includes(s)) return false;
  return def;
}

async function load() {
  const resp = await getSchema();
  groups.value = resp.groups;
  for (const g of resp.groups) {
    for (const it of g.items) {
      const v = it.value_type === 'bool' ? toBool(it.value) : it.value;
      drafts[it.key] = v;
      originals[it.key] = v;
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

// ===== 数据源连接测试 =====
// testKey 跟 SOURCE_GROUPS[i].testKey 对齐: 'ragflow' / 'review-agent'.
const _testClients: Record<string, () => Promise<TestResult>> = {
  'ragflow':  testRagflow,
  'review-agent': testReviewAgent,
  // 钉钉分两个频道 (市场群 / 审核群), 各配各的 webhook → 也要分别自检
  'dingtalk-market': () => testDingTalk('market'),
  'dingtalk-review': () => testDingTalk('review'),
  'gitlab': testGitLab,
};
async function onTest(testKey: string) {
  const fn = _testClients[testKey];
  if (!fn) return;
  testing.value = testKey;
  try {
    testResults[testKey] = await fn();
  } catch (e: any) {
    testResults[testKey] = { ok: false, status: 'off', message: e?.message || '请求失败', detail: null };
  } finally {
    testing.value = null;
  }
}

onMounted(load);
</script>

<style scoped>

/* ===== 智能体 section: 数据源区 / 业务智能体区 分割线 ===== */
.sec-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border), transparent);
  margin: 20px 0;
}
.sec-divider::before {
  content: '';
}
.agent-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
@media (max-width: 1100px) { .agent-cards { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 700px)  { .agent-cards { grid-template-columns: 1fr; } }

.agent-card {
  display: flex; gap: 12px;
  padding: 14px; border-radius: 12px;
  background: var(--surface); border: 1px solid var(--border);
  cursor: pointer; transition: all 0.15s ease;
  align-items: flex-start;
}
.agent-card:hover {
  border-color: var(--primary);
  background: var(--surface-sunken);
  transform: translateY(-1px);
}
.agent-card.active {
  border-color: transparent;
  background: var(--primary-grad-soft);
  box-shadow: inset 0 0 0 1px var(--border);
}
.agent-card .ac-icon {
  width: 38px; height: 38px; border-radius: 10px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; flex-shrink: 0;
  box-shadow: var(--primary-shadow);
}
.agent-card .ac-body { flex: 1; min-width: 0; }
.agent-card .ac-row1 {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 8px;
}
.agent-card .ac-name { font-size: 14px; font-weight: 700; color: var(--ink-900); }
.agent-card .ac-cnt {
  font-size: 10.5px; padding: 1px 7px;
  background: var(--surface-sunken); color: var(--ink-700);
  border-radius: var(--radius-pill);
}
.agent-card.active .ac-cnt { background: var(--primary-grad); color: #fff; }
.agent-card .ac-sub {
  font-size: 11px; color: var(--ink-500);
  font-family: var(--font-mono); margin-top: 1px;
}
.agent-card .ac-summary {
  font-size: 12px; color: var(--ink-700); line-height: 1.5;
  margin-top: 4px;
}
.set { padding: 4px 4px 40px; }
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

/* === inline 渲染的 row (knowledgeSource / agents / general) 的样式 — 镜像 SettingRow 的 scoped 块 ===
   原因: Vue scoped CSS 不会穿透到父组件, SettingRow 内的类只能在 SettingRow 自己的 scoped 里生效.
   这三组在 Settings 模板里直接写了 .row / .lbl-col / .inp-col / .act-col / .primary,
   所以这些样式要在 Settings 这边的 scoped 里再放一份 (跟 SettingRow 完全一致). */
.row {
  display: grid; grid-template-columns: 1.4fr 2fr auto;
  gap: 16px; align-items: start;
  padding: 14px 0;
  border-top: 1px dashed var(--border);
}
.row.first { border-top: none; padding-top: 4px; }
@media (max-width: 768px) { .row { grid-template-columns: 1fr; } }

.lbl-col .k { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.lbl-col code {
  font-size: 13px; font-weight: 600;
  background: transparent;
  padding: 0;
  border-radius: 0;
  color: var(--primary);
  font-family: var(--font-body);
  background-image: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.lbl-col .d { font-size: 12px; color: var(--ink-500); margin-top: 4px; line-height: 1.5; }

.secret-tag { font-size: 9.5px; padding: 1px 6px; background: rgba(239, 68, 68, 0.1); color: var(--err); border-radius: var(--radius-pill); font-weight: 600; }
.custom-tag { font-size: 9.5px; padding: 1px 6px; background: var(--primary-soft); color: var(--primary); border-radius: var(--radius-pill); font-weight: 600; }

.inp-col input {
  width: 100%; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 7px; background: var(--surface); color: var(--ink-900);
  font-size: 13px; font-family: var(--font-mono);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.inp-col input:focus {
  outline: none; border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}
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
.switch input:checked + .sl { background: var(--primary-grad); }
.switch input:checked + .sl::before { transform: translateX(18px); }
.switch input:disabled + .sl { opacity: 0.5; }
.stxt { font-family: var(--font-mono); font-size: 11px; color: var(--ink-500); min-width: 24px; }

.act-col { display: flex; flex-direction: column; gap: 4px; align-items: stretch; min-width: 70px; }
.primary {
  background: var(--primary-grad); color: #fff; border: 0;
  padding: 6px 14px; border-radius: 7px;
  font-size: 12.5px; font-weight: 600; font-family: inherit; cursor: pointer;
  transition: filter .15s ease, box-shadow .15s ease;
}
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.primary:not(:disabled):hover {
  filter: brightness(1.05);
  box-shadow: 0 3px 10px rgba(59, 130, 246, 0.25);
  transform: translateY(-1px);
}
.ghost {
  background: transparent; border: 1px solid var(--border);
  padding: 5px 12px; border-radius: 7px;
  color: var(--ink-700); font-size: 12px; cursor: pointer; font-family: inherit;
}
.ghost:hover { border-color: var(--primary); color: var(--primary); }



































/* ===== 数据源 sub-group: 每个 prefix 一个子区 ===== */
.ds-grp {
  margin-top: 14px;
  padding: 14px 14px 12px;
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg, 10px);
}
.ds-grp .test-row { border-top-color: color-mix(in srgb, var(--border) 60%, transparent); }
.ds-head {
  display: flex; align-items: baseline; gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.ds-icon { font-size: 16px; }
.ds-label { font-weight: 600; color: var(--ink-900); font-size: 13.5px; }
.ds-hint { color: var(--ink-500); font-size: 11.5px; margin-left: 4px; }

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

/* ===== 通知: 最近通知 (送达回执) ===== */
.notif-log { margin-top: 18px; }
.notif-log h3 { display: flex; align-items: center; gap: 8px; }
.mini-link {
  margin-left: auto; background: transparent; border: 1px solid var(--border);
  padding: 2px 10px; border-radius: var(--radius-pill);
  font-size: 11px; color: var(--ink-700); cursor: pointer; font-family: inherit;
}
.mini-link:hover { border-color: var(--primary); color: var(--primary); }
.notif-empty { font-size: 12px; color: var(--ink-500); padding: 12px 0; }
.notif-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.notif-list li {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  border: 1px solid var(--border); border-left: 3px solid var(--border);
  border-radius: var(--radius-sm); padding: 7px 10px; background: var(--surface-soft);
  font-size: 12px;
}
.notif-list li.sent { border-left-color: var(--ok); }
.notif-list li.failed { border-left-color: var(--err); background: rgba(239, 68, 68, 0.06); }
.notif-list li.pending { border-left-color: var(--warn); }
.notif-list li.skipped { border-left-color: var(--ink-500); opacity: 0.7; }
.nl-act { font-weight: 600; color: var(--ink-900); }
.nl-code { font-family: var(--font-mono); font-size: 11px; color: var(--ink-700); }
.nl-chip {
  font-size: 10.5px; font-weight: 600; padding: 1px 8px; border-radius: var(--radius-pill);
}
.nl-chip.sent { background: rgba(16, 185, 129, 0.14); color: var(--ok); }
.nl-chip.failed { background: rgba(239, 68, 68, 0.14); color: var(--err); }
.nl-chip.pending { background: rgba(245, 158, 11, 0.14); color: var(--warn); }
.nl-chip.skipped { background: rgba(100, 116, 139, 0.16); color: var(--ink-600); }
.nl-time { font-size: 11px; color: var(--ink-500); margin-left: auto; }
.nl-err {
  width: 100%; font-size: 11px; color: var(--err); opacity: 0.85;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* ===== 资产市场: 工作区/远端只读展示 ===== */
.workdir {
  margin-top: 10px; padding: 9px 12px; border-radius: var(--radius-sm);
  background: var(--surface-sunken); font-size: 11.5px; color: var(--ink-700);
  display: flex; flex-direction: column; gap: 5px;
}
.workdir code {
  font-family: var(--font-mono); font-size: 11px; color: var(--ink-900);
  background: var(--surface); padding: 1px 6px; border-radius: 4px;
}
.workdir .muted { color: var(--ink-500); font-size: 11px; }

@media (max-width: 900px) {
  .set-layout { grid-template-columns: 1fr; }
  .set-toc { position: static; }
}
</style>
