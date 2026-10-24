<template>
  <el-drawer :model-value="modelValue" size="760px" direction="rtl"
             :title="mode === 'update' ? `更新资产 · ${asset?.name || ''}` : '上传新资产'"
             :close-on-click-modal="false" :with-header="true"
             class="up-drawer" @update:model-value="emit('update:modelValue', $event)">
    <template v-if="!job">
      <!-- ============ 第 ① 步: 选形态 (没定类型时先问一句) ============ -->
      <div v-if="step === 'pick'" class="kind-pick">
        <div class="kp-lead">
          <b>先选资产形态</b>
          <span>三种形态的配置方式完全不同 —— 选完直接进对应的表单。</span>
        </div>
        <button v-for="k in KIND_META" :key="k.value" type="button"
                class="kp-card" @click="chooseKind(k.value)">
          <span class="kp-ic">{{ k.icon }}</span>
          <span class="kp-main">
            <span class="kp-title">{{ k.label }}<i>{{ k.code }}</i></span>
            <span class="kp-tag">{{ k.tagline }}</span>
            <ul class="kp-needs">
              <li v-for="n in k.needs" :key="n">{{ n }}</li>
            </ul>
          </span>
          <span class="kp-go">开始配置 →</span>
        </button>
      </div>

      <el-form v-else label-position="top" class="up-form">
        <!-- 步骤条: 选形态 → 填配置 (形态在第 ① 步就定了, 这里只是显示进度) -->
        <div v-if="mode === 'create'" class="flow-steps">
          <span class="fs done">① 选形态</span>
          <span class="fs-arrow">→</span>
          <span class="fs on">② 填配置</span>
        </div>

        <!-- 类型头: 现在配的是哪种形态, 一眼可见, 也能随时换 -->
        <div class="type-bar">
          <span class="tb-ic">{{ kind.icon }}</span>
          <span class="tb-body">
            <b>{{ kind.label }}<i>{{ kind.code }}</i></b>
            <span class="tb-hint">{{ kind.formHint }}</span>
          </span>
          <button v-if="mode === 'create'" type="button" class="tb-change"
                  @click="step = 'pick'">更换类型</button>
        </div>
        <!-- ============ ① 连接器配置 / 安装包 (放最前) ============ -->
        <!-- 连接器是**配置型**资产: 只有一段 MCP 配置, 没有安装包也没有 README -->
        <section v-if="isMcp" class="up-sec">
          <div class="sec-h"><span class="sec-no">1</span>MCP 配置<span class="sec-tip">必填</span></div>
          <el-form-item label="" :error="mcpConfigError">
            <el-input v-model="mcpConfigText" type="textarea" :rows="11" class="mcp-json"
                      :placeholder="MCP_TEMPLATE" />
          </el-form-item>
          <div class="mcp-bar">
            <button type="button" class="mini-btn" @click="formatMcp">格式化</button>
            <button type="button" class="mini-btn" @click="useMcpTemplate">用模板</button>
            <span class="mcp-msg" :class="{ bad: !!mcpConfigError }">
              {{ mcpConfigError || '✓ 配置合法' }}
            </span>
          </div>
          <p class="hint">
            连接器是配置型资产 —— Agent 按这段配置来连 (mcpServers → 每个连接器给
            <code>command</code>+<code>args</code> 或 <code>url</code>)。
            详情页会原样展示这份配置, 用户照着加到自己的 MCP 配置里。
          </p>
        </section>

        <section v-else class="up-sec">
          <div class="sec-h"><span class="sec-no">1</span>安装包<span class="sec-tip">必填</span></div>
          <div class="row-2">
            <el-form-item label="" :error="pkgError || pkgNameError">
              <input ref="fileInput" type="file" class="file-input"
                     accept=".zip,.tar.gz,.tgz" @change="onPickPackage" />
              <div v-if="pkgFile" class="file-list">
                <span class="file-chip">{{ pkgFile.name }}
                  <b @click="clearPackage">×</b>
                </span>
              </div>
            </el-form-item>
            <div class="pkg-side">
              <p class="hint">
                压缩包会在服务端解压后推送到 GitLab, 仓库里存的是解压后的文件。<br />
                <template v-if="form.kind === 'plugin'">
                  插件包需含 <code>README.md</code> 和 <code>.qoder-plugin/plugin.json</code>。
                </template>
                <template v-else>
                  技能包需含 <code>SKILL.md</code>。
                </template>
              </p>
            </div>
          </div>

          <!-- 包体检: 选好包就当场验, 不用填完一整张表单才被 422 拦下 -->
          <div v-if="previewing" class="pv-box checking">正在体检安装包…</div>
          <div v-else-if="preview" class="pv-box" :class="previewBad ? 'bad' : 'ok'">
            <div class="pv-h">
              <span class="pv-icon">{{ previewBad ? '❌' : '✅' }}</span>
              <span>{{ previewBad ? '这个包装不上, 请调整后重试' : '体检通过' }}</span>
            </div>
            <div class="pv-meta mono">
              {{ preview.total_files }} 个文件
              · 展示文档 {{ preview.doc_file || '缺失' }}
              <template v-if="preview.installable">· 可一键安装</template>
              <template v-else>· {{ preview.block_reason }}</template>
            </div>
            <ul v-if="preview.issues.length" class="pv-list">
              <li v-for="(i, idx) in preview.issues" :key="'i' + idx">✗ {{ i }}</li>
            </ul>
            <ul v-if="preview.warnings.length" class="pv-list warn">
              <li v-for="(w, idx) in preview.warnings" :key="'w' + idx">⚠ {{ w }}</li>
            </ul>
            <details v-if="preview.files.length" class="pv-files">
              <summary>文件清单 ({{ preview.files.length }})</summary>
              <code v-for="f in preview.files" :key="f">{{ f }}</code>
            </details>
          </div>
        </section>

        <!-- ============ ② 基础信息 ============ -->
        <section class="up-sec">
          <div class="sec-h"><span class="sec-no">2</span>基础信息</div>
          <p class="guide">
            <b>三条约定</b>:
            <template v-if="isMcp">
              ① 资产 code = 连接器名 (英文, <code>dml-</code> 开头);
              ② 连接器<b>只有这段 MCP 配置</b> —— 没有安装包, 也没有 README;
              ③ 图标会自动分配, 且不跟现有资产重复 —— 都可以手动改。
            </template>
            <template v-else>
              ① 资产 code = 安装包名 = 插件名 (英文, <code>dml-</code> 开头);
              ② 校验规则按形态来
              ({{ form.kind === 'plugin' ? '插件要 README.md + plugin.json' : '技能要 SKILL.md' }});
              ③ 图标会自动分配, 且不跟现有资产重复 —— 都可以手动改。
            </template>
          </p>
          <div class="row-2">
            <el-form-item label="名称" required>
              <el-input v-model="form.name" maxlength="60" show-word-limit
                        placeholder="展示名, 中文即可 (卡片上的标题), 如 SSD 日志医生" />
            </el-form-item>
            <el-form-item label="图标" :error="iconError">
              <div class="icon-pick">
                <button type="button" class="icon-btn" @click="iconPanel = !iconPanel">
                  <span class="icon-cur">{{ form.icon || '🧩' }}</span>
                  <span class="icon-caret">▾</span>
                </button>
                <div v-if="iconPanel" class="icon-panel">
                  <button v-for="ic in iconChoices" :key="ic" type="button"
                          class="icon-cell" :class="{ on: ic === form.icon }"
                          @click="chooseIcon(ic)">{{ ic }}</button>
                </div>
              </div>
            </el-form-item>
          </div>

          <el-form-item label="一句话简介" required>
            <el-input v-model="form.summary" type="textarea" :rows="2" maxlength="200" show-word-limit
                      placeholder="一句话说清它干什么 (卡片副标题 + 搜索都用这句), 如 贴日志即可定位 assert 与超时点" />
          </el-form-item>

          <div class="row-2">
            <el-form-item label="资产 code" required :error="codeError">
              <el-input v-model="form.code" :disabled="mode === 'update'"
                        :placeholder="`${CODE_EXAMPLE} — 英文, dml- 开头`"
                        @blur="codeTouched = true" />
              <p v-if="codePkgMismatch" class="hint warn-hint">
                ⚠ 与安装包名不一致 (包名是 {{ pkgBaseName }}) —— 建议保持一致, 免得装出来对不上
              </p>
            </el-form-item>
            <el-form-item label="版本 (semver)" :error="versionError">
              <el-input v-model="form.version" placeholder="语义化版本, 如 1.0.0" />
              <p v-if="mode === 'update'" class="hint">发新版本建议 +1 (如 1.0.0 → 1.1.0)</p>
            </el-form-item>
          </div>

          <!-- 分类: 抽屉里唯一的下拉 —— 其它选项都是固定的 -->
          <el-form-item label="分类" required>
            <el-select v-model="form.category" style="width:100%" filterable
                       @change="onCategoryChange">
              <el-option v-for="c in categories" :key="c.name" :value="c.name" :label="c.name">
                <span>{{ c.name }}</span>
                <span class="cat-desc">{{ c.desc }}</span>
              </el-option>
            </el-select>
          </el-form-item>
        </section>

        <!-- ============ ③ 进阶信息 (默认收起) ============ -->
        <section class="up-sec">
          <button type="button" class="sec-toggle" @click="advOpen = !advOpen">
            <span class="sec-no">3</span>进阶信息
            <span class="sec-caret">{{ advOpen ? '▾' : '▸' }}</span>
          </button>
          <div v-show="advOpen" class="adv-body">
            <el-form-item label="详细说明">
              <el-input v-model="form.description" type="textarea" :rows="3"
                        :placeholder="isMcp
                          ? '补充说明 —— 会显示在详情页 (连接器没有 README)'
                          : '会存到 GitLab 的 README.md —— 写清怎么用、前置条件、示例'" />
            </el-form-item>
            <div class="row-2">
              <el-form-item label="适用场景">
                <el-input v-model="form.use_when" type="textarea" :rows="2"
                          placeholder="什么时候该用它 (如: 拿到一段 dmesg 需要快速判断问题域)" />
              </el-form-item>
              <el-form-item label="不适用">
                <el-input v-model="form.not_for" type="textarea" :rows="2"
                          placeholder="什么时候**别**用它 (如: 需要逐行精确解析完整 trace)" />
              </el-form-item>
            </div>
            <div class="row-2">
              <el-form-item label="标签 (逗号分隔)">
                <el-input v-model="tagsText" placeholder="逗号分隔, 如 日志, 诊断, 速查 (卡片上显示)" />
              </el-form-item>
              <el-form-item label="搜索关键词 (逗号分隔)">
                <el-input v-model="keywordsText" placeholder="同义词/技术词, 逗号分隔, 如 ssd, nvme, dmesg (搜不到时靠它)" />
              </el-form-item>
            </div>
            <!-- 安装步骤: 只对「有安装包」的形态有意义 —— 连接器没有包可装 -->
            <el-form-item v-if="!isMcp" label="安装步骤 (每行一步)">
              <el-input v-model="stepsText" type="textarea" :rows="2"
                        placeholder="每行一步, 如:&#10;将 xxx 复制到 Agent 的 skills 目录&#10;重启 Agent 会话" />
              <p class="hint">包里一般已有 SKILL.md / README.md, 一般不用填。</p>
            </el-form-item>
            <el-form-item label="">
              <el-checkbox v-model="form.featured">设为精选 (市场首页优先展示)</el-checkbox>
            </el-form-item>
            <p class="hint perm-note">
              权限声明不在这里填了 —— 审核会直接看包里的内容;
              有特殊权限需求, 请在包的 README 里写清楚。
            </p>
          </div>
        </section>
      </el-form>
    </template>

    <!-- 任务进度: staged(已存本地) → syncing(推送中) → pushed(已同步) / failed -->
    <div v-else class="job-box">
      <div class="job-status">
        <el-icon v-if="job.status === 'pushed'" color="var(--ok)"><CircleCheck /></el-icon>
        <el-icon v-else-if="job.status === 'failed'" color="var(--err)"><CircleClose /></el-icon>
        <el-icon v-else class="is-loading"><Loading /></el-icon>
        <div>
          <div class="job-title">
            {{ job.status === 'pushed' ? (pendingReview ? '已提交, 等待管理员审核' : '已同步到 GitLab')
               : job.status === 'failed' ? '同步失败'
               : job.status === 'staged' ? '已保存到本地, 准备同步…'
               : '正在推送到 GitLab…' }}
          </div>
          <div v-if="job.status === 'pushed'" class="job-sub mono">
            commit {{ job.commit_sha.slice(0, 12) }} · {{ job.git_path }}
          </div>
          <div v-if="job.status === 'pushed' && pendingReview" class="job-sub">
            文件已推送, 管理员审核通过后才会出现在市场里
          </div>
          <div v-else-if="job.status === 'staged'" class="job-sub">
            文件已落到本地工作区, 后台正在 commit + push
          </div>
        </div>
      </div>
      <pre v-if="job.error" class="job-err">{{ job.error }}</pre>
      <p v-if="job.status === 'failed'" class="job-hint">
        资产仍在本机工作区, 只是没推到 GitLab. 修掉上面的问题后可重试。
      </p>
      <p v-else class="job-hint">前端列表会在同步完成后自动刷新。</p>
    </div>

    <template #footer>
      <template v-if="!job && step === 'form'">
        <!-- 缺什么一次说清, 不用点一次报一个 -->
        <div class="foot-bar">
          <div class="foot-left">
            <template v-if="missing.length">
              <span class="foot-warn">还缺: {{ missing.join('、') }}</span>
            </template>
            <span v-else class="foot-ok">✓ 该填的都填了</span>
          </div>
          <div class="foot-right">
            <el-button @click="visible = false">取消</el-button>
            <el-button type="primary" :loading="submitting" :disabled="!canSubmit"
                       @click="submit">
              {{ mode === 'update' ? '提交新版本' : '上架' }}
            </el-button>
          </div>
        </div>
      </template>
      <!-- 还在第 ① 步 (选形态) —— 没东西可提交, 只给个「返回」 -->
      <div v-else-if="!job" class="foot-bar">
        <div class="foot-left">
          <span class="foot-hint">先选一种形态, 就能进对应的配置表单</span>
        </div>
        <div class="foot-right">
          <el-button @click="visible = false">取消</el-button>
        </div>
      </div>
      <template v-else-if="job.status === 'failed'">
        <el-button @click="visible = false">关闭</el-button>
        <el-button type="primary" :loading="submitting" @click="doRetry">重试同步</el-button>
      </template>
      <el-button v-else type="primary" @click="close">{{ job.status === 'pushed' ? '完成' : '关闭' }}</el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { CircleCheck, CircleClose, Loading } from '@element-plus/icons-vue';
