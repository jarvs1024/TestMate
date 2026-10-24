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
          <!-- ⚠️ 错误只在下面的 mcp-bar 里显示一处 (以前 form-item 和 mcp-bar 各显示一遍) -->
          <el-form-item label="">
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

          <!-- 资产 code: 跟 MCP 配置里的连接器名保持一致 -->
          <el-form-item label="资产 code" required :error="codeFieldError" class="code-item">
            <el-input v-model="form.code" :disabled="mode === 'update'"
                      :placeholder="`${CODE_EXAMPLE} — 英文, dml- 开头`"
                      @blur="codeTouched = true" />
            <p class="hint">自动跟 MCP 配置里的连接器名保持一致</p>
          </el-form-item>
        </section>

        <section v-else class="up-sec">
          <div class="sec-h"><span class="sec-no">1</span>安装包<span class="sec-tip">必填</span></div>
          <el-form-item label="" :error="pkgError || pkgNameError">
            <input ref="fileInput" type="file" class="file-input"
                   accept=".zip,.tar.gz,.tgz" @change="onPickPackage" />
            <div v-if="pkgFile" class="file-list">
              <span class="file-chip">{{ pkgFile.name }}
                <b @click="clearPackage">×</b>
              </span>
            </div>
          </el-form-item>

          <!-- 包的要求: **每个形态不一样** —— 放上传区正下方, 别塞在角落小字里 -->
          <div class="pkg-req">
            <span class="pr-ic">📦</span>
            <span class="pr-txt">
              <b>{{ kind.label }}包要求</b>:
              包名以 <code>dml-</code> 开头 (如 dml-weekly-report.zip);
              <template v-if="kind.pkgNeed">{{ kind.pkgNeed }}。</template>
            </span>
          </div>

          <!-- 资产 code: 它是**包名派生的** —— 跟着 ① 走, 别孤零零放 ② -->
          <el-form-item label="资产 code" required :error="codeFieldError" class="code-item">
            <el-input v-model="form.code" :disabled="mode === 'update'"
                      :placeholder="`${CODE_EXAMPLE} — 英文, dml- 开头`"
                      @blur="codeTouched = true" />
            <p class="hint">选好安装包后自动跟包名保持一致</p>
          </el-form-item>

          <p class="hint">
            压缩包会在服务端解压后推送到 GitLab, 仓库里存的是解压后的文件。
          </p>

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
            <ul v-if="previewIssues.length" class="pv-list">
              <li v-for="(i, idx) in previewIssues" :key="'i' + idx">✗ {{ i }}</li>
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
            <b>怎么填</b>: {{ kind.guide }}
          </p>
          <div class="row-2">
            <el-form-item label="名称" required>
              <el-input v-model="form.name" maxlength="60" show-word-limit
                        placeholder="展示名, 中文即可 (卡片上的标题), 如 SSD 日志医生" />
            </el-form-item>
            <el-form-item label="图标">
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
              <p class="hint">
                自动分配, <b>不会跟现有资产重复</b>
                <template v-if="usedIcons.size">· 已用过的 {{ usedIcons.size }} 个不再提供</template>
              </p>
            </el-form-item>
          </div>

          <el-form-item label="一句话简介" required>
            <el-input v-model="form.summary" type="textarea" :rows="2" maxlength="200" show-word-limit
                      placeholder="一句话说清它干什么 (卡片副标题 + 搜索都用这句), 如 贴日志即可定位 assert 与超时点" />
          </el-form-item>

          <div class="row-2">
            <el-form-item label="版本 (semver)" :error="versionError">
              <el-input v-model="form.version" placeholder="语义化版本, 如 1.0.0" />
              <p v-if="mode === 'update'" class="hint">发新版本建议 +1 (如 1.0.0 → 1.1.0)</p>
            </el-form-item>
          </div>

          <!-- 适用场景: 详情页首屏就有这一块 → 别藏在进阶信息里 -->
          <el-form-item label="适用场景">
            <el-input v-model="form.use_when" type="textarea" :rows="2"
                      placeholder="什么时候该用它 (如: 拿到一段 dmesg 需要快速判断问题域)" />
          </el-form-item>

          <div class="row-2">
            <!-- 分类 (必填) 与适用范围 (选填) 并排; 各有稳定类名, e2e 不靠顺序定位 -->
            <el-form-item label="分类" required>
              <el-select v-model="form.category" class="sel-category" style="width:100%" filterable
                         @change="onCategoryChange">
                <el-option v-for="c in categories" :key="c.name" :value="c.name" :label="c.name">
                  <span>{{ c.name }}</span>
                  <span class="cat-desc">{{ c.desc }}</span>
                </el-option>
              </el-select>
            </el-form-item>
            <!-- 适用范围: 通用 (所有项目) 或某个项目特有 -->
            <el-form-item label="适用范围 (选填)">
              <el-select v-model="form.project" class="sel-project" style="width:100%">
                <el-option value="" label="通用 —— 所有项目都能用" />
                <el-option v-for="p in projectOptions" :key="p" :value="p"
                           :label="`${p} 项目 —— 只有 ${p} 项目用得上`" />
              </el-select>
              <p class="hint">
                资产是团队共有的, 但项目各有各的机台和流程 ——
                通用资产所有人都能用; 项目特有的会在卡片上标出来。
              </p>
            </el-form-item>
          </div>
        </section>

        <!-- ============ ③ 进阶信息 (默认收起) ============ -->
        <section class="up-sec">
          <button type="button" class="sec-toggle" @click="advOpen = !advOpen">
            <span class="sec-no">3</span>进阶信息
            <span class="sec-hint">可展开 · 补充适用场景与检索词</span>
            <span class="sec-caret">{{ advOpen ? '▾' : '▸' }}</span>
          </button>
          <div v-show="advOpen" class="adv-body">
            <div class="row-2">
              <el-form-item label="标签 (逗号分隔)">
                <el-input v-model="tagsText" placeholder="逗号分隔, 如 日志, 诊断, 速查 (卡片上显示)" />
              </el-form-item>
            </div>
            <el-form-item label="搜索关键词 (逗号分隔)">
              <el-input v-model="keywordsText" placeholder="同义词/技术词, 逗号分隔, 如 ssd, nvme, dmesg (搜不到时靠它)" />
            </el-form-item>
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
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { CircleCheck, CircleClose, Loading } from '@element-plus/icons-vue';
import { getAsset, getJob, retryJob, uploadAsset, updateAsset, type AssetItem, type AssetJob, type MarketKind } from '@/api/assets';
import { KIND_META } from './kindMeta';
import { MCP_TEMPLATE } from './mcpConfig';
import { CODE_EXAMPLE, useAssetUploadForm } from './useAssetUploadForm';

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
/** 上架要走审核 —— 提交完不是"已上架", 而是"已提交待审核" */
const pendingReview = ref(false);
/** 进阶信息默认收起 (大部分人只填基础信息) */
const advOpen = ref(false);

