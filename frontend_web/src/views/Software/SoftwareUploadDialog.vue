<template>
  <el-drawer :model-value="modelValue" size="760px" direction="rtl"
             :title="mode === 'version' ? `发布新版本 · ${item?.name || ''}` : '上架软件'"
             :close-on-click-modal="false" class="sw-up-drawer"
             @update:model-value="emit('update:modelValue', $event)">
    <el-form label-position="top" class="up-form">
      <!-- ============ ① 软件包 (放最前) ============ -->
      <section class="up-sec">
        <div class="sec-h"><span class="sec-no">1</span>软件包<span class="sec-tip">必填</span></div>
        <!-- ⚠️ 2026-10-30: `dragging` 这个 ref 以前**只写不读** (模板里没有任何绑定),
             样式里也没有 .dragging —— 状态等于没用: 用户把文件拖进来, 边框一点变化都没有.
             现在把状态绑到 class 上, 拖进来时边框变主色. -->
        <div class="file-pick" :class="{ dragging }"
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
              <!-- ⚠️ 2026-10-30: 文件名最长 200 字符, mono 字体约 1400px > 抽屉 760px ——
                   不截断的话 chip 把内容撑破, 完整文件名一个都看不到.
                   名字单独包一层: 自己截断 (ellipsis) + title 给全名. -->
              <span class="fc-name" :title="file.name">{{ file.name }}</span>
              <!-- ⚠️ 2026-10-30: 以前是 `<b>×</b>` —— b 不可聚焦, **键盘用户清不掉**,
                   屏幕阅读器也读不出这是什么. 改成真 button: 能 Tab 到, 能回车触发,
                   还有 aria-label 说清清的是哪个文件. -->
              <button type="button" class="file-x" :aria-label="'清除文件 ' + file.name"
                      @click="clearFile">×</button>
            </template>
            <template v-else>
              <span class="pick-hint">未选择文件 (可以拖进来)</span>
            </template>
          </span>
        </div>
        <p class="hint">
          任意格式都行 (exe / zip / tar.gz / deb …), 单个最大
          <b>{{ formatSize(maxBytes) }}</b>. 文件原样存在服务器上, 别人下下来就是这一份.
          <br>文件名只能用<b>英文字母、数字</b>和 <b>. _ -</b>, 且必须以字母或数字开头.
        </p>
        <p v-if="fileError" class="pick-err">{{ fileError }}</p>
        <!-- ⚠️ 2026-10-30 (第十一轮): 「软件标识」那块整个删了, 但**这个错误还得说** ——
             它告诉用户"这个软件包文件名派生的标识不能用, 换个文件名" ——
             用户看不到 code 不影响他按提示换文件名. 挪到软件包这一段里. -->
        <p v-if="codeError" class="pick-err">{{ codeError }}</p>

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
              <!-- ⚠️ `label` 只放图标本身 (就一个 emoji) —— 它是**选中后输入框里
                   显示的那行字**, 之前塞了「(已被「XXX」用了)」进去, 必被截断.
                   占用人信息挪到 slot 里, 只在下拉列表那一行显示. -->
              <el-option v-for="ic in ICONS" :key="ic" :value="ic"
                         :label="ic" :disabled="isIconUsed(ic)">
                <span>{{ ic }}</span>
                <span v-if="iconOwner(ic)" class="opt-desc">已被「{{ iconOwner(ic) }}」用了</span>
              </el-option>
            </el-select>
            <p class="hint">图标别跟别人重复 —— 用过的图标会标成「已用」, 换别的吧.</p>
          </el-form-item>
        </div>

        <!-- ⚠️ 2026-10-30 (第十一轮): 这里原来放着一个「软件标识」只读输入框
             (底色写死 --ink-200, #E2E8F0 蓝灰, 在纯白面板上特别扎眼),
             后来改成显示「软件名称」的只读行 —— **现在整块删掉**:
             用户原话「软件名称去掉, 不展示这个信息, 后端维护就好了, 只要保证不冲突」.
             · code 由软件包文件名派生 (codeFromFileName), 后端还会再派生一次,
               撞名自动加序号 —— **唯一性由后端保证**, 用户不用操心, 也不用看;
             · 「软件名」输入框在上面已经有了, 再显示一遍纯属重复. -->

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
              <!-- ⚠️ `label` 是选中后输入框里显示的字 —— 必须短;
                   长的解释放 slot 里(只在下拉列表那一行显示) -->
              <el-option v-for="p in PLATFORMS" :key="p.value" :value="p.value" :label="p.label">
                <span>{{ p.label }}</span>
                <span v-if="p.desc" class="opt-desc">{{ p.desc }}</span>
              </el-option>
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

        <!-- ⚠️ 2026-10-30: **新增 / 覆盖 二选一** (用户要的能力) ——
             以前只有「新增一条」这一条路, 想换掉某个已有版本只能先把它下架.
             现在两条路都留着, 但由用户选:
               · 「新增一个版本」 → 版本列表多一条 (N → N+1)
               · 「覆盖已有版本」 → 原地改掉选中的那一条 (版本总条数不变) -->
        <div class="ver-mode" role="radiogroup" aria-label="版本处理方式">
          <button type="button" class="vm-btn" :class="{ active: versionMode === 'new' }"
                  role="radio" :aria-checked="versionMode === 'new'"
                  @click="setVersionMode('new')">
            <span class="vm-ic">➕</span>新增一个版本
          </button>
          <button type="button" class="vm-btn" :class="{ active: versionMode === 'replace' }"
                  role="radio" :aria-checked="versionMode === 'replace'"
                  :disabled="!versionOptions.length"
                  @click="setVersionMode('replace')">
            <span class="vm-ic">♻️</span>覆盖已有版本
          </button>
        </div>

        <!-- 覆盖模式: 选一个要改掉的版本 -->
        <el-form-item v-if="versionMode === 'replace'" label="要覆盖的版本" required>
          <el-select v-model="versionForm.replace_version" style="width:100%"
                     placeholder="选一个已有版本" @change="onPickReplaceTarget">
            <el-option v-for="v in versionOptions" :key="v.version" :value="v.version"
                       :label="v.version + (v.variant ? ` (${v.variant})` : '')">
              <span class="mono">{{ v.version }}</span>
              <span v-if="v.variant" class="opt-desc">{{ v.variant }}</span>
              <span v-if="v.status !== 'ready'" class="opt-desc">{{ statusLabel(v.status) }}</span>
            </el-option>
          </el-select>
          <p class="hint">
            选中的那一版会被<b>原地换掉</b> —— 版本号、说明、安装包全换成这次填的,
            版本总条数不变. 别的版本不受影响.
          </p>
        </el-form-item>

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
            {{ uploading ? '上传中…'
              : (mode === 'version'
                  ? (versionMode === 'replace' ? '覆盖这一版' : '发布新版本')
                  : '上架软件') }}
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
  ICONS, PLATFORMS, RESERVED_CODES, codeFromFileName, formatSize, splitFeatures, splitTags,
  validateCode, validateFileName, validateFileSize, validateName, validateVersion,
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
const versionForm = ref({ version: '', variant: '', is_default: true, replace_version: '' });
// ⚠️ 2026-10-30: 版本处理方式 —— 'new' = 新增一条, 'replace' = 原地覆盖某一条
/**
 * 版本处理方式 —— 默认「**覆盖已有版本**」 (2026-10-31 第十三轮, 用户要求).
 *
 * ⚠️ 但**没有可覆盖的版本时必须回落「新增」** —— 第一个版本只能新增,
 *    强行停在「覆盖」会卡住提交 (下拉是空的, required 校验过不去).
 */
const versionMode = ref<'new' | 'replace'>('replace');
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

/** 谁占了这个图标? (没人占就是空串) —— 显示在下拉选项的补充说明里 */
function iconOwner(ic: string): string {
  return config.value?.used_icons?.[ic] || '';
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
  versionForm.value.replace_version = '';
  // 版本处理方式回到「覆盖」 (默认) —— 上次覆盖过, 这次不一定还要覆盖, 用户自己切
  versionMode.value = 'replace';
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
    // ⚠️ 2026-10-31 (第十三轮): 版本处理方式默认「**覆盖已有版本**」(用户要求).
    //    ⚠️ 但**没有可覆盖的版本时回落「新增」** —— 第一个版本只能新增,
    //    停在「覆盖」的话下拉是空的, required 校验过不去, 提交直接卡住.
    versionForm.value.replace_version = '';
    if (versionOptions.value.length) {
      versionMode.value = 'replace';
      // 默认选第一个可覆盖的版本 —— 少一次点击
      onPickReplaceTarget(versionOptions.value[0].version);
    } else {
      versionMode.value = 'new';
    }
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
/** 可供「覆盖」的版本 —— 排除正在传/传失败的那种? 不排除, 一并给出 (用户可能就是要重传) */
const versionOptions = computed(() => props.item?.versions || []);
/** 版本状态的中文说法 (下拉里的补充说明) */
function statusLabel(s: string): string {
  if (s === 'ready') return '可下载';
  if (s === 'awaiting_file') return '待传文件';
  if (s === 'uploading') return '上传中';
  if (s === 'failed') return '上传失败';
  return s;
}
/** 用户填的版本号跟已发过的撞了 —— 当场提示, 别等后端 409 */
const versionDup = computed(() => {
  const v = versionForm.value.version.trim();
  if (!v) return false;
  // ⚠️ 覆盖模式下, **正在改的那一条**不算撞号 —— 同名覆盖 (1.0.0 → 1.0.0) 是合法的.
  //    撞的是别的版本 → 还是得拦 (否则页面上会出现两个同号版本).
  if (versionMode.value === 'replace' && v === versionForm.value.replace_version) return false;
  return existingVersions.value.includes(v);
});

/** 切「新增 / 覆盖」 */
function setVersionMode(m: 'new' | 'replace') {
  versionMode.value = m;
  if (m === 'replace') {
    // 默认选第一个可覆盖的版本 —— 少一次点击
    if (!versionForm.value.replace_version && versionOptions.value.length) {
      onPickReplaceTarget(versionOptions.value[0].version);
    }
  } else {
    versionForm.value.replace_version = '';
  }
}

/** 选了要覆盖的版本 → 版本号/变体预填 (版本号**可以再改**) */
function onPickReplaceTarget(v: string) {
  versionForm.value.replace_version = v;
  const hit = versionOptions.value.find((x) => x.version === v);
  if (!hit) return;
  versionForm.value.version = hit.version;
  versionForm.value.variant = hit.variant || '';
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
  // ⚠️ 文件名规范 (2026-10-28) —— **当场拒绝**, 不静默改名.
  //    静默改名用户不知道, 下载回来名字对不上更麻烦 (所以后端也不再 sanitize).
  const nameErr = validateFileName(f.name);
  if (nameErr) {
    fileError.value = nameErr;
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
  // ⚠️ 软件标识**自动生成** —— 由文件名派生 (后端也会再派生一次, 规则一致)
  if (mode.value === 'create') {
    form.value.code = codeFromFileName(f.name);
    codeError.value = '';
  }
}

function clearFile() {
  file.value = null;
  fileError.value = '';
  if (mode.value === 'create') form.value.code = '';
}

const missing = computed<string[]>(() => {
  const out: string[] = [];
  // ⚠️ 2026-10-30: 原来这里还有一条「软件标识」—— 但 code 是**从文件名派生的**,
  //    没选文件就必然没有 code, 两条一起报等于把同一件事说两遍,
  //    而且用户界面上根本看不到 code 了, 报它只会让人一头雾水.
  //    现在只报「请先选择软件包」—— code 会跟着文件名自动出来.
  if (!file.value) out.push('请先选择软件包');
  if (mode.value === 'version') {
    if (!versionForm.value.version.trim()) out.push('版本号');
    // ⚠️ 覆盖模式必须先选一个要改掉的版本
    if (versionMode.value === 'replace' && !versionForm.value.replace_version) {
      out.push('要覆盖的版本');
    }
  } else {
    if (!form.value.name.trim()) out.push('软件名');
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
    // ⚠️ code 是**自动生成**的 —— 校验不过只能让用户**换文件名**, 所以提示要说清楚
    const derived = form.value.code.trim();
    if (validateCode(derived)) {
      codeError.value = RESERVED_CODES.includes(derived)
        ? `文件名派生的标识 "${derived}" 是系统保留词 —— 换个软件包文件名吧`
        : `文件名派生的标识 "${derived}" 不合规 —— 换个软件包文件名吧`;
      return;
    }
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
  // ⚠️ 2026-10-30: 提交是**两步**: 先建条目, 再传文件.
  //    传到 90% 断线 → 条目**已经建好了** (库里多一条「待传文件」),
  //    但用户只看到一句「文件大小与声明的不一致」, 不知道条目已经存在.
  //    用户再点一次提交 → 又 POST 一次 /software → code 被占用 →
  //    后端自动改成 xxx2 **新建一条** → 库里多一条永远传不上文件的坏条目.
  //    所以要记住"建到哪一步了", 失败时把状态说清楚.
  //    ⚠️ **不改提交语义** —— 不改成"再次点击只重跑传文件" (那要后端配合, 风险大).
  let entryCreated = false;
  let createdCode = '';
  let createdVersion = '';
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
      // ⚠️ 条目建好了 —— 记下**实际用的 code** (撞名时后端会自动加序号 xxx2),
      //    失败提示里要写出来, 用户才知道自己刚才建的是哪一条.
      //    ⚠️ 变量叫 entryCreated (不叫 created) —— 块内的 `const created`
      //    会把它遮住, 赋值会报 "Assignment to constant variable".
      entryCreated = true;
      createdCode = created.code;
      createdVersion = created.version;
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
        // ⚠️ 覆盖模式: 告诉后端「把这一行原地换成我」——
        //    不传 = 照旧新增一条 (版本 N → N+1)
        replace_version: versionMode.value === 'replace'
          ? versionForm.value.replace_version.trim()
          : '',
      });
      version = created.version;
      // ⚠️ 发新版本: 建的是**版本记录** (不是软件条目) —— 失败提示要照这个说
      entryCreated = true;
      createdCode = code;
      createdVersion = created.version;
    }

    // ---- 第 ② 步: 传文件 (原始字节流, 边传边报进度) ----
    await uploadSoftwareFile(code, file.value!, (p) => {
      percent.value = p;
      uploadedBytes.value = Math.round((p / 100) * (file.value?.size || 0));
    });

    ElMessage.success(
      mode.value === 'create'
        ? '软件已上传'
        : (versionMode.value === 'replace'
            ? `版本 ${versionForm.value.replace_version} 已覆盖为 ${version}`
            : `新版本 ${version} 已发布`),
    );
    emit('done');
    emit('update:modelValue', false);
  } catch (e: any) {
    // ⚠️ 2026-10-30: 按**阶段**分开说 —— 以前不管哪一步挂了都只给一句"上传失败",
    //    用户不知道条目已经建好了, 再点一次提交就多一条坏条目.
    formError.value = submitErrorText(e, entryCreated, createdCode, createdVersion);
  } finally {
    uploading.value = false;
  }
}

/**
 * 提交失败的提示 —— **按阶段分开说** (2026-10-30).
 *
 * ⚠️ 提交是**先建条目、再传文件**两步:
 *   · 条目**没建成** (第一步就挂) → 只报失败原因, 重试一次不会多东西;
 *   · 条目**建成了**、文件没传上去 → 库里已经多了一条「待传文件」,
 *     必须**说清楚**, 否则用户再点一次提交 → 又 POST 一次 /software →
 *     code 被占用 → 后端自动加序号 → **多一条永远传不上文件的坏条目**.
 *   · 顺带告诉他怎么补救 (到条目详情发新版本, 或先下架这条).
 *
 * ⚠️ **不改提交语义** —— 不做成"再次点击只重跑传文件" (那要后端配合, 风险大).
 */
function submitErrorText(
  e: unknown,
  entryCreated: boolean,
  code: string,
  version: string,
): string {
  const reason = errText(e, '上传失败');
  if (!entryCreated) return reason;
  if (mode.value === 'version') {
    // ⚠️ 覆盖模式: 老文件**已经被换掉**了 (后端覆盖时删了旧目录),
    //    所以失败提示要说明"这一版现在没有文件" —— 用户才知道要去重新传.
    if (versionMode.value === 'replace') {
      return `版本 ${versionForm.value.replace_version} 已经覆盖成 ${version}, 但新文件没传上去（${reason}）`
        + ' —— 原来的安装包已被替换掉, 这一版现在显示为「上传失败」. 重新传一次即可.';
    }
    return `新版本 ${version} 的记录已建好, 但文件没传上去（${reason}）`
      + ' —— 这一版会显示为「上传失败」. 可以重新上传, 或者把这一版下架.';
  }
  return `软件条目已创建（标识 ${code}）, 但文件没传上去（${reason}）`
    + ' —— 库里会先显示为「待传文件」. 要重传请到该条目详情里发一个新版本, 或先下架这条.';
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
/* ⚠️ 2026-10-30: 拖拽时的视觉反馈 —— 以前 `dragging` 只写不读, 拖进来毫无变化.
   边框从虚线灰变成主色, 底色淡蓝 —— 一眼看出"松手就能放". */
.file-pick.dragging {
  border-color: var(--primary);
  background: rgba(59, 130, 246, .06);
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
  /* ⚠️ 2026-10-30: chip 本身也要能收缩 —— 它是 .file-pick 的 flex 子项,
     不给 min-width:0 的话里面的省略号不会生效 (文件名会把抽屉撑破). */
  min-width: 0; max-width: 100%; overflow: hidden;
}
/* ⚠️ 2026-10-30: 文件名单独一层 —— 名字长到 200 字符时截断, 完整名字在 title 里 */
.fc-name {
  min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* ⚠️ 2026-10-30: 清除按钮 (以前是 <b>) —— 复位按钮默认样式, 别被浏览器画成灰方块;
   flex-shrink:0 保证名字被截断时"×"不被一起截掉. */
.file-chip .file-x {
  border: none; background: none; padding: 0 2px; margin: 0;
  font: inherit; line-height: 1; color: var(--ink-500);
  cursor: pointer; flex-shrink: 0;
}
.file-chip .file-x:hover { color: var(--err); }
/* 空状态: 别带 chip 的底色 —— 那看着像"已经选了一个文件" */
.file-chip.is-empty { background: transparent; padding: 4px 0; }
.pick-hint { font-size: 12px; color: var(--ink-500); }
.pick-err { margin: 0; font-size: 11.5px; color: var(--err); }
.hint { margin: 0; font-size: 11px; color: var(--ink-500); line-height: 1.6; }

/* 下拉选项里的补充说明 (选项右侧灰字) ——
   ⚠️ 2026-10-29: 别用 float: right + max-width + ellipsis —— 那样会把说明
      **硬截断**成「…」, 用户根本读不到. 去掉 float, 让文字自然排下去.
   ⚠️ inline-block 是必须的 —— Element 的下拉项自带 nowrap + overflow:hidden,
      截断发生在选项行这一层; 说明只是 inline 元素的话, 省略号会落在整行尾巴上
      (把主标题切掉). 改成 inline-block + 自己的 max-width 后, 省略号只落在说明上. */
.opt-desc {
  display: inline-block; vertical-align: bottom;
  color: var(--ink-500); font-size: 11px;
  margin-left: 12px; max-width: 260px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}

/* ===== 版本「新增 / 覆盖」二选一 (2026-10-30) =====
   两个平铺按钮 (不是 radio) —— 一眼能看出当前走的是哪条路. */
.ver-mode {
  display: flex; gap: 8px; flex-wrap: wrap;
  margin-bottom: 4px;
}
.vm-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: var(--radius-btn);
  border: 1px solid var(--border); background: var(--fill-blank);
  color: var(--ink-700); font-size: 13px; cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
}
.vm-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.vm-btn.active {
  border-color: var(--primary); background: var(--primary-grad-soft);
  color: var(--primary); font-weight: 600;
}
.vm-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.vm-ic { font-size: 13px; }

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
