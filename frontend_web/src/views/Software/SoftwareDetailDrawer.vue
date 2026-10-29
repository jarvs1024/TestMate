<template>
  <el-drawer :model-value="modelValue" size="720px" direction="rtl"
             :title="item ? `软件详情 · ${item.name}` : '软件详情'"
             :close-on-click-modal="false" class="sw-drawer"
             @update:model-value="emit('update:modelValue', $event)">
    <!-- ⚠️ 加载中 / 加载失败 / 没数据 —— 三种状态必须**分开** (2026-10-30).
         以前失败时**不清 item**, 抽屉继续渲染**上一个软件的旧数据** ——
         「打开 B 但 B 读失败」时, 抽屉里显示的还是 A 的名字/版本历史,
         用户以为在看 B, 点下载下到的却是 A 的包 —— 下错包.
         所以失败要**明说失败**, 不能拿"读不到详情"冒充"还在加载". -->
    <div v-if="loading" class="state">
      <div class="spinner" />
      <div>正在读取…</div>
    </div>
    <div v-else-if="loadError" class="state err">
      <div style="font-size: 28px">⚠️</div>
      <div>加载失败：{{ loadError }}</div>
      <button class="reset" @click="load">重试</button>
    </div>
    <div v-else-if="!item" class="state">
      <div>读不到这个软件的详情</div>
      <button v-if="code" class="reset" @click="load">重试</button>
    </div>

    <div v-else class="sw-body">
      <!-- ===== 头部: 图标 / 名称 / 版本 / 状态 ===== -->
      <div class="sw-hd">
        <div class="sw-icon">{{ item.icon || '🧰' }}</div>
        <div class="sw-hd-main">
          <div class="sw-name">{{ item.name }}</div>
          <div class="sw-sub mono">
            {{ item.version || '—' }}
            <template v-if="item.category"> · {{ item.category }}</template>
            <!-- ⚠️ 平台显示走 platformLabel —— 以前直接显示 'windows',
                 跟上传表单里的 'Windows' 两种写法 (后端存的仍是小写原值) -->
            <template v-if="item.platform"> · {{ platformLabel(item.platform) }}</template>
          </div>
          <!-- ⚠️ 软件挂多个版本时, 标题区要**说清推荐下哪个** (2026-10-28) -->
          <div v-if="versions.length > 1" class="sw-sub">
            共 {{ versions.length }} 个版本 · 推荐下载
            <b class="mono">{{ defaultLabel }}</b>
          </div>
        </div>
        <div class="sw-hd-actions">
          <button class="mini-btn primary" :disabled="!item.download_version"
                  @click="doDownload(item.download_version)">
            ⬇ 下载{{ item.download_version ? ` ${defaultLabel}` : '' }}
          </button>
          <button v-if="item.can_edit" class="mini-btn" @click="emit('new-version', item)">
            ↑ 发布新版本
          </button>
        </div>
      </div>

      <!-- ⚠️ 状态提示条 —— 「待传文件」「已删除」这类信息必须说出来, 别让人以为一切正常 -->
      <div v-if="item.publish_status === 'awaiting_file'" class="sw-note warn">
        🕐 这个软件的信息填好了, 但文件还没传完 —— 现在还不能下载.
      </div>
      <div v-else-if="item.publish_status === 'hidden'" class="sw-note warn">
        ⚠️ 这个软件已被删除 (文件仍保留在服务器上, 管理员可以彻底清理).
      </div>
      <div v-else-if="!item.download_version" class="sw-note warn">
        ❌ 还没有可下载的文件 —— 发一个新版本并把包传上来.
      </div>

      <!-- ===== 简介 ===== -->
      <p v-if="item.summary" class="sw-summary">{{ item.summary }}</p>

      <!-- ===== 功能清单 ===== -->
      <section v-if="item.features?.length" class="sw-sec">
        <div class="sec-h"><span class="sec-no">{{ secNos.features }}</span>功能</div>
        <ul class="feature-list">
          <li v-for="(f, i) in item.features" :key="i">{{ f }}</li>
        </ul>
      </section>

      <!-- ===== 详情 ===== -->
      <section v-if="item.description" class="sw-sec">
        <div class="sec-h"><span class="sec-no">{{ secNos.description }}</span>详情</div>
        <div class="pre-wrap">{{ item.description }}</div>
      </section>

      <!-- ===== 适用场景 ===== -->
      <section v-if="item.use_when || item.not_for" class="sw-sec">
        <div class="sec-h"><span class="sec-no">{{ secNos.use }}</span>适用场景</div>
        <div v-if="item.use_when" class="use-block ok">
          <span class="ub-tag">适合</span>
          <span class="ub-text pre-wrap">{{ item.use_when }}</span>
        </div>
        <div v-if="item.not_for" class="use-block no">
          <span class="ub-tag">不适合</span>
          <span class="ub-text pre-wrap">{{ item.not_for }}</span>
        </div>
      </section>

      <!-- ===== 安装说明 (选填) ===== -->
      <section v-if="item.install_steps" class="sw-sec">
        <div class="sec-h"><span class="sec-no">{{ secNos.install }}</span>安装说明</div>
        <ol class="step-list">
          <li v-for="(s, i) in installStepList" :key="i">{{ s }}</li>
        </ol>
      </section>

      <!-- ===== 注意事项 (选填) —— 醒目一点, 免得别人踩坑 ===== -->
      <section v-if="item.caveats" class="sw-sec">
        <div class="sec-h"><span class="sec-no">{{ secNos.caveats }}</span>注意事项</div>
        <div class="caveat-box">
          <span class="cb-icon">⚠</span>
          <div class="pre-wrap">{{ item.caveats }}</div>
        </div>
      </section>

      <!-- ===== 版本历史 ===== -->
      <section class="sw-sec">
        <div class="sec-h">
          <span class="sec-no">{{ secNos.versions }}</span>版本与更新说明
          <span class="sec-tip">{{ versions.length }} 个版本</span>
        </div>
        <div v-if="!versions.length" class="empty">还没有版本记录</div>
        <div v-for="v in versions" :key="v.id" class="ver-row" :class="v.status">
          <div class="vr-hd">
            <span class="vr-ver mono">{{ v.version }}</span>
            <!-- ⚠️ 变体标签 —— 两个版本并存时靠它区分谁是谁 (2026-10-28) -->
            <span v-if="v.variant" class="vr-variant">{{ v.variant }}</span>
            <!-- ⚠️ 推荐标记 —— 头部那个「⬇ 下载」下的就是它 -->
            <span v-if="v.is_default" class="vr-default">推荐</span>
            <span class="vr-status" :class="`vs-${v.status}`">{{ statusLabel(v.status) }}</span>
            <span class="vr-size mono">{{ formatSize(v.file_size) }}</span>
            <button v-if="v.status === 'ready'" class="mini-btn" @click="doDownload(v.version)">⬇ 下载</button>
            <!-- ⚠️ 设为推荐 / 取消推荐 (2026-10-28) -->
            <button v-if="item.can_edit && v.status === 'ready' && !v.is_default"
                    class="mini-btn" @click="setDefault(v)">
              ⭐ 设为推荐
            </button>
            <!-- ⚠️ 单版本下架 —— 只删这一个版本, 其他版本不受影响 -->
            <button v-if="item.can_edit" class="mini-btn danger-ghost" @click="onDeleteVersion(v)">
              下架这版
            </button>
          </div>
          <div class="vr-notes">{{ v.release_notes || '（这次没写更新说明）' }}</div>
          <div class="vr-meta mono">
            {{ v.author || '未知' }} · {{ shortDate(v.created_at) }}
            <template v-if="v.sha256"> · sha256 {{ v.sha256.slice(0, 12) }}…</template>
            <template v-if="v.download_count"> · 已下载 {{ v.download_count }} 次</template>
          </div>
          <!-- ⚠️ 上传失败要把原因说出来 (后端记的 last_error) -->
          <div v-if="v.status === 'failed'" class="vr-err">上传失败: {{ v.last_error || '未知原因' }}</div>
        </div>
      </section>

      <!-- ===== 标签 / 元信息 ===== -->
      <section v-if="item.tags?.length || item.keywords?.length" class="sw-sec">
        <div class="sec-h"><span class="sec-no">{{ secNos.tags }}</span>标签</div>
        <div class="ac-tags">
          <span v-for="t in item.tags" :key="t" class="tag">#{{ t }}</span>
          <span v-for="k in item.keywords" :key="'k' + k" class="tag kw">{{ k }}</span>
        </div>
      </section>

      <div class="sw-foot mono">
        上传者 {{ item.author || '未知' }} · 创建 {{ shortDate(item.created_at) }} ·
        更新 {{ shortDate(item.updated_at) }} · 已下载 {{ item.download_count || 0 }} 次
      </div>

      <!-- ===== 危险操作 ===== -->
      <!-- ⚠️ 2026-10-28: 以前是两个按钮 (删除=软删留文件 / 彻底清理=删文件, 仅管理员),
           绕。现在合成一个「下架软件」: **谁上架的谁就能下架, 不用管理员审批**,
           管理员照旧能下架任何人的. 下架 = 条目和文件一起没. -->
      <div v-if="item.can_edit" class="sw-danger">
        <button class="mini-btn danger" @click="onUnpublish">下架这个软件</button>
        <!-- ⚠️ 2026-10-30: 以前这里写的是「文件**一起删掉**」——
             这块是**普通文本** (不是 Markdown), 星号会原样显示给用户.
             去掉星号, 用「也会一起删掉」这种说法. -->
        <span class="danger-tip">下架后这个软件会从列表里消失, 服务器上的文件也会一起删掉, 不可恢复.</span>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  deleteSoftwareVersion, downloadSoftware, getSoftware, purgeSoftware,
  updateSoftwareVersion,
  type SoftwareDetail, type SoftwareVersion,
} from '@/api/software';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';
import { fmtDate } from '@/utils/format';
import { formatSize, platformLabel } from './softwareForm';