/**
 * 表单状态、校验与同步逻辑 —— 全在 composable 里.
 *
 * 为什么抽出去 (2026-10-25): 这些是最容易出 bug 的部分 (code 与包名同步 /
 * 缺项清单 / 图标不重复), 埋在组件里时**没法单测**, 只能靠 e2e 兜.
 */
const {
  form, tagsText, keywordsText, mcpConfigText, step, codeTouched,
  fileInput, pkgFile, preview, previewing, iconPanel, usedIcons,
  categories, projectOptions,
  isMcp, kind, mcpConfigError, codeFieldError,
  versionError, pkgError, pkgNameError,
  previewBad, previewIssues, iconChoices, missing, canSubmit,
  formatMcp, useMcpTemplate,
  onCategoryChange, chooseIcon, clearPackage, onPickPackage,
  chooseKind, reset,
} = useAssetUploadForm({
  mode: () => props.mode,
  asset: () => props.asset,
  initialKind: () => props.initialKind || '',
  open: () => props.modelValue,
});

watch(() => props.modelValue, (open) => {
  if (!open) return;
  reset();                 // 表单状态/校验/分类/项目/图标 全部重置
  job.value = null;
  submitting.value = false;
  pendingReview.value = false;
  advOpen.value = false;
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
    // ⚠️ 详细说明 / 不适用 / 安装步骤 / 设为精选 已经不在表单里填了 ——
    //    更新版本时**保留原值** (从 asset 取), 别让"没填"把老资产的字段清空。
    description: props.mode === 'update' ? (props.asset?.description || '') : '',
    use_when: form.use_when,
    not_for: props.mode === 'update' ? (props.asset?.not_for || '') : '',
    category: form.category,
    // 适用范围: 空 = 通用; 不在项目列表里的后端会归一成通用
    project: form.project || '',
    icon: form.icon || '🧩',
    tags: splitList(tagsText.value),
    keywords: splitList(keywordsText.value),
    install_steps: props.mode === 'update' ? [...(props.asset?.install_steps || [])] : [],
    // ⚠️ 权限声明不再由表单填 (2026-10-24) —— 固定空, 审核直接看包里的内容
    permissions: {},
    featured: props.mode === 'update' ? !!props.asset?.featured : false,
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
/* 「可展开」提示 —— 进阶信息默认收起, 得让人知道里面有东西 */
.sec-hint { font-size: 11px; font-weight: 500; color: var(--ink-500); }
.adv-body { padding-bottom: 4px; }

/* 分类下拉里的说明文字 (选项右侧灰字) */
.cat-desc {
  float: right; color: var(--ink-500); font-size: 11px;
  margin-left: 16px; max-width: 320px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}

.up-form :deep(.el-form-item) { margin-bottom: 14px; }
.row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; align-items: start; }

/* 包的要求条 —— 放在上传区正下方, 每个形态内容不同 */
.pkg-req {
  display: flex; align-items: flex-start; gap: 8px;
  padding: 8px 10px; margin: 0 0 8px;
  background: var(--surface-sunken); border: 1px solid var(--border);
  border-radius: var(--radius-sm); font-size: 11.5px; line-height: 1.7;
  color: var(--ink-700);
}
.pkg-req .pr-ic { font-size: 14px; line-height: 1.3; }
.pkg-req .pr-txt b { color: var(--ink-900); }
.pkg-req code {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--surface-soft); padding: 1px 4px; border-radius: 4px;
}

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
  max-height: 260px; overflow-y: auto;
  /* ⚠️ 不透明 —— 半透明毛玻璃底会透出下面的表单文字, 读不清 */
  background: linear-gradient(var(--surface), var(--surface)), var(--bg-base);
  border: 1px solid var(--border);
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
