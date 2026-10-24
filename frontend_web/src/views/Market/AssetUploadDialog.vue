<template>
  <el-dialog v-model="visible" :title="mode === 'update' ? `更新资产 · ${asset?.name || ''}` : '上传新资产'"
             width="640px" :close-on-click-modal="false">
    <el-form v-if="!job" label-position="top" class="up-form">
      <div class="row-2">
        <el-form-item label="类型" required>
          <el-select v-model="form.kind" style="width:100%" :disabled="mode === 'update'">
            <el-option value="plugin" label="插件 plugin" />
            <el-option value="skill" label="技能 skill" />
            <el-option value="mcp" label="连接器 mcp（只读不装）" />
          </el-select>
        </el-form-item>
        <el-form-item label="分类" required>
          <!-- ⚠️ 只给**分类表**里的选项 (不再 allow-create) ——
               自定义分类在前端没有筛选 chip, 筛不出来 (孤儿分类);
               实在归不进去就选「其他」. -->
          <el-select v-model="form.category" style="width:100%" filterable>
            <el-option v-for="c in categories" :key="c.name" :value="c.name" :label="c.name">
              <span>{{ c.name }}</span>
              <span class="cat-desc">{{ c.desc }}</span>
            </el-option>
          </el-select>
        </el-form-item>
      </div>

      <div class="row-2">
        <el-form-item label="资产 code" required>
          <el-input v-model="form.code" :disabled="mode === 'update'"
                    placeholder="小写字母/数字/连字符, 如 ssd-log-doctor" />
        </el-form-item>
        <el-form-item label="版本 (semver)" required>
          <el-input v-model="form.version" placeholder="1.0.0" />
        </el-form-item>
      </div>

      <div class="row-2">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="SSD 日志医生" />
        </el-form-item>
        <el-form-item label="图标">
          <el-input v-model="form.icon" placeholder="🩺" />
        </el-form-item>
      </div>

      <el-form-item label="一句话简介" required>
        <el-input v-model="form.summary" type="textarea" :rows="2"
                  placeholder="贴日志即可定位 assert 与超时点" />
      </el-form-item>

      <el-form-item label="详细说明">
        <el-input v-model="form.description" type="textarea" :rows="3"
                  placeholder="会存到 GitLab 的 README.md" />
      </el-form-item>

      <div class="row-2">
        <el-form-item label="适用场景">
          <el-input v-model="form.use_when" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="不适用">
          <el-input v-model="form.not_for" type="textarea" :rows="2" />
        </el-form-item>
      </div>

      <el-form-item label="标签 (逗号分隔)">
        <el-input v-model="tagsText" placeholder="日志, 诊断, 速查" />
      </el-form-item>

      <el-form-item label="权限声明">
        <div class="perm-editor">
          <el-input v-model="permRead" placeholder="读取文件, 如 ~/lab/logs/**" />
          <el-input v-model="permExec" placeholder="执行命令, 如 nvme, fio" />
          <el-input v-model="permNet" placeholder="访问网络, 如 git.internal:443" />
          <el-input v-model="permSecret" placeholder="读取凭据, 如 GITLAB_TOKEN" />
          <p class="hint">⚠️ 这是市场区别于普通插件目录的核心, 审核与安装都会看这里。如实填写。</p>
        </div>
      </el-form-item>

      <el-form-item label="安装步骤 (每行一步)">
        <el-input v-model="stepsText" type="textarea" :rows="3"
                  placeholder="将 xxx 复制到宿主 skills 目录&#10;重启 Agent 会话" />
      </el-form-item>

      <el-form-item label="安装包 (zip / tar.gz)">
        <input ref="fileInput" type="file" class="file-input"
               accept=".zip,.tar.gz,.tgz" @change="onPickPackage" />
        <div v-if="pkgFile" class="file-list">
          <span class="file-chip">{{ pkgFile.name }}
            <b @click="clearPackage">×</b>
          </span>
        </div>
        <p class="hint">
          压缩包会在服务端解压后推送到 GitLab, 仓库里存的是解压后的文件.
          skill 包需含 <code>SKILL.md</code>, plugin 包需含 <code>README.md</code>.
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
      </el-form-item>
    </el-form>

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
      <template v-if="!job">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" :disabled="previewBad" @click="submit">
          {{ mode === 'update' ? '提交新版本' : '上架' }}
        </el-button>
      </template>
      <template v-else-if="job.status === 'failed'">
        <el-button @click="visible = false">关闭</el-button>
        <el-button type="primary" :loading="submitting" @click="doRetry">重试同步</el-button>
      </template>
      <el-button v-else type="primary" @click="close">{{ job.status === 'pushed' ? '完成' : '关闭' }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { CircleCheck, CircleClose, Loading } from '@element-plus/icons-vue';
import { getAsset, getJob, listCategories, previewPackage, retryJob, uploadAsset, updateAsset, type AssetItem, type AssetJob, type MarketKind, type PackagePreview } from '@/api/assets';

const props = defineProps<{
  modelValue: boolean;
  mode: 'create' | 'update';
  asset?: AssetItem | null;
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

/** 体检没通过就不让提交 —— 免得白填一整张表单 */
const previewBad = computed(() => {
  const p = preview.value;
  if (!p) return false;
  return !p.ok || p.issues.length > 0;
});

const form = reactive({
  code: '', kind: 'skill' as MarketKind, name: '', version: '1.0.0',
  summary: '', description: '', use_when: '', not_for: '',
  category: '', icon: '🧩', featured: false,
  tags: [] as string[], files: [] as File[],
  permissions: {} as Record<string, string[]>,
  install_steps: [] as string[],
});

// 表单里用逗号/多行文本编辑数组, 提交时转回数组
const tagsText = ref('');
const stepsText = ref('');
const permRead = ref('');
const permExec = ref('');
const permNet = ref('');
const permSecret = ref('');

/* 分类表 (后端下发) —— 上传/更新时只能从里面选 */
const categories = ref<{ name: string; slug: string; desc?: string; total: number }[]>([]);
async function loadCategories() {
  if (categories.value.length) return;
  try {
    const r = await listCategories();
    categories.value = (r?.items || []) as typeof categories.value;
  } catch {
    /* 拿不到就退回空列表 —— 后端还会再归一成「其他」 */
  }
}

watch(() => props.modelValue, (open) => {
  if (!open) return;
  loadCategories();
  job.value = null;
  submitting.value = false;
  pkgFile.value = null;
  preview.value = null;
  previewing.value = false;
  pendingReview.value = false;
  if (fileInput.value) fileInput.value.value = '';
  const a = props.asset;
  if (props.mode === 'update' && a) {
    form.code = a.code; form.kind = a.kind; form.name = a.name; form.version = a.version;
    form.summary = a.summary; form.description = a.description;
    form.use_when = a.use_when; form.not_for = a.not_for;
    form.category = a.category; form.icon = a.icon; form.featured = a.featured;
    form.tags = [...a.tags]; form.install_steps = [...a.install_steps];
    form.files = [];
    const p = a.permissions || {};
    permRead.value = (p.filesystem_read || []).join(', ');
    permExec.value = (p.process_exec || []).join(', ');
    permNet.value = (p.network || []).join(', ');
    permSecret.value = (p.secrets || []).join(', ');
  } else {
    Object.assign(form, {
      code: '', kind: 'skill', name: '', version: '1.0.0', summary: '',
      description: '', use_when: '', not_for: '', category: '', icon: '🧩',
      featured: false, tags: [], files: [], install_steps: [],
      permissions: {},
    });
    tagsText.value = ''; stepsText.value = '';
    permRead.value = permExec.value = permNet.value = permSecret.value = '';
  }
});

async function onPickPackage(e: Event) {
  const input = e.target as HTMLInputElement;
  pkgFile.value = input.files?.[0] ?? null;
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

function splitList(s: string): string[] {
  return s.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
}

async function submit() {
  if (!form.name.trim() || !form.summary.trim()) {
    ElMessage.warning('名称与简介必填');
    return;
  }
  if (props.mode === 'create' && !/^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/.test(form.code.trim())) {
    ElMessage.warning('code 只能用小写字母/数字/连字符, 且不能以连字符开头结尾');
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
    permissions: {
      filesystem_read: splitList(permRead.value),
      process_exec: splitList(permExec.value),
      network: splitList(permNet.value),
      secrets: splitList(permSecret.value),
    },
    install_steps: splitList(stepsText.value),
    featured: form.featured,
    package: pkgFile.value,
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
/* 分类下拉里的说明文字 (选项右侧灰字) */
.cat-desc {
  float: right; color: var(--ink-500); font-size: 11px;
  margin-left: 16px; max-width: 320px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}

.up-form :deep(.el-form-item) { margin-bottom: 14px; }
.row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }
.perm-editor { display: flex; flex-direction: column; gap: 7px; width: 100%; }
.hint { margin: 2px 0 0; font-size: 11.5px; color: var(--ink-500); }
.file-input { display: block; margin-bottom: 8px; font-size: 12.5px; }
.file-list { display: flex; flex-wrap: wrap; gap: 6px; }
.hint { margin: 6px 0 0; font-size: 11.5px; color: var(--ink-500); line-height: 1.6; }
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