const props = defineProps<{
  modelValue: boolean;
  code: string | null;
  /**
   * 刷新计数 —— 外面改了数据就 +1, 抽屉重新读一次.
   *
   * ⚠️ 为什么需要它: 抽屉是**常驻**的 (v-model 一直开着), 路由/抽屉都不会重建它.
   *    在抽屉里发完新版本, 抽屉里的版本历史还是旧的 —— 用户会以为"新版本没传上去".
   */
  refreshKey?: number;
}>();
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void;
  (e: 'changed'): void;
  (e: 'new-version', item: SoftwareDetail): void;
}>();

const item = ref<SoftwareDetail | null>(null);
const versions = ref<SoftwareVersion[]>([]);
const loading = ref(false);
/**
 * 加载失败的原因 —— 空串 = 没失败.
 *
 * ⚠️ 2026-10-30: 以前失败只有一句 toast, 正文分支 `v-else-if="!item"` 是**死代码**
 *    (item 从来不清空) —— 用户看到的是**上一个软件**的旧数据.
 *    单独一个 ref, 才能把"加载失败"和"没有数据"分开说.
 */
const loadError = ref('');

/**
 * 详情页各区块的**连续编号** —— 条件渲染的块不占号.
 *
 * ⚠️ 2026-10-28: 以前这里是硬编码的 1..7, 但每个块都是 `v-if` 条件渲染 ——
 *    没有功能清单就从 2 开始, 没有安装说明就 1→2→3→5, 跳号.
 *    跟这次「上架页去掉详情/不适合的场景」直接相关: 新条目更常缺这两块,
 *    编号跳得更扎眼. 现在按**实际显示出来的块**依次编号.
 */