import { getAsset, getJob, listAssets, listCategories, previewPackage, retryJob, uploadAsset, updateAsset, type AssetItem, type AssetJob, type MarketKind, type PackagePreview } from '@/api/assets';
import {
  CODE_EXAMPLE, CODE_PREFIX, GENERAL_ICONS, ICON_POOLS,
  codeFromPackageName, pickIcon, validateCode, validatePackageName,
} from './assetForm';
import { KIND_META, kindMeta } from './kindMeta';
import { MCP_TEMPLATE, formatMcpConfig, parseMcpConfig } from './mcpConfig';

const props = defineProps<{
  modelValue: boolean;
  mode: 'create' | 'update';
  asset?: AssetItem | null;
  /** 入口选定的形态 (市场页下拉选完传进来) —— 空就先进第 ① 步让人选 */
  initialKind?: MarketKind | '';
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void;
  (e: 'done'): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
});

const submitting = ref(false);
const job = ref<AssetJob | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const pkgFile = ref<File | null>(null);
const preview = ref<PackagePreview | null>(null);
const previewing = ref(false);
/** 上架要走审核 —— 提交完不是"已上架", 而是"已提交待审核" */
const pendingReview = ref(false);
/** 进阶信息默认收起 (大部分人只填基础信息) */
const advOpen = ref(false);
/** 图标选择面板 */
const iconPanel = ref(false);
/** 现有资产用过的图标 —— 自动分配时避开, 免得卡片上图标重复 */
const usedIcons = ref<Set<string>>(new Set());
/** 分类表 (后端下发) —— 上传/更新时只能从里面选 */
const categories = ref<{ name: string; slug: string; desc?: string; total: number }[]>([]);

