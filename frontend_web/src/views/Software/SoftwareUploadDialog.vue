<template>
  <el-drawer :model-value="modelValue" size="760px" direction="rtl"
             :title="mode === 'version' ? `发布新版本 · ${item?.name || ''}` : '上架软件'"
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
          <!-- ⚠️ 这里**不能**用两个兄弟节点的 v-if / v-else (chip 一个 / hint 一个):
               选中文件时 chip 的分支会**替换**掉 hint 那个节点, Vue 的兄弟节点 patch
               会把 input 一起挪动 —— input 的 change 监听器就此失灵,
               **选了文件界面却毫无反应** (2026-10-28 踩过).
               改成**一个元素内部**用 template v-if 切换文字, DOM 骨架不动. -->
          <span class="file-chip" :class="{ 'is-empty': !file }">
            <template v-if="file">
              {{ file.name }}<b @click="clearFile">×</b>
            </template>
            <template v-else>
              <span class="pick-hint">未选择文件 (可以拖进来)</span>
            </template>
          </span>
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
            <!-- ⚠️ 图标**不能跟别的软件重复** (2026-10-28) —— 两张卡长得一样,
                 用户根本分不清谁是谁. 已用过的图标直接标出来并禁掉. -->
            <el-select v-model="form.icon" filterable style="width:100%"
                       @change="iconTouched = true">
              <el-option v-for="ic in ICONS" :key="ic" :value="ic"
                         :label="iconLabel(ic)" :disabled="isIconUsed(ic)" />
            </el-select>
            <p class="hint">图标别跟别人重复 —— 用过的图标会标成「已用」, 换别的吧.</p>
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
          <el-form-item label="版本变体">
            <!-- ⚠️ 变体标签 (选填) —— 一个软件挂两个版本时靠它区分:
                 「Windows版」「LTS版」「内测版」. 不填就用版本号. -->
            <el-input v-model="form.variant" maxlength="32" placeholder="如 Windows版 / LTS版" />
          </el-form-item>
        </div>

        <div class="row-2">
          <el-form-item label="适用平台">
            <!-- ⚠️ 必须给中文 placeholder —— Element Plus 默认是英文 "Select",
                 整个界面都是中文, 夹一个英文下拉框很扎眼 -->
            <el-select v-model="form.platform" style="width:100%" placeholder="不限">
              <el-option v-for="p in PLATFORMS" :key="p.value" :value="p.value" :label="p.label" />
            </el-select>
          </el-form-item>
        </div>

        <el-form-item label="一句话简介" required>
          <el-input v-model="form.summary" type="textarea" :rows="2" maxlength="500" show-word-limit
                    placeholder="一句话说清它干什么 (卡片副标题 + 搜索都用这句)" />
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

        <!-- ⚠️ 2026-10-28: 「详情」和「不适合的场景」两个输入框**去掉了** ——
             上架时只填真正影响"能不能用、怎么用"的信息, 少两个框少两次纠结.
             · 「详情」= 一段自由文本, 跟「功能清单」「安装说明」重叠, 详情页本来就有条件渲染;
             · 「不适合的场景」更没必要 —— 「注意事项」已经覆盖了"别乱用"这件事.
             两者在后端都是 nullable=False + default="", 不传就是空串, 老数据照常显示. -->

        <!-- ===== 安装说明 / 注意事项 —— **选填**, 详情页有则显示、无则不占位 ===== -->
        <el-form-item label="安装说明">
          <el-input v-model="form.install_steps" type="textarea" :rows="3"
                    placeholder="怎么装、怎么跑起来, 如&#10;解压到 /opt/tool&#10;运行 install.sh&#10;配好环境变量 PATH" />
          <p class="hint">选填 —— 填了详情页会显示「安装说明」一栏, 没填就不占位.</p>
        </el-form-item>

        <el-form-item label="注意事项">
          <el-input v-model="form.caveats" type="textarea" :rows="2"
                    placeholder="有什么坑、什么副作用, 如: 需要管理员权限, 会在系统目录留下配置" />
          <p class="hint">选填 —— 详情页会用醒目的提示块显示, 避免别人踩坑.</p>
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

      <!-- ============ ② 版本信息 (发新版本时) ============ -->
      <!-- ⚠️ 跟上面的「② 基本信息」是 v-if / v-else **互斥**的 —— 两种模式都占第 2 号 -->
      <section v-else class="up-sec">
        <div class="sec-h"><span class="sec-no">2</span>版本信息</div>
        <el-form-item label="版本变体">
          <!-- ⚠️ 变体标签 (选填) —— 两个版本并存时靠它区分谁是谁 -->
          <el-input v-model="versionForm.variant" maxlength="32" placeholder="如 Windows版 / LTS版" />
          <p class="hint">选填 —— 一个软件挂两个版本、两个都有用时, 靠这个标签区分 (如「LTS版」).</p>
        </el-form-item>

        <el-form-item label="版本号" required>
          <el-input v-model="versionForm.version" maxlength="32" placeholder="如 1.1.0" />
          <!-- ⚠️ 版本号**可以自增, 也可以自己写** ——
               默认给的是"当前版本 +1 个补丁号"的建议值, 想改成 2.0.0 直接改就行.
               重复的版本号当场拦下来 (后端也会再拦一道). -->
          <p class="hint">
            <template v-if="currentVersion">
              当前 {{ currentVersion }} · 建议
              <b class="mono">{{ suggestedVersion }}</b>
              <button v-if="versionForm.version.trim() !== suggestedVersion"
                      type="button" class="mini-link" @click="versionForm.version = suggestedVersion">
                用建议值
              </button>
            </template>
            <template v-if="existingVersions.length">
              · 已有版本 {{ existingVersions.join(' / ') }}
            </template>
          </p>
          <p v-if="versionError" class="pick-err">{{ versionError }}</p>
        </el-form-item>

        <!-- ⚠️ 推荐下载版本 —— 一个条目只能有一个推荐版本.
             新版本默认接管推荐; 想让老版本继续当默认 (比如 LTS 版还在给老环境用),
             就把这里关掉, 之后在详情页也能随时改. -->
        <el-form-item label="设为推荐下载版本">
          <el-checkbox v-model="versionForm.is_default">把这个版本设成默认下载的那个</el-checkbox>
          <p class="hint">
            关掉的话, 推荐位留给现有版本 —— 适合「老版本还在给老环境用」的场景.
          </p>
        </el-form-item>
      </section>

      <!-- ============ ③ 更新说明 ============ -->
      <!-- ⚠️ 编号为什么是 **3** (2026-10-28 修):
           两种模式的区块结构是一样的 —— 「基本信息」和「版本信息」是 v-if / v-else
           **互斥**的, 所以不管哪种模式, 这个 section 前面都只有两个:
             上架软件:  ① 软件包 → ② 基本信息 → ③ 更新说明
             发新版本:  ① 软件包 → ② 版本信息 → ③ 更新说明
           以前这里写的是 `mode === 'version' ? 3 : 4` —— create 模式给 4,
           页面上的数字直接跳号 (1 → 2 → 4), 看着像漏了一节. -->
      <section class="up-sec">
        <div class="sec-h">
          <span class="sec-no">3</span>发布与更新说明
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
            {{ uploading ? '上传中…' : (mode === 'version' ? '发布新版本' : '上架软件') }}
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

