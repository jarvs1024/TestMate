<template>
  <el-drawer :model-value="modelValue" size="640px" direction="rtl"
             :title="item ? `编辑软件 · ${item.name}` : '编辑软件'"
             :close-on-click-modal="false" class="sw-edit-drawer"
             @update:model-value="emit('update:modelValue', $event)">
    <!-- ⚠️ 没有 item (理论上不会发生) → 明说, 别给一个空表单让人瞎填 -->
    <div v-if="!item" class="state">
      <div>读不到这个软件的信息, 请关掉重开</div>
    </div>

    <el-form v-else label-position="top" class="up-form">
      <!-- ===== 基本信息 ===== -->
      <section class="up-sec">
        <div class="sec-h"><span class="sec-no">1</span>基本信息</div>
        <div class="row-2">
          <el-form-item label="软件名" required>
            <el-input v-model="form.name" maxlength="128" show-word-limit
                      placeholder="展示名, 中文即可 (卡片标题), 如 SSD 日志医生" />
          </el-form-item>
          <el-form-item label="图标">
            <!-- ⚠️ 图标**不能跟别的软件重复** —— 两张卡长得一样, 用户根本分不清谁是谁.
                 已用过的图标直接标出来并禁掉.
                 ⚠️ **自己正在用的那个不算被占** (used_icons 只给图标→软件名,
                     不知道是不是自己) —— 编辑时按"图标 == 当前条目的图标"放行. -->
            <el-select v-model="form.icon" filterable style="width:100%">
              <el-option v-for="ic in ICONS" :key="ic" :value="ic"
                         :label="ic" :disabled="isIconUsed(ic)">
                <span>{{ ic }}</span>
                <span v-if="iconOwner(ic)" class="opt-desc">已被「{{ iconOwner(ic) }}」用了</span>
              </el-option>
            </el-select>
            <p class="hint">图标别跟别人重复 —— 用过的图标会标成「已用」, 换别的吧.</p>
          </el-form-item>
        </div>

        <el-form-item label="一句话简介" required>
          <el-input v-model="form.summary" type="textarea" :rows="2" maxlength="500" show-word-limit
                    placeholder="一句话说清它干什么 (卡片副标题 + 搜索都用这句)" />
        </el-form-item>

        <el-form-item label="详细说明">
          <el-input v-model="form.description" type="textarea" :rows="4"
                    placeholder="这个软件到底是什么、怎么用 —— 详情页会整段显示" />
        </el-form-item>

        <el-form-item label="功能清单">
          <el-input v-model="featuresText" type="textarea" :rows="4"
                    placeholder="一行一条, 如&#10;读取 NVMe SMART 日志&#10;自动定位失败扇区&#10;导出 CSV 报告" />
          <p class="hint">一行一条 —— 卡片上会显示前 3 条.</p>
        </el-form-item>
      </section>

      <!-- ===== 适用与安装 ===== -->
      <section class="up-sec">
        <div class="sec-h"><span class="sec-no">2</span>适用与安装</div>
        <el-form-item label="适用场景">
          <el-input v-model="form.use_when" type="textarea" :rows="2"
                    placeholder="什么情况下该用它" />
        </el-form-item>
        <el-form-item label="不适合的场景">
          <el-input v-model="form.not_for" type="textarea" :rows="2"
                    placeholder="什么情况下别用它" />
        </el-form-item>
        <el-form-item label="安装说明">
          <el-input v-model="form.install_steps" type="textarea" :rows="3"
                    placeholder="怎么装、怎么跑起来, 如&#10;解压到 /opt/tool&#10;运行 install.sh" />
          <p class="hint">选填 —— 填了详情页会显示「安装说明」一栏, 没填就不占位.</p>
        </el-form-item>
        <el-form-item label="注意事项">
          <el-input v-model="form.caveats" type="textarea" :rows="2"
                    placeholder="有什么坑、什么副作用, 如: 需要管理员权限" />
          <p class="hint">选填 —— 详情页会用醒目的提示块显示, 避免别人踩坑.</p>
        </el-form-item>
        <div class="row-2">
          <el-form-item label="适用平台">
            <!-- ⚠️ 必须给中文 placeholder —— Element Plus 默认是英文 "Select" -->
            <el-select v-model="form.platform" style="width:100%" placeholder="不限">
              <el-option v-for="p in PLATFORMS" :key="p.value" :value="p.value" :label="p.label">
                <span>{{ p.label }}</span>
                <span v-if="p.desc" class="opt-desc">{{ p.desc }}</span>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="分类">
            <el-input v-model="form.category" maxlength="64" placeholder="如 工具 / 驱动 / 脚本" />
          </el-form-item>
        </div>
      </section>

      <!-- ===== 标签 ===== -->
      <section class="up-sec">
        <div class="sec-h"><span class="sec-no">3</span>标签与关键词</div>
        <div class="row-2">
          <el-form-item label="标签 (逗号分隔)">
            <el-input v-model="tagsText" placeholder="如 ssd, 日志, 诊断" />
          </el-form-item>
          <el-form-item label="关键词 (逗号分隔)">
            <el-input v-model="keywordsText" placeholder="如 smartctl, nvme" />
            <p class="hint">搜索用 —— 跟标签分开, 标签给人看, 关键词给搜索用.</p>
          </el-form-item>
        </div>
      </section>

      <!-- ⚠️ 2026-10-30: 保存失败**要保留用户填的内容** ——
           静默关抽屉 = 白填一遍. 这里只提示, 不清表单. -->
      <p v-if="formError" class="form-err">{{ formError }}</p>
    </el-form>

    <template #footer>
      <div class="up-foot">
        <span class="foot-tip">只改说明信息, 不会动已经传上去的安装包.</span>
        <div class="foot-btns">
          <button class="mini-btn" :disabled="saving" @click="emit('update:modelValue', false)">取消</button>
          <button class="mini-btn primary" :disabled="saving || !canSave" @click="submit">
            {{ saving ? '保存中…' : '保存' }}
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
  getSoftwareConfig, updateSoftware,
  type SoftwareConfig, type SoftwareDetail,
} from '@/api/software';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';
import {
  ICONS, PLATFORMS, splitFeatures, splitTags, validateName,
} from './softwareForm';