const secNos = computed(() => {
  const it = item.value;
  const out: Record<string, number> = {};
  let n = 0;
  const take = () => ++n;
  if (it?.features?.length) out.features = take();
  if (it?.description) out.description = take();
  if (it?.use_when || it?.not_for) out.use = take();
  if (it?.install_steps) out.install = take();
  if (it?.caveats) out.caveats = take();
  out.versions = take();          // 版本历史总是显示
  if (it?.tags?.length || it?.keywords?.length) out.tags = take();
  return out;
});

/**
 * 推荐下载版本的显示名 —— 版本号 + 变体标签 (有的话).
 *
 * ⚠️ 2026-10-28: 一个软件挂两个版本时, 光显示 "1.2.0" 用户不知道该下哪个 ——
 *    所以带上网标的标签, 比如「1.2.0 LTS版」.
 */
const defaultLabel = computed(() => {
  const v = versions.value.find((x) => x.is_default);
  if (!v) return item.value?.download_version || '';
  return v.variant ? `${v.version} ${v.variant}` : v.version;
});

/** 安装说明 —— 一行一条 (空行忽略) */
const installStepList = computed(() =>
  (item.value?.install_steps || '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean),
);

// ⚠️ 不再单独判断 admin —— 「下架软件」对**上传者本人**和**管理员**都显示
//    (后端 _assert_can_modify 才是真正的闸: 上传者本人 或 管理员).

function errText(e: unknown, fallback: string): string {
  return httpErrorText(errorStatus(e), errorDetail(e), fallback);
}

async function load() {
  if (!props.code) return;
  loading.value = true;
  loadError.value = '';
  // ⚠️ 2026-10-30: **先把上一个软件的数据清掉** ——
  //    以前只在成功分支写 item.value, 失败分支只弹个 toast, item 里还留着
  //    **上一个软件**的数据. 于是「打开 B 但 B 读失败」时, 抽屉正文和标题
  //    还是 A 的 —— 用户以为在看 B, 点下载下到的却是 A 的包 (下错包).
  item.value = null;
  versions.value = [];
  try {
    const d = await getSoftware(props.code);
    item.value = d;
    versions.value = d.versions || [];
  } catch (e: any) {
    // ⚠️ 404 = 这个条目**已经不在了** (刚被下架 / 被删) —— 静默关掉抽屉.
    //    以前这里一律弹红错, 用户看到的是"下架成功" + 紧接着一条
    //    「软件 xxx 不存在」—— 明明成功却报错了, 看着像坏了.
    if (errorStatus(e) === 404) {
      emit('update:modelValue', false);
      return;
    }
    // ⚠️ 失败原因记进 loadError —— 正文里显示"加载失败: 原因" + 重试按钮,
    //    免得用户对着上一个软件的旧数据发呆.
    loadError.value = errText(e, '读取软件详情失败');
    ElMessage.error(loadError.value);
  } finally {
    loading.value = false;
  }
}

watch(() => [props.modelValue, props.code], ([open]) => {
  if (open) load();
});

// ⚠️ 外面说"数据变了" → 重新读一次 (发完新版本 / 删完之后)
watch(() => props.refreshKey, () => {
  if (props.modelValue) load();
});

async function doDownload(version: string) {
  if (!item.value || !version) return;
  try {
    await downloadSoftware(item.value.code, version);
  } catch (e: any) {
    ElMessage.error(errText(e, '拿下载票据失败'));
  }
}

/**
 * 把某个版本设成**推荐下载**的那个.
 *
 * ⚠️ 2026-10-28: 一个软件挂两个版本、两个都有用时, "该下哪个" 得有人说了算.
 *    后端保证推荐位唯一 —— 设了新的, 旧的自动摘掉.
 */
async function setDefault(v: SoftwareVersion) {
  if (!item.value) return;
  try {
    await updateSoftwareVersion(item.value.code, v.version, { is_default: true });
    ElMessage.success(`已把 ${v.version} 设为推荐下载版本`);
    await load();
  } catch (e: any) {
    ElMessage.error(errText(e, '设置推荐版本失败'));
  }
}

/**
 * **下架单个版本** —— 只删这一个版本的文件, 其他版本照旧能下.
 *
 * ⚠️ 2026-10-28: 传错的那一版要能单独撤掉, 不能为了删一个版本
 *    把整个软件连别的版本一起下架.
 */
async function onDeleteVersion(v: SoftwareVersion) {
  if (!item.value) return;
  // ⚠️ 这是**唯一**能下载的版本吗? —— 那删掉它整个软件就一并下架了,
  //    确认框必须说清楚, 不然用户以为只撤了一个版本.
  const isLast = versions.value.filter((x) => x.status === 'ready').length <= 1;
  try {
    // ⚠️ 2026-10-30: ElMessageBox 是**纯文本**, **不渲染 Markdown** ——
    //    以前这里写了 `**最后一个**` / `**文件会被删掉**`, 用户看到的是字面的星号.
    //    改成纯文本说法.
    //    ⚠️ 也**不要**把 dangerouslyUseHTMLString 改成 true —— 正文里插了软件名,
    //    开了就是 HTML 注入面 (软件名带标签就能把确认框的内容换掉).
    await ElMessageBox.confirm(
      isLast
        ? `确定下架版本 ${v.version} 吗?\n\n`
          + '这是最后一个可下载版本 —— 下架后这个软件会一起从软件库里消失, '
          + '文件也会被删掉, 不可恢复.'
        : `确定下架版本 ${v.version} 吗?\n\n`
          + '这个版本的文件会被删掉, 不可恢复. 其他版本不受影响.',
      '下架这个版本',
      {
        type: 'warning',
        confirmButtonText: '下架这版',
        cancelButtonText: '取消',
        confirmButtonClass: 'mini-btn danger',
        // ⚠️ 保持 false —— ElMessageBox 是纯文本, 不渲染 Markdown
        dangerouslyUseHTMLString: false,
      },
    );
  } catch {
    return; // 用户取消
  }
  try {
    const r = await deleteSoftwareVersion(item.value.code, v.version);
    // ⚠️ 后端把"条目被连带下架"告诉了我们 (2026-10-28) ——
    //    这时**再去查详情必然 404** (条目已经软删了). 所以:
    //    关抽屉 + 刷新列表, 不查详情, 也不弹红错.
    if (r.item_unpublished) {
      ElMessage.success(
        `版本 ${v.version} 已下架 · 这是最后一个版本, 软件已一并下架`,
      );
      emit('update:modelValue', false);
      emit('changed');
      return;
    }
    ElMessage.success(`版本 ${v.version} 已下架`);
    await load();
    emit('changed');
  } catch (e: any) {
    ElMessage.error(errText(e, '下架版本失败'));
  }
}

/**
 * 下架 —— 条目和文件一起删.
 *
 * ⚠️ 2026-10-28: 以前这里有两个按钮 (删除=软删留文件 / 彻底清理=删文件且仅管理员),
 *    绕。现在合并成一个「下架软件」:
 *    · **谁上架的谁就能下架**, 不用等管理员审批 (后端 _assert_can_modify);
 *    · 管理员照旧能下架/更新任何人的软件;
 *    · 下架即删除 —— 文件本体也一起删, 所以确认框要说清楚不可恢复.
 */
async function onUnpublish() {
  if (!item.value) return;
  try {
    // ⚠️ 2026-10-30: ElMessageBox 是**纯文本**, 不渲染 Markdown ——
    //    以前写的是「软件包**也会一起删掉**」, 用户看到的是字面的星号.
    //    ⚠️ 也**不要**开 dangerouslyUseHTMLString —— 正文里插了软件名,
    //    开了就是 HTML 注入面.
    await ElMessageBox.confirm(
      `确定下架「${item.value.name}」吗?\n\n下架后它会从软件库里消失, ` +
      '服务器上的软件包也会一起删掉, 不可恢复。',
      '下架软件',
      {
        type: 'warning',
        confirmButtonText: '下架',
        cancelButtonText: '取消',
        confirmButtonClass: 'mini-btn danger',
        // ⚠️ 保持 false —— ElMessageBox 是纯文本, 不渲染 Markdown
        dangerouslyUseHTMLString: false,
      },
    );
  } catch {
    return; // 用户取消
  }
  try {
    const r = await purgeSoftware(item.value.code);
    ElMessage.success(`已下架 (${r.deleted_files || 0} 个版本的文件一并删除)`);
    // ⚠️ **先关抽屉再刷新列表** —— 反过来的话, 父组件刷新 `refreshKey` 会在
    //    抽屉还开着的时候触发一次详情查询, 而条目已经被删了 → 404.
    emit('update:modelValue', false);
    emit('changed');
  } catch (e: any) {
    ElMessage.error(errText(e, '下架失败'));
  }
}

function shortDate(iso: string | null): string {
  // ⚠️ 以前是 `iso.slice(0, 10)` —— 直接截字符串, 显示的是 **UTC 那一天**,
  //    跟页面上其它按本地时区显示的时间对不上 (晚上更新的资产差一天).
  return fmtDate(iso);
}

function statusLabel(s: string): string {
  if (s === 'ready') return '可下载';
  if (s === 'uploading') return '上传中';
  if (s === 'failed') return '上传失败';
  return '待传文件';
}
</script>

<style scoped>
.sw-body { display: flex; flex-direction: column; gap: 14px; }
/* ⚠️ 加载中 / 失败 / 没数据 —— 跟列表页 (index.vue) 同一套写法,
   别一个页面转圈一个页面光秃秃一句字 */
.state {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  padding: 30px 0; color: var(--ink-500); font-size: 13px;
}
.state.err { color: var(--err); }
.spinner {
  width: 22px; height: 22px; border-radius: 50%;
  border: 2px solid var(--border); border-top-color: var(--primary);
  animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
/* 「重试」按钮 —— 跟列表页 .reset 同一套 (失败后必须给个重试入口) */
.reset {
  border: 1px solid var(--border); background: var(--surface);
  border-radius: var(--radius-btn); padding: 5px 13px;
  font-size: 12px; color: var(--ink-700); cursor: pointer; font-family: inherit;
}
.reset:hover { border-color: var(--primary); color: var(--primary); }

.sw-hd { display: flex; gap: 12px; align-items: flex-start; }
.sw-icon {
  width: 42px; height: 42px; border-radius: 11px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 21px; flex-shrink: 0; box-shadow: var(--primary-shadow);
}
.sw-hd-main { flex: 1; min-width: 0; }
.sw-name { font-size: 17px; font-weight: 700; color: var(--ink-900); line-height: 1.25; }
.sw-sub { font-size: 11.5px; color: var(--ink-500); margin-top: 3px; }
.sw-hd-actions { display: flex; gap: 7px; flex-shrink: 0; }

.sw-note {
  padding: 8px 11px; border-radius: var(--radius-sm); font-size: 12px;
  background: rgba(245, 158, 11, 0.10); color: var(--warn);
  border: 1px solid rgba(245, 158, 11, 0.25);
}

.sw-summary { margin: 0; font-size: 13px; color: var(--ink-700); line-height: 1.6; }

.sw-sec { display: flex; flex-direction: column; gap: 8px; }
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
.sec-tip { font-size: 10.5px; color: var(--ink-500); font-weight: 400; margin-left: auto; }

.feature-list { margin: 0; padding-left: 18px; font-size: 12.5px; color: var(--ink-700); line-height: 1.75; }
.pre-wrap { white-space: pre-wrap; word-break: break-word; font-size: 12.5px; color: var(--ink-700); line-height: 1.65; }

/* ===== 安装说明 (选填) ===== */
.step-list {
  margin: 0; padding-left: 20px;
  font-size: 12.5px; color: var(--ink-700); line-height: 1.75;
}
.step-list li { margin-bottom: 2px; }

/* ===== 注意事项 (选填) —— 醒目, 免得别人踩坑 ===== */
.caveat-box {
  display: flex; gap: 8px; align-items: flex-start;
  padding: 9px 11px; border-radius: var(--radius-sm);
  background: rgba(245, 158, 11, 0.09);
  border: 1px solid rgba(245, 158, 11, 0.28);
}
.cb-icon { flex-shrink: 0; font-size: 13px; color: var(--warn); }
.caveat-box .pre-wrap { color: var(--ink-800, #374151); }

/* ===== 版本变体标签 / 推荐标记 (2026-10-28) ===== */
.vr-variant {
  font-size: 10.5px; padding: 2px 7px; border-radius: var(--radius-pill);
  background: rgba(59, 130, 246, 0.12); color: var(--primary);
  font-weight: 600;
}
.vr-default {
  font-size: 10.5px; padding: 2px 7px; border-radius: var(--radius-pill);
  background: rgba(16, 185, 129, 0.14); color: var(--ok); font-weight: 700;
}

.use-block { display: flex; gap: 8px; align-items: flex-start; font-size: 12.5px; }
.ub-tag {
  flex-shrink: 0; padding: 2px 7px; border-radius: var(--radius-pill);
  font-size: 10.5px; font-weight: 600;
}
.use-block.ok .ub-tag { background: rgba(16, 185, 129, 0.12); color: var(--ok); }
.use-block.no .ub-tag { background: rgba(239, 68, 68, 0.10); color: var(--err); }
.ub-text { color: var(--ink-700); line-height: 1.6; }

.ver-row {
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 9px 11px; display: flex; flex-direction: column; gap: 5px;
  background: var(--surface-soft);
}
.ver-row.vs-failed, .ver-row.failed { border-color: rgba(239, 68, 68, 0.35); }
.vr-hd { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.vr-ver { font-size: 12.5px; font-weight: 700; color: var(--ink-900); }
.vr-status { font-size: 10.5px; padding: 2px 7px; border-radius: var(--radius-pill); font-weight: 600; }
.vs-ready { background: rgba(16, 185, 129, 0.12); color: var(--ok); }
.vs-awaiting_file { background: rgba(245, 158, 11, 0.12); color: var(--warn); }
.vs-uploading { background: rgba(59, 130, 246, 0.12); color: var(--primary); }
.vs-failed { background: rgba(239, 68, 68, 0.10); color: var(--err); }
.vr-size { font-size: 10.5px; color: var(--ink-500); margin-left: auto; }
.vr-notes { font-size: 12.5px; color: var(--ink-700); line-height: 1.6; white-space: pre-wrap; }
.vr-meta { font-size: 10px; color: var(--ink-500); }
.vr-err { font-size: 11px; color: var(--err); }

.empty { font-size: 12px; color: var(--ink-500); }

.ac-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.tag {
  font-size: 10px; color: var(--ink-500); background: var(--surface-sunken);
  padding: 2px 6px; border-radius: var(--radius-sm); font-family: var(--font-mono);
}
.tag.kw { color: var(--primary-2); }

.sw-foot { font-size: 10.5px; color: var(--ink-500); border-top: 1px dashed var(--border); padding-top: 9px; }

.sw-danger {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding-top: 10px; border-top: 1px solid var(--border);
}
.danger-tip { font-size: 10.5px; color: var(--ink-500); }
</style>