const form = reactive({
  code: CODE_PREFIX, kind: 'skill' as MarketKind, name: '', version: '1.0.0',
  summary: '', description: '', use_when: '', not_for: '', category: '', icon: '🧩',
  featured: false, tags: [] as string[], files: [] as File[],
  install_steps: [] as string[],
});
const tagsText = ref('');
/** 连接器 (mcp) 的 MCP 配置 (JSON 文本) */
const mcpConfigText = ref('');
const keywordsText = ref('');
const stepsText = ref('');

/** 连接器形态: 只有一段 MCP 配置, 没有安装包也没有 README */
const isMcp = computed(() => form.kind === 'mcp');
/** 当前形态的元信息 (图标 / 需要准备什么) */
const kind = computed(() => kindMeta(form.kind));
/** 抽屉里的第几步: pick = 选形态, form = 填配置 */
const step = ref<'pick' | 'form'>('form');
/** MCP 配置的实时校验 (规则与后端一致) */
const mcpParsed = computed(() => parseMcpConfig(mcpConfigText.value));
const mcpConfigError = computed(() => {
  if (!isMcp.value) return '';
  return mcpParsed.value.ok ? '' : mcpParsed.value.error;
});
function formatMcp() {
  mcpConfigText.value = formatMcpConfig(mcpConfigText.value);
}
function useMcpTemplate() {
  mcpConfigText.value = MCP_TEMPLATE;
}

