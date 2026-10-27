<template>
  <el-drawer :model-value="modelValue" size="760px" direction="rtl"
             :title="mode === 'version' ? `发布新版本 · ${item?.name || ''}` : '上传软件'"
             :close-on-click-modal="false" class="sw-up-drawer"
             @update:model-value="emit('update:modelValue', $event)">
    <el-form label-position="top" class="up-form">
      <!-- ============ ① 软件包 (放最前) ============ -->
      <section class="up-sec">
        <div class="sec-h"><span class="sec-no">1</span>软件包<span class="sec-tip">必填</span></div>
        <div class="file-pick"
             @dragover.prevent="dragging = true"
             @dragleave.prevent="dragging = false"
             @drop.prevent="onDrop">
          <input ref="fileInput" type="file" class="file-input" @change="onPick" />
          <button type="button" class="pick-btn" @click="fileInput?.click()">
            <span class="pb-ic">📦</span>选择软件包
          </button>
          <span v-if="file" class="file-chip">
            {{ file.name }}<b @click="clearFile">×</b>
          </span>
          <span v-else class="pick-hint">未选择文件 (可以拖进来)</span>
        </div>
        <p class="hint">
          任意格式都行 (exe / zip / tar.gz / deb …), 单个最大
          <b>{{ formatSize(maxBytes) }}</b>. 文件原样存在服务器上, 别人下下来就是这一份.
        </p>
        <p v-if="fileError" class="pick-err">{{ fileError }}</p>

        <!-- 上传进度 —— 5G 的包要传好几分钟, 没有进度条用户会以为卡死了 -->
        <div v-if="uploading" class="pv-box checking">
          <div class="pv-h">
            <span class="pv-icon">⬆</span>
            <span>正在上传… {{ percent }}%</span>
          </div>
          <el-progress :percentage="percent" :stroke-width="8" />
          <div class="pv-meta mono">
            {{ file?.name }} · {{ formatSize(file?.size || 0) }}
            <span v-if="uploadedBytes"> · 已传 {{ formatSize(uploadedBytes) }}</span>
          </div>
        </div>
      </section>

      <!-- ============ ② 基本信息 ============ -->
      <section v-if="mode !== 'version'" class="up-sec">
        <div class="sec-h"><span class="sec-no">2</span>基本信息</div>
        <div class="row-2">
          <el-form-item label="软件名" required>
            <el-input v-model="form.name" maxlength="128" show-word-limit
                      placeholder="展示名, 中文即可 (卡片标题), 如 SSD 日志医生" />
          </el-form-item>
          <el-form-item label="图标">
            <el-select v-model="form.icon" filterable style="width:100%">
              <el-option v-for="ic in ICONS" :key="ic" :value="ic" :label="ic" />
            </el-select>
          </el-form-item>
        </div>

        <!-- 标识: 会变成服务器上的目录名 —— 所以有格式要求 -->
        <el-form-item label="软件标识 (code)" required>
          <el-input v-model="form.code" maxlength="64"
                    :placeholder="`唯一标识, 小写字母数字与 -_. 如 ${CODE_EXAMPLE}`" />
          <p class="hint">这是这个软件在服务器上的唯一编号, 以后下载和更新都靠它认.</p>
          <p v-if="codeError" class="pick-err">{{ codeError }}</p>
        </el-form-item>

        <div class="row-2">
          <el-form-item label="版本号" required>
            <el-input v-model="form.version" maxlength="32" placeholder="如 1.0.0" />
          </el-form-item>
          <el-form-item label="适用平台">
            <el-select v-model="form.platform" style="width:100%">
              <el-option v-for="p in PLATFORMS" :key="p.value" :value="p.value" :label="p.label" />
            </el-select>
          </el-form-item>
        </div>

        <el-form-item label="一句话简介" required>
          <el-input v-model="form.summary" type="textarea" :rows="2" maxlength="500" show-word-limit
                    placeholder="一句话说清它干什么 (卡片副标题 + 搜索都用这句)" />
        </el-form-item>

        <el-form-item label="详情">
          <el-input v-model="form.description" type="textarea" :rows="4" maxlength="4000" show-word-limit
                    placeholder="详细说明: 怎么用、需要什么环境、注意事项…" />
        </el-form-item>

        <!-- 功能清单 —— 卡片和详情里最显眼的一段 -->
        <el-form-item label="功能清单">
          <el-input v-model="featuresText" type="textarea" :rows="4"
                    placeholder="一行一条, 如&#10;读取 NVMe SMART 日志&#10;自动定位失败扇区&#10;导出 CSV 报告" />
          <p class="hint">一行一条 —— 卡片上会显示前 3 条.</p>
        </el-form-item>

        <el-form-item label="适用场景">
          <el-input v-model="form.use_when" type="textarea" :rows="2"
                    placeholder="什么情况下该用它" />
        </el-form-item>

        <el-form-item label="不适合的场景">
          <el-input v-model="form.not_for" type="textarea" :rows="2"
                    placeholder="什么情况下别用它 (别让人踩坑)" />
        </el-form-item>

        <div class="row-2">
          <el-form-item label="分类">
            <el-input v-model="form.category" maxlength="64" placeholder="如 工具 / 驱动 / 脚本" />
          </el-form-item>
          <el-form-item label="标签 (逗号分隔)">
            <el-input v-model="tagsText" placeholder="如 ssd, 日志, 诊断" />
          </el-form-item>
        </div>
      </section>

      <!-- ============ ③ 版本信息 (发新版本时) ============ -->
      <section v-else class="up-sec">
        <div class="sec-h"><span class="sec-no">2</span>版本信息</div>
        <el-form-item label="版本号" required>
          <el-input v-model="versionForm.version" maxlength="32" placeholder="如 1.1.0" />
          <p v-if="versionError" class="pick-err">{{ versionError }}</p>
        </el-form-item>
      </section>

      <!-- ============ ④ 更新说明 ============ -->
      <section class="up-sec">
        <div class="sec-h">
          <span class="sec-no">{{ mode === 'version' ? 3 : 4 }}</span>发布与更新说明
          <span class="sec-tip">选填</span>
        </div>
        <el-input v-model="releaseNotes" type="textarea" :rows="3"
                  placeholder="这次改了什么 —— 版本历史里会给每个人看" />
      </section>

      <p v-if="formError" class="form-err">{{ formError }}</p>
    </el-form>

    <template #footer>
      <div class="up-foot">
        <span v-if="missing.length" class="missing">还缺: {{ missing.join('、') }}</span>
        <span v-else class="missing ok">可以提交了</span>
        <div class="foot-btns">
          <button class="mini-btn" :disabled="uploading" @click="emit('update:modelValue', false)">取消</button>
          <button class="mini-btn primary" :disabled="uploading || missing.length > 0" @click="submit">
            {{ uploading ? '上传中…' : (mode === 'version' ? '发布新版本' : '上传软件') }}
          </button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import {
  createSoftware, createSoftwareVersion, getSoftwareConfig, uploadSoftwareFile,
  type SoftwareConfig, type SoftwareDetail,
} from '@/api/software';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';
import {
  CODE_EXAMPLE, ICONS, PLATFORMS, formatSize, splitFeatures, splitTags,
  validateCode, validateFileSize, validateName, validateVersion,
} from './softwareForm';