/** 新建软件时的空表单 —— 每次打开抽屉都回到这个状态 */
function emptyForm() {
  return {
    code: '', name: '', icon: '🧰', version: '1.0.0', summary: '',
    // ⚠️ 2026-10-28: `description`(详情) 和 `not_for`(不适合的场景) 不再是表单字段 ——
    //    上架时不再问这两个, 提交时也不传 (后端 default="", 老数据照常显示).
    use_when: '', platform: '', category: '', tags: '', keywords: '',
    // 安装说明 / 注意事项 —— 选填 (2026-10-28)
    install_steps: '', caveats: '',
    // 变体标签 —— 选填 (2026-10-28)
    variant: '',
  };
}

const form = ref(emptyForm());
// ⚠️ is_default 默认 **true** —— 新版本默认接管推荐位 (2026-10-28)
const versionForm = ref({ version: '', variant: '', is_default: true });
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
/** 用户自己挑过图标 —— 之后 loadConfig 不要再替他改 */
const iconTouched = ref(false);

function errText(e: unknown, fallback: string): string {
  return httpErrorText(errorStatus(e), errorDetail(e), fallback);
}

async function loadConfig() {
  // (2026-10-28) 每次打开都要**重新拉** ——
  //    `used_icons` 是「谁占了哪个图标」. 上一条刚上架完, 这里必须看到最新的,
  //    否则下拉里那个已被占用的图标看着还是可选的, 用户选了才被后端 409 拦回来.
  try {
    config.value = await getSoftwareConfig();
  } catch {
      // 取不到配置不该挡住上传 —— 用 5G 的默认上限, 后端还会再拦一道
      config.value = null;
  }
  // ⚠️ 默认图标给一个**没被占用**的 (2026-10-28) ——
  //    图标不许跟别的软件重复 (后端会 409). 但所有条目的默认值都是 🧰,
  //    不挑空闲的 → 第二个条目必然撞车, 用户什么都没选就被拦.
  //    只在用户还没自己挑过时改 (别把人家刚选好的图标顶掉).
  if (!iconTouched.value) {
    const free = pickFreeIcon();
    if (free) form.value.icon = free;
  }
  iconTouched.value = false;
}