/** 体检结论: 包装不上 (解包失败 **或** 有问题项 —— 比如缺 SKILL.md) */
const previewBad = computed(() => {
  const p = preview.value;
  if (!p) return false;
  return !p.ok || p.issues.length > 0;
});

/** 图标可选范围: 分类池 + 通用池 */
const iconChoices = computed(() => {
  const pool = ICON_POOLS[form.category] || [];
  return Array.from(new Set([...pool, ...GENERAL_ICONS]));
});

// ---------- 校验 ----------
/** code 动过才提示 —— 刚打开时预填的 "dml-" 还没填完, 立刻标红只会碍眼 */
const codeTouched = ref(false);
const codeError = computed(() => {
  if (props.mode === 'update' || !codeTouched.value) return '';
  return validateCode(form.code);
});
const versionError = computed(() => {
  const v = (form.version || '').trim();
  if (!v) return '版本必填';
  if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(v)) return '版本格式应为 1.0.0';
  return '';
});
const pkgError = computed(() => (pkgFile.value ? '' : '请选择安装包'));
/** 安装包名 (去掉扩展名) —— 跟 code 应该一致 */
const pkgBaseName = computed(() => codeFromPackageName(pkgFile.value?.name || ''));
/** code 跟包名不一致 (软提示, 不拦提交) */
const codePkgMismatch = computed(() => {
  if (props.mode === 'update') return false;
  if (!pkgBaseName.value || !form.code.trim()) return false;
  return form.code.trim() !== pkgBaseName.value;
});
/** 安装包名本身的合法性 (dml- 开头 + 英文 + 合法扩展名) */
const pkgNameError = computed(() =>
  pkgFile.value ? validatePackageName(pkgFile.value.name) : '');