const props = defineProps<{
  modelValue: boolean;
  /** create = 新建软件; version = 给已有软件发新版本 */
  mode?: 'create' | 'version';
  item?: SoftwareDetail | null;
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void;
  (e: 'done'): void;
}>();

const mode = computed(() => props.mode || 'create');

const form = ref({
  code: '', name: '', icon: '🧰', version: '1.0.0', summary: '', description: '',
  use_when: '', not_for: '', platform: '', category: '', tags: '', keywords: '',
});
const versionForm = ref({ version: '' });
const featuresText = ref('');
const tagsText = ref('');
const releaseNotes = ref('');

const file = ref<File | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const fileError = ref('');
const codeError = ref('');
const versionError = ref('');
const formError = ref('');

const uploading = ref(false);
const percent = ref(0);
const uploadedBytes = ref(0);
const dragging = ref(false);

const config = ref<SoftwareConfig | null>(null);
const maxBytes = computed(() => config.value?.max_bytes || 5 * 1024 * 1024 * 1024);

function errText(e: unknown, fallback: string): string {
  return httpErrorText(errorStatus(e), errorDetail(e), fallback);
}

async function loadConfig() {
  if (config.value) return;
  try {
    config.value = await getSoftwareConfig();
  } catch {
    // 取不到配置不该挡住上传 —— 用 5G 的默认上限, 后端还会再拦一道
    config.value = null;
  }
}

watch(() => props.modelValue, (open) => {
  if (!open) return;
  formError.value = '';
  fileError.value = '';
  codeError.value = '';
  versionError.value = '';
  percent.value = 0;
  uploadedBytes.value = 0;
  loadConfig();
  if (mode.value === 'version') {
    const cur = props.item?.version || '';
    // 默认给下一个补丁版本号 —— 省得用户自己想
    versionForm.value.version = cur ? bumpVersion(cur) : '1.0.0';
  }
});

function bumpVersion(v: string): string {
  const m = v.match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return v;
  return `${m[1]}.${m[2]}.${Number(m[3]) + 1}`;
}

function onPick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0] || null;
  setFile(f);
}

function onDrop(e: DragEvent) {
  dragging.value = false;
  const f = e.dataTransfer?.files?.[0] || null;
  setFile(f);
}

function setFile(f: File | null) {
  fileError.value = '';
  if (!f) {
    file.value = null;
    return;
  }
  const err = validateFileSize(f.size, maxBytes.value);
  if (err) {
    fileError.value = err;
    file.value = null;
    return;
  }
  file.value = f;
}