/** 这个图标已经被别的软件占了? */
function isIconUsed(ic: string): boolean {
  return !!config.value?.used_icons?.[ic];
}

/** 下拉里显示的名字 —— 已用的直接标出来 */
function iconLabel(ic: string): string {
  const owner = config.value?.used_icons?.[ic];
  return owner ? `${ic} (已被「${owner}」用了)` : ic;
}

/** 挑一个还没人用的图标 */
function pickFreeIcon(): string {
  const used = config.value?.used_icons || {};
  return ICONS.find((ic) => !used[ic]) || '';
}

/**
 * 清掉**浏览器里**残留的文件列表.
 *
 * ⚠️ 2026-10-28 踩到的真 bug: 只清 Vue 状态 (file.value = null) 是不够的 ——
 *    input.files 里还留着上一次选的文件. 浏览器判断"文件列表没变"时
 *    **不会**再派发 change 事件 → onPick 不跑 → 用户以为自己换了新文件,
 *    实际提交的还是上一次的旧文件 (界面上的文件名也会停在旧的).
 *    必须 input.value = '' 把浏览器那份也清掉, 再选同一个文件才会重新派发 change.
 */
function clearDomFile() {
  const el = fileInput.value;
  if (el) el.value = '';
}

/**
 * 草稿重置 —— **在抽屉关闭时**做, 不是打开时.
 *
 * ⚠️ 2026-10-28 踩过的坑: 原来在「打开」时清 file.value, 结果**文件选不上了** ——
 *    打开的瞬间改 file 会让 Vue 立刻 patch 掉刚挂上的 DOM,
 *    紧接着的 file input 选择事件就丢了 (e2e 里 uploadFile 后 change 没触发,
 *    手动 dispatch 才生效). 挪到关闭时做就没有这个问题 ——
 *    下次打开时状态早就是干净的, 打开本身不做任何会改 DOM 的事.
 */