const iconError = computed(() => '');

/** 缺什么 —— 一次说清, 别让人点一次报一个 */
const missing = computed(() => {
  const out: string[] = [];
  if (isMcp.value) {
    // 连接器: 要配置, 不要包
    if (mcpConfigError.value) out.push('MCP 配置');
  } else if (!pkgFile.value) {
    out.push('安装包');
  }
  if (!form.name.trim()) out.push('名称');
  if (!form.summary.trim()) out.push('一句话简介');
  if (props.mode === 'create') {
    const c = validateCode(form.code);
    if (c) out.push('资产 code');
  }
  if (!form.category) out.push('分类');
  if (versionError.value) out.push('版本');
  if (pkgNameError.value) out.push('安装包名');
  return out;
});
const canSubmit = computed(() =>
  missing.value.length === 0
  && (isMcp.value || (!previewBad.value && !pkgNameError.value)));

async function loadCategories() {
  if (categories.value.length) return;
  try {
    const r = await listCategories();
    categories.value = (r?.items || []) as typeof categories.value;
  } catch {
    /* 拿不到就退回空列表 —— 后端还会再归一成「其他」 */
  }
}

/** 拉现有资产的图标 —— 自动分配时避开重复 */
async function loadUsedIcons() {
  try {
    const r = await listAssets({ limit: 500 });
    usedIcons.value = new Set(
      (r?.items || []).map((i: AssetItem) => (i.icon || '').trim()).filter(Boolean),
    );
  } catch {
    usedIcons.value = new Set();
  }
}

/** 自动分配图标 (避开已被用掉的) */
function autoIcon() {
  form.icon = pickIcon({
    category: form.category,
    name: form.name,
    summary: form.summary,
    used: usedIcons.value,
  });
}

function onCategoryChange() {
  autoIcon();
}

function chooseIcon(ic: string) {
  form.icon = ic;
  iconTouched.value = true;   // 用户手选过 → 后面名字/分类变了也别乱改
  iconPanel.value = false;
}

watch(() => props.modelValue, (open) => {
  if (!open) return;
  loadCategories();
  loadUsedIcons();
  job.value = null;
  submitting.value = false;
  pkgFile.value = null;
  preview.value = null;
  previewing.value = false;
  pendingReview.value = false;
  advOpen.value = false;
  iconPanel.value = false;
  codeTouched.value = false;
  if (fileInput.value) fileInput.value.value = '';
  const a = props.asset;
  if (props.mode === 'update' && a) {
    step.value = 'form';          // 更新版本: 直接进表单, 不选形态 (类型不可改)
    form.code = a.code; form.kind = a.kind; form.name = a.name; form.version = a.version;
    form.summary = a.summary; form.description = a.description;
    form.use_when = a.use_when; form.not_for = a.not_for;
    form.category = a.category; form.icon = a.icon; form.featured = a.featured;
    // 连接器: 带出老配置 (发布新版本 = 只改这段配置)
    mcpConfigText.value = a.mcp_config ? JSON.stringify(a.mcp_config, null, 2) : '';
    form.tags = [...a.tags]; form.install_steps = [...a.install_steps];
    form.files = [];
    tagsText.value = (a.tags || []).join(', ');
    keywordsText.value = (a.keywords || []).join(', ');
    stepsText.value = (a.install_steps || []).join('\n');
  } else {
    // 新建: 形态在入口就选好了 (initialKind) —— 直接进对应表单;
    // 没带形态 (别处打开) 就先走第 ① 步让人选, 别再默认「技能」。
    const k = (props.initialKind || 'skill') as MarketKind;
    Object.assign(form, {
      code: CODE_PREFIX, kind: k, name: '', version: '1.0.0', summary: '',
      description: '', use_when: '', not_for: '', category: '', icon: '🧩',
      featured: false, tags: [], files: [], install_steps: [],
    });
    step.value = props.initialKind ? 'form' : 'pick';
    tagsText.value = ''; keywordsText.value = ''; stepsText.value = '';
    mcpConfigText.value = '';
  }
});