function clearFile() {
  file.value = null;
  fileError.value = '';
}

const missing = computed<string[]>(() => {
  const out: string[] = [];
  if (!file.value) out.push('软件包');
  if (mode.value === 'version') {
    if (!versionForm.value.version.trim()) out.push('版本号');
  } else {
    if (!form.value.name.trim()) out.push('软件名');
    if (!form.value.code.trim()) out.push('软件标识');
    if (!form.value.version.trim()) out.push('版本号');
    if (!form.value.summary.trim()) out.push('一句话简介');
  }
  return out;
});

async function submit() {
  if (missing.value.length) return;
  formError.value = '';
  codeError.value = '';
  versionError.value = '';

  if (mode.value === 'create') {
    codeError.value = validateCode(form.value.code);
    if (codeError.value) return;
  } else {
    versionError.value = validateVersion(versionForm.value.version);
    if (versionError.value) return;
  }
  const nameErr = mode.value === 'create' ? validateName(form.value.name) : '';
  if (nameErr) {
    formError.value = nameErr;
    return;
  }

  uploading.value = true;
  percent.value = 0;
  uploadedBytes.value = 0;
  try {
    let code = props.item?.code || '';
    let version = versionForm.value.version;

    if (mode.value === 'create') {
      const f = file.value!;
      const created = await createSoftware({
        code: form.value.code.trim(),
        name: form.value.name.trim(),
        icon: form.value.icon || '🧰',
        version: form.value.version.trim(),
        summary: form.value.summary.trim(),
        description: form.value.description,
        features: splitFeatures(featuresText.value),
        use_when: form.value.use_when,
        not_for: form.value.not_for,
        platform: form.value.platform,
        category: form.value.category.trim(),
        tags: splitTags(tagsText.value),
        keywords: splitTags(form.value.keywords),
        file_name: f.name,
        file_size: f.size,
        release_notes: releaseNotes.value,
      });
      code = created.code;
      version = created.version;
    } else {
      const f = file.value!;
      const created = await createSoftwareVersion(code, {
        version: version.trim(),
        release_notes: releaseNotes.value,
        file_name: f.name,
        file_size: f.size,
      });
      version = created.version;
    }

    // ---- 第 ② 步: 传文件 (原始字节流, 边传边报进度) ----
    await uploadSoftwareFile(code, file.value!, (p) => {
      percent.value = p;
      uploadedBytes.value = Math.round((p / 100) * (file.value?.size || 0));
    });

    ElMessage.success(mode.value === 'create' ? '软件已上传' : `新版本 ${version} 已发布`);
    emit('done');
    emit('update:modelValue', false);
  } catch (e: any) {
    formError.value = errText(e, '上传失败');
  } finally {
    uploading.value = false;
  }
}
</script>

<style scoped>
.up-form { display: flex; flex-direction: column; gap: 4px; }
.up-sec { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.sec-h {
  display: flex; align-items: center; gap: 7px;
  font-size: 12px; font-weight: 700; color: var(--ink-900);
}
.sec-no {
  width: 17px; height: 17px; border-radius: 5px;
  background: var(--surface-sunken); color: var(--ink-600, #6b7280);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700;
}
.sec-tip { font-size: 10.5px; color: var(--ink-500); font-weight: 400; }

.row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

.file-pick {
  display: flex; align-items: center; gap: 9px; flex-wrap: wrap;
  border: 1px dashed var(--border); border-radius: var(--radius-sm);
  padding: 11px 12px; background: var(--surface-soft);
}
.file-input { display: none; }
.pick-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 13px; border-radius: var(--radius-btn);
  border: 1px solid var(--primary); background: var(--primary);
  color: #fff; font-size: 12.5px; cursor: pointer; font-family: inherit;
}
.pick-btn:hover { opacity: .9; }
.pb-ic { font-size: 14px; }
.file-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--ink-700);
  background: var(--surface-sunken); padding: 4px 9px;
  border-radius: var(--radius-sm); font-family: var(--font-mono);
}
.file-chip b { cursor: pointer; color: var(--ink-500); }
.pick-hint { font-size: 12px; color: var(--ink-500); }
.pick-err { margin: 0; font-size: 11.5px; color: var(--err); }
.hint { margin: 0; font-size: 11px; color: var(--ink-500); line-height: 1.6; }

.pv-box {
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 9px 11px; background: var(--surface-soft);
  display: flex; flex-direction: column; gap: 6px;
}
.pv-h { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--ink-700); }
.pv-meta { font-size: 10.5px; color: var(--ink-500); }

.form-err {
  margin: 4px 0 0; padding: 8px 11px; border-radius: var(--radius-sm);
  font-size: 12px; color: var(--err);
  background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.25);
}

.up-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.missing { font-size: 11.5px; color: var(--warn); }
.missing.ok { color: var(--ok); }
.foot-btns { display: flex; gap: 8px; }
</style>