function resetDraft() {
  formError.value = '';
  fileError.value = '';
  codeError.value = '';
  versionError.value = '';
  percent.value = 0;
  uploadedBytes.value = 0;
  // ① 发新版本时, 上一版的「发布与更新说明」会被带进新版本的表单 ——
  //    用户以为在写新说明, 实际提交的是上一版的文字;
  // ② 上传完 A 软件再去上传 B 软件, A 的「功能清单 / 标签 / 名称 / 文件」会带过去 ——
  //    看着像填好了, 实际提交的是别的软件的内容.
  releaseNotes.value = '';
  featuresText.value = '';
  tagsText.value = '';
  file.value = null;
  clearDomFile();
  // ⚠️ 必须**逐字段**重置, 不能整个换对象 ——
  //    `form.value = emptyForm()` 换掉整个 ref 后, el-input 绑定的旧值
  //    不会同步到 DOM (输入框里还留着上一次的简介), 看着像没清干净.
  Object.assign(form.value, emptyForm());
  // ⚠️ 逐字段重置 versionForm —— 换整个对象的话 el-checkbox 的选中状态
  //    不会同步 (界面上还留着上一次的勾).
  versionForm.value.version = '';
  versionForm.value.variant = '';
  versionForm.value.is_default = true;
  // 下次打开时图标由 loadConfig 重新挑一个空闲的
  iconTouched.value = false;
}

watch(() => props.modelValue, (open) => {
  if (!open) {
    resetDraft();
    return;
  }
  // 打开时也清一次浏览器那份 (首次挂载时本来就没有, 重复清是幂等的)
  clearDomFile();
  loadConfig();
  if (mode.value === 'version') {
    const cur = props.item?.version || '';
    // 默认给下一个补丁版本号 —— 省得用户自己想
    versionForm.value.version = cur ? bumpVersion(cur) : '1.0.0';
    // ⚠️ 新版本默认**接管**推荐位 (勾上) —— 这是最常见的用法:
    //    发新版 = 让大家下新的. 想让老版本继续当默认 (比如 LTS 版还在给老环境用),
    //    就把勾去掉 —— 这就是下面那个复选框的用处.
    versionForm.value.is_default = true;
  }
});

function bumpVersion(v: string): string {
  const m = v.match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return v;
  return `${m[1]}.${m[2]}.${Number(m[3]) + 1}`;
}

// ===== 版本号建议 (发新版本时) =====
// 当前版本 / 建议的下一个版本号 / 已经发过的版本号
const currentVersion = computed(() => props.item?.version || '');
const suggestedVersion = computed(() => bumpVersion(currentVersion.value) || '1.0.0');
const existingVersions = computed(() => (props.item?.versions || []).map((v) => v.version));
/** 用户填的版本号跟已发过的撞了 —— 当场提示, 别等后端 409 */
const versionDup = computed(() => existingVersions.value.includes(versionForm.value.version.trim()));

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
    // 版本号跟已发过的撞了 —— 当场拦, 别等后端 409
    if (versionDup.value) {
      versionError.value = `版本号 ${versionForm.value.version.trim()} 已经发过了, 换一个`;
      return;
    }
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
        features: splitFeatures(featuresText.value),
        use_when: form.value.use_when,
        // ⚠️ 不再传 description / not_for (2026-10-28) —— 上架页没有这两个输入框了
        // 安装说明 / 注意事项 (选填)
        install_steps: form.value.install_steps,
        caveats: form.value.caveats,
        platform: form.value.platform,
        category: form.value.category.trim(),
        tags: splitTags(tagsText.value),
        keywords: splitTags(form.value.keywords),
        file_name: f.name,
        file_size: f.size,
        release_notes: releaseNotes.value,
        // 变体标签 (选填)
        variant: form.value.variant.trim(),
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
        // 变体标签 (选填) —— 两个版本并存时靠它区分
        variant: versionForm.value.variant.trim(),
        // 是否接管推荐下载位
        is_default: versionForm.value.is_default,
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
/* 空状态: 别带 chip 的底色 —— 那看着像"已经选了一个文件" */
.file-chip.is-empty { background: transparent; padding: 4px 0; }
.pick-hint { font-size: 12px; color: var(--ink-500); }
.pick-err { margin: 0; font-size: 11.5px; color: var(--err); }
.hint { margin: 0; font-size: 11px; color: var(--ink-500); line-height: 1.6; }

/* 提示行里的小链接按钮 (如「用建议值」) */
.mini-link {
  border: none; background: none; padding: 0 3px;
  color: var(--primary); font-size: 11px; cursor: pointer;
  font-family: inherit; text-decoration: underline;
}
.mini-link:hover { color: var(--primary-2); }

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