/** 第 ① 步: 选定形态 → 直接进对应表单 */
function chooseKind(k: MarketKind) {
  form.kind = k;
  step.value = 'form';
}

async function onPickPackage(e: Event) {
  const input = e.target as HTMLInputElement;
  pkgFile.value = input.files?.[0] ?? null;
  // ⚠️ 包名 = 资产 code = 插件名 → 选完包就把 code 带出来 (省得再手打一遍)
  const derived = codeFromPackageName(pkgFile.value?.name || '');
  if (derived && props.mode === 'create' && !codeTouched.value) {
    form.code = derived;
  }
  await runPreview();
}

function clearPackage() {
  pkgFile.value = null;
  preview.value = null;
  if (fileInput.value) fileInput.value.value = '';
}

/** 体检: 走服务端与真实上传完全相同的解包路径, 结论就是提交后的结论 */
async function runPreview() {
  if (!pkgFile.value) return;
  previewing.value = true;
  preview.value = null;
  try {
    preview.value = await previewPackage(pkgFile.value, form.kind);
  } catch (e: any) {
    preview.value = {
      ok: false, filename: pkgFile.value.name, size_bytes: pkgFile.value.size,
      kind: form.kind, total_files: 0, files: [], doc_file: '',
      has_skill_md: false, has_plugin_manifest: false, has_mcp_config: false,
      installable: false, block_reason: '',
      issues: ['体检失败: ' + (e?.response?.data?.detail || e?.message)],
      warnings: [],
    };
  } finally {
    previewing.value = false;
  }
}

// 类型变了, 体检结论也得重算 (skill 要 SKILL.md, plugin 要 plugin.json)
watch(() => form.kind, () => {
  if (pkgFile.value) runPreview();
});

/**
 * 连接器: MCP 配置里第一个连接器的名字 → 资产 code (省得手打一遍).
 *
 * 只在用户**没自己动过** code 时才填 —— 填了就别再覆盖人家的输入。
 * 名字不合法 (中文/特殊字符) 就跳过, 让用户自己填。
 */
watch(() => mcpConfigText.value, () => {
  if (props.mode !== 'create' || codeTouched.value || !isMcp.value) return;
  const p = mcpParsed.value;
  if (!p.ok) return;
  const names = Object.keys((p.config as any)?.mcpServers || {});
  const slug = (names[0] || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  if (!slug) return;
  form.code = slug.startsWith(CODE_PREFIX) ? slug : CODE_PREFIX + slug;
});

// 名字/简介/分类变了 → 图标跟着重新猜 (但用户手选过就别乱动)
const iconTouched = ref(false);
watch(() => [form.name, form.summary], () => {
  if (!iconTouched.value) autoIcon();
});

function splitList(s: string): string[] {
  return s.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
}

async function submit() {
  codeTouched.value = true;
  if (missing.value.length) {
    ElMessage.warning('还缺: ' + missing.value.join('、'));
    return;
  }
  submitting.value = true;
  const payload = {
    code: form.code.trim(),
    kind: form.kind,
    name: form.name.trim(),
    version: form.version.trim() || '1.0.0',
    summary: form.summary.trim(),
    description: form.description,
    use_when: form.use_when,
    not_for: form.not_for,
    category: form.category,
    icon: form.icon || '🧩',
    tags: splitList(tagsText.value),
    keywords: splitList(keywordsText.value),
    install_steps: splitList(stepsText.value),
    // ⚠️ 权限声明不再由表单填 (2026-10-24) —— 固定空, 审核直接看包里的内容
    permissions: {},
    featured: form.featured,
    // 连接器: 只传 MCP 配置, 不传包
    mcp_config: isMcp.value ? mcpConfigText.value : '',
    package: isMcp.value ? null : pkgFile.value,
    files: [] as File[],
  };
  try {
    const created = props.mode === 'update'
      ? await updateAsset(form.code, payload)
      : await uploadAsset(payload);
    job.value = created;
    await poll(created.id);
  } catch (e: any) {
    ElMessage.error('提交失败: ' + (e?.response?.data?.detail || e?.message));
    submitting.value = false;
  }
}

async function poll(id: number) {
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      const j = await getJob(id);
      job.value = j;
      if (j.status === 'pushed' || j.status === 'failed') {
        submitting.value = false;
        if (j.status === 'pushed') {
          // 上架可能要过审核 —— 查一下资产现在的状态再给提示
          try {
            const a = await getAsset(j.code);
            pendingReview.value = a.publish_status === 'pending';
          } catch {
            pendingReview.value = false;
          }
          ElMessage.success(
            pendingReview.value
              ? `${j.code} 已提交, 等待管理员审核`
              : `${j.code} 已同步到 GitLab`,
          );
          emit('done');
        } else {
          ElMessage.error('同步到 GitLab 失败');
        }
        return;
      }
    } catch {
      /* 轮询失败继续等 */
    }
  }
  submitting.value = false;
}