const props = defineProps<{
  modelValue: boolean;
  /** 要编辑的条目 (软件详情) */
  item?: SoftwareDetail | null;
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void;
  (e: 'done'): void;
}>();

function emptyForm() {
  return {
    name: '', icon: '🧰', summary: '', description: '',
    features: '', use_when: '', not_for: '',
    install_steps: '', caveats: '',
    platform: '', category: '', tags: '', keywords: '',
  };
}

const form = ref(emptyForm());
const featuresText = ref('');
const tagsText = ref('');
const keywordsText = ref('');
const formError = ref('');
const saving = ref(false);

const config = ref<SoftwareConfig | null>(null);

/** 抽屉打开 → 把条目的内容回填进表单 */
function fillFromItem() {
  const it = props.item;
  if (!it) return;
  Object.assign(form.value, {
    name: it.name || '',
    icon: it.icon || '🧰',
    summary: it.summary || '',
    description: it.description || '',
    features: (it.features || []).join('\n'),
    use_when: it.use_when || '',
    not_for: it.not_for || '',
    install_steps: it.install_steps || '',
    caveats: it.caveats || '',
    platform: it.platform || '',
    category: it.category || '',
    tags: (it.tags || []).join(', '),
    keywords: (it.keywords || []).join(', '),
  });
  // ⚠️ 功能清单/标签单独存一份 —— 提交时要 split 回数组
  featuresText.value = (it.features || []).join('\n');
  tagsText.value = (it.tags || []).join(', ');
  keywordsText.value = (it.keywords || []).join(', ');
  formError.value = '';
}

watch(() => props.modelValue, (open) => {
  if (!open) {
    formError.value = '';
    saving.value = false;
    return;
  }
  fillFromItem();
  loadConfig();
});

/** 拉图标占用表 —— 跟上传抽屉同一套「已用」标记 */
async function loadConfig() {
  try {
    config.value = await getSoftwareConfig();
  } catch {
    // 取不到不该挡住编辑 —— 后端还会再拦一道
    config.value = null;
  }
}

/**
 * 这个图标已经被**别的**软件占了?
 *
 * ⚠️ `used_icons` 是 {图标 → 软件名}, 不知道占用者是不是自己 ——
 *    编辑时自己正在用的那个图标必须放行, 否则用户连"不改图标"都做不到
 *    (下拉里它被标成"已用"而且是禁用的).
 */
function isIconUsed(ic: string): boolean {
  const owner = config.value?.used_icons?.[ic];
  if (!owner) return false;
  if (ic === props.item?.icon) return false;
  return true;
}

function iconOwner(ic: string): string {
  if (ic === props.item?.icon) return '';
  return config.value?.used_icons?.[ic] || '';
}

function errText(e: unknown, fallback: string): string {
  return httpErrorText(errorStatus(e), errorDetail(e), fallback);
}

const canSave = computed(() => !!form.value.name.trim());

async function submit() {
  const it = props.item;
  if (!it || saving.value) return;
  const nameErr = validateName(form.value.name);
  if (nameErr) {
    formError.value = nameErr;
    return;
  }
  saving.value = true;
  formError.value = '';
  try {
    await updateSoftware(it.code, {
      name: form.value.name.trim(),
      icon: form.value.icon || '🧰',
      summary: form.value.summary.trim(),
      description: form.value.description,
      features: splitFeatures(featuresText.value),
      use_when: form.value.use_when,
      not_for: form.value.not_for,
      install_steps: form.value.install_steps,
      caveats: form.value.caveats,
      platform: form.value.platform,
      category: form.value.category.trim(),
      tags: splitTags(tagsText.value),
      keywords: splitTags(keywordsText.value),
    });
    ElMessage.success('软件信息已保存');
    emit('done');
    emit('update:modelValue', false);
  } catch (e: any) {
    // ⚠️ 失败**不关抽屉** —— 用户填的东西还在, 改一处再提交就行
    formError.value = errText(e, '保存失败');
  } finally {
    saving.value = false;
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
.row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.hint { margin: 0; font-size: 11px; color: var(--ink-500); line-height: 1.6; }

/* 下拉选项里的补充说明 (选项右侧灰字) */
.opt-desc {
  display: inline-block; vertical-align: bottom;
  color: var(--ink-500); font-size: 11px;
  margin-left: 12px; max-width: 260px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}

.state {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  padding: 30px 0; color: var(--ink-500); font-size: 13px;
}

.form-err {
  margin: 4px 0 0; padding: 8px 11px; border-radius: var(--radius-sm);
  font-size: 12px; color: var(--err);
  background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.25);
}

.up-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.foot-tip { font-size: 11.5px; color: var(--ink-500); }
.foot-btns { display: flex; gap: 8px; }
</style>