async function doRetry() {
  if (!job.value) return;
  submitting.value = true;
  try {
    job.value = await retryJob(job.value.id);
    await poll(job.value.id);
  } catch (e: any) {
    ElMessage.error('重试失败: ' + (e?.response?.data?.detail || e?.message));
    submitting.value = false;
  }
}

function close() {
  visible.value = false;
  if (fileInput.value) fileInput.value.value = '';
}
</script>

<style scoped>
/* ===== 抽屉 ===== */
.up-drawer :deep(.el-drawer__body) { padding-top: 4px; }

/* ===== 第 ① 步: 选形态 ===== */
.kind-pick { padding: 4px 2px 0; }
.kp-lead {
  display: flex; flex-direction: column; gap: 2px;
  margin-bottom: 12px; font-size: 12.5px; color: var(--ink-500);
}
.kp-lead b { font-size: 14px; color: var(--ink-900); }
.kp-card {
  display: flex; align-items: flex-start; gap: 12px; width: 100%;
  padding: 12px 14px; margin-bottom: 10px; text-align: left;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-card); cursor: pointer; font-family: inherit;
  transition: all 0.15s ease;
}
.kp-card:hover { border-color: var(--primary); box-shadow: var(--shadow-md); }
.kp-ic { font-size: 26px; line-height: 1.2; }
.kp-main { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 0; }
.kp-title { font-size: 14px; font-weight: 700; color: var(--ink-900); }
.kp-title i {
  font-style: normal; font-size: 11px; font-weight: 500; color: var(--ink-500);
  margin-left: 6px;
}
.kp-tag { font-size: 12px; color: var(--ink-700); line-height: 1.5; }
.kp-needs { margin: 2px 0 0; padding-left: 18px; }
.kp-needs li { font-size: 11.5px; color: var(--ink-500); line-height: 1.7; }
.kp-go { align-self: center; font-size: 12.5px; color: var(--ink-500); white-space: nowrap; }
.kp-card:hover .kp-go { color: var(--primary); }

/* ===== 步骤条 + 类型头 ===== */
.flow-steps {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--ink-500); margin-bottom: 10px;
}
.flow-steps .fs.on { color: var(--primary); font-weight: 700; }
.flow-steps .fs.done { color: var(--ok); }
.flow-steps .fs-arrow { color: var(--ink-500); }
.type-bar {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px; margin-bottom: 14px;
  background: var(--surface-sunken); border: 1px solid var(--border);
  border-radius: var(--radius-card);
}
.tb-ic { font-size: 22px; line-height: 1; }
.tb-body { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.tb-body b { font-size: 13.5px; color: var(--ink-900); }
.tb-body i {
  font-style: normal; font-size: 11px; font-weight: 500; color: var(--ink-500);
  margin-left: 6px;
}
.tb-hint { font-size: 11.5px; color: var(--ink-500); }
.tb-change {
  background: var(--surface); border: 1px solid var(--border);
  color: var(--ink-700); border-radius: var(--radius-pill);
  padding: 4px 12px; font-size: 11.5px; cursor: pointer; font-family: inherit;
}
.tb-change:hover { border-color: var(--primary); color: var(--primary); }

/* ===== 分区 ===== */
.up-sec {
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 12px 14px 2px; margin-bottom: 14px; background: var(--surface);
}
.sec-h, .sec-toggle {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 700; color: var(--ink-900); margin-bottom: 10px;
}
.sec-toggle {
  width: 100%; background: none; border: 0; padding: 0 0 10px;
  cursor: pointer; font-family: inherit; text-align: left;
}
.sec-no {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px; border-radius: 50%;
  background: var(--primary); color: #fff; font-size: 11px; font-weight: 700;
}
.sec-tip {
  font-size: 10.5px; font-weight: 600; color: var(--err);
  background: rgba(239, 68, 68, 0.1); padding: 1px 6px; border-radius: var(--radius-pill);
}
.sec-caret { margin-left: auto; color: var(--ink-500); font-size: 11px; }
.adv-body { padding-bottom: 4px; }

/* 分类下拉里的说明文字 (选项右侧灰字) */
.cat-desc {
  float: right; color: var(--ink-500); font-size: 11px;
  margin-left: 16px; max-width: 320px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}

.up-form :deep(.el-form-item) { margin-bottom: 14px; }
.row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; align-items: start; }
.pkg-side { padding-top: 2px; }

/* ===== 图标选择 ===== */
.icon-pick { position: relative; }
.icon-btn {
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--surface-sunken); padding: 5px 10px; cursor: pointer;
  font-family: inherit; font-size: 16px; min-width: 74px;
}
.icon-caret { font-size: 10px; color: var(--ink-500); }
.icon-panel {
  position: absolute; z-index: 20; top: 38px; left: 0;
  display: grid; grid-template-columns: repeat(8, 1fr); gap: 2px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 6px; box-shadow: var(--shadow-md);
}
.icon-cell {
  width: 26px; height: 26px; border: 0; background: none; cursor: pointer;
  border-radius: 4px; font-size: 15px; line-height: 1;
}
.icon-cell:hover { background: var(--surface-sunken); }
.icon-cell.on { background: rgba(59, 130, 246, 0.16); }

.hint { margin: 2px 0 0; font-size: 11.5px; color: var(--ink-500); }
/* ===== MCP 配置编辑器 ===== */
.mcp-json :deep(textarea) {
  font-family: var(--font-mono); font-size: 12px; line-height: 1.6;
}
.mcp-bar { display: flex; align-items: center; gap: 8px; margin: 2px 0 6px; }
.mcp-bar button {
  background: var(--surface-sunken); border: 1px solid var(--border);
  color: var(--ink-700); border-radius: var(--radius-pill);
  padding: 3px 12px; font-size: 11.5px; cursor: pointer; font-family: inherit;
}
.mcp-bar button:hover { border-color: var(--primary); color: var(--primary); }
.mcp-msg { font-size: 11.5px; color: var(--ok); }
.mcp-msg.bad { color: var(--err); }
.warn-hint { color: var(--warn); }
.guide {
  margin: 0 0 12px; padding: 8px 10px; font-size: 11.5px; line-height: 1.7;
  color: var(--ink-700); background: var(--surface-sunken); border-radius: var(--radius-sm);
}
.guide code {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--surface); padding: 1px 5px; border-radius: 4px;
}
.perm-note { margin: 0 0 10px; padding: 7px 9px; background: var(--surface-sunken);
  border-radius: var(--radius-sm); line-height: 1.6; }
.file-input { display: block; margin-bottom: 8px; font-size: 12.5px; }
.file-list { display: flex; flex-wrap: wrap; gap: 6px; }
.hint code {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--surface-sunken); padding: 1px 5px; border-radius: 4px;
}
.file-chip {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; font-family: var(--font-mono);
  background: var(--surface-sunken); color: var(--ink-700);
  padding: 3px 8px; border-radius: var(--radius-sm);
}
.file-chip b { cursor: pointer; color: var(--ink-500); }
.file-chip b:hover { color: var(--err); }

/* ===== 底部固定条 ===== */
.foot-bar { display: flex; align-items: center; gap: 12px; }
.foot-left { flex: 1; min-width: 0; }
.foot-warn { font-size: 11.5px; color: var(--warn); }
.foot-ok { font-size: 11.5px; color: var(--ok); }
.foot-right { display: flex; gap: 8px; }

.job-box { padding: 8px 0; }
.job-status { display: flex; align-items: center; gap: 12px; }
.job-status .el-icon { font-size: 26px; }
.job-title { font-size: 14px; font-weight: 700; color: var(--ink-900); }
.job-sub { font-size: 11px; color: var(--ink-500); margin-top: 3px; }
.job-err {
  margin-top: 12px; padding: 10px; background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25); border-radius: var(--radius-sm);
  font-size: 11.5px; color: var(--err); white-space: pre-wrap; word-break: break-all;
}
.job-hint { margin-top: 10px; font-size: 11.5px; color: var(--ink-500); }

/* ===== 包体检结果 ===== */
.pv-box {
  margin-top: 10px; padding: 9px 12px; border-radius: var(--radius-sm);
  font-size: 12px; border: 1px solid var(--border); background: var(--surface-sunken);
}
.pv-box.checking { color: var(--ink-500); }
.pv-box.ok { background: rgba(16, 185, 129, 0.07); border-color: rgba(16, 185, 129, 0.28); }
.pv-box.bad { background: rgba(239, 68, 68, 0.07); border-color: rgba(239, 68, 68, 0.3); }
.pv-h { display: flex; align-items: center; gap: 6px; font-weight: 700; color: var(--ink-900); }
.pv-box.ok .pv-h { color: var(--ok); }
.pv-box.bad .pv-h { color: var(--err); }
.pv-icon { font-size: 13px; }
.pv-meta { margin-top: 4px; font-size: 11px; color: var(--ink-500); }
.pv-list { margin: 6px 0 0; padding-left: 16px; font-size: 11.5px; color: var(--err); }
.pv-list.warn { color: var(--warn); }
.pv-files { margin-top: 6px; font-size: 11px; color: var(--ink-500); }
.pv-files summary { cursor: pointer; }
.pv-files code {
  display: block; font-family: var(--font-mono); font-size: 10.5px;
  color: var(--ink-700); padding: 1px 0;
}
</style>
