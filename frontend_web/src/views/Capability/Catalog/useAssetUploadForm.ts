/**
 * 上传表单的状态与校验 —— 从 AssetUploadDialog.vue 抽出来的.
 *
 * 为什么抽 (2026-10-25 整改):
 *   抽屉组件接近 1000 行, 而这里面是**最容易出错**的部分:
 *     · code 与包名 / MCP 连接器名的同步与一致性
 *     · "还缺什么"清单 (决定能不能上架)
 *     · 图标自动分配 (不能跟现有资产重复)
 *   这些以前全埋在组件里, 靠 watch 串起来 —— **watch 级逻辑没法单测**,
 *   只能靠 e2e 兜, 于是出了"图标被悄悄改掉""新资产不自动分配图标"这类问题.
 *
 * 抽成 composable 之后: 状态、校验、动作都在一个纯 TS 模块里, 可直接测.
 */
import { computed, reactive, ref, watch } from 'vue';
import {
  listAssets, listCategories, listProjects, previewPackage,
  type AssetItem, type MarketKind, type PackagePreview,
} from '@/api/assets';
import {
  CODE_PREFIX, FALLBACK_ICONS, GENERAL_ICONS, ICON_POOLS,
  checkCodeSync, codeFromPackageName, pickIcon, validateCode, validatePackageName,
} from './assetForm';
import { kindMeta } from './kindMeta';
import { MCP_TEMPLATE, formatMcpConfig, parseMcpConfig } from './mcpConfig';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

export interface UseAssetUploadFormOptions {
  /**
   * create = 新建资产; update = 发新版本; edit = **只改元信息** (2026-10-30).
   *
   * ⚠️ edit 与 update 的区别: update 是"发新版本" —— **必须传安装包**,
   *    版本号也会变; edit 是"改说明" —— 不碰包, 不碰版本号.
   */
  mode: () => 'create' | 'update' | 'edit';
  /** 更新/编辑时的原资产 */
  asset: () => AssetItem | null | undefined;
  /** 入口选定的形态 (空 = 让人在抽屉里选) */
  initialKind: () => MarketKind | '';
  /** 抽屉是否打开 (打开时初始化 / 重置) */
  open: () => boolean;
}

export function useAssetUploadForm(opts: UseAssetUploadFormOptions) {
  const mode = () => opts.mode();
  const asset = () => opts.asset();

  // ---------- 状态 ----------
  const fileInput = ref<HTMLInputElement | null>(null);
  const pkgFile = ref<File | null>(null);
  const preview = ref<PackagePreview | null>(null);
  const previewing = ref(false);
  /** 图标选择面板 */
  const iconPanel = ref(false);
  /** 现有资产用过的图标 —— 自动分配时避开, 免得卡片上图标重复 */
  const usedIcons = ref<Set<string>>(new Set());
  /** 用户手选过图标 → 后面名字/分类变了也别乱改 */
  const iconTouched = ref(false);
  /** 分类表 (后端下发) —— 上传/更新时只能从里面选 */
  const categories = ref<{ name: string; slug: string; desc?: string; total: number }[]>([]);
  /**
   * 分类表**加载失败的原因** —— 空串 = 没失败.
   *
   * ⚠️ 2026-10-30 整改: 以前 catch 是空的, 失败被吞成空数组 →
   *    「分类」被记成**缺项** → 页脚一直挂「还缺: 分类」, 「上架」按钮**永久置灰**,
   *    而且**看不出为什么不行** (只能关掉抽屉重开).
   *    现在把失败原因记在这里, 由界面显式告诉用户 + 给一个「重试」.
   */
  const categoriesError = ref('');
  /** 分类表正在加载 —— 下拉要显示 loading 态 (别让用户以为是"没分类") */
  const categoriesLoading = ref(false);
  /** 项目列表 (后端下发, 设置项里可改) —— 适用项目的下拉选项 */
  const projectOptions = ref<string[]>([]);

  /**
   * 表单状态 —— 只放**表单里真能填**的字段.
   *
   * 详细说明 / 不适用 / 安装步骤 / 设为精选 已经从表单里去掉了 (2026-10-24),
   * 所以它们**不在 form 里** —— 更新版本时直接取 asset 的原值提交,
   * 免得"没填"把老资产的字段清空 (也不必维护一份用不到的表单状态)。
   */
  const form = reactive({
    code: CODE_PREFIX, kind: 'skill' as MarketKind, name: '', version: '1.0.0',
    summary: '', use_when: '', category: '', icon: '🧩',
    // 适用项目: 空 = 通用 (所有项目都能用); "6100" = 6100 项目特有
    project: '',
    tags: [] as string[], files: [] as File[],
    // ⚠️ 2026-10-30: 「只改元信息」模式要能编辑这几项 ——
    //    以前上架表单里**没有**这些输入框 (2026-10-24 精简掉了),
    //    编辑时却又想改 → 只能靠"发新版本", 那太重了.
    description: '',
    not_for: '',
    // 安装步骤: 后端是**列表** (install_steps: list[str]), 表单里一行一条
    installStepsText: '',
  });
  const tagsText = ref('');
  /** 连接器 (mcp) 的 MCP 配置 (JSON 文本) */
  const mcpConfigText = ref('');
  const keywordsText = ref('');
  /** 抽屉里的第几步: pick = 选形态, form = 填配置 */
  const step = ref<'pick' | 'form'>('form');

  // ---------- 派生 ----------
  /** 连接器形态: 只有一段 MCP 配置, 没有安装包也没有 README */
  const isMcp = computed(() => form.kind === 'mcp');
  /** 「只改元信息」模式 (2026-10-30) —— 不碰安装包, 不碰版本号 */
  const isEdit = computed(() => mode() === 'edit');
  /** 当前形态的元信息 (图标 / 需要准备什么) */
  const kind = computed(() => kindMeta(form.kind));
  /**
   * MCP 配置的实时校验 (规则与后端一致).
   *
   * ⚠️ `requirePrefix` 只在**新建**时为 true —— 新上架的连接器统一叫 dml-xxx
   *    (团队命名约定); 更新**存量**连接器时不强制 (那 4 个老名字没前缀,
   *    硬拦等于把它们锁死 —— 连发个新版本都提交不了).
   */
  const mcpParsed = computed(() =>
    parseMcpConfig(mcpConfigText.value, { requirePrefix: mode() === 'create' }));
  const mcpConfigError = computed(() => {
    if (!isMcp.value) return '';
    return mcpParsed.value.ok ? '' : mcpParsed.value.error;
  });
  /**
   * MCP 配置栏上显示的那句话.
   *
   * ⚠️ **空配置不算错误** —— 刚打开抽屉还没填, 那是缺项 (底部「还缺」清单会列
   *    「MCP 配置」), 标红只会让人以为哪里填错了. 填了之后才校验对错。
   */
  const mcpHint = computed(() => {
    if (!isMcp.value) return '';
    if (!mcpConfigText.value.trim()) return '还没填配置 —— 可点「用模板」';
    return mcpConfigError.value || '✓ 配置合法';
  });
  /** 配置栏那句话的状态: idle=还没填 (中性) / ok=合法 (绿) / bad=填错了 (红) */
  const mcpHintState = computed<'idle' | 'ok' | 'bad'>(() => {
    if (!isMcp.value) return 'idle';
    if (!mcpConfigText.value.trim()) return 'idle';
    return mcpConfigError.value ? 'bad' : 'ok';
  });
  function formatMcp() {
    mcpConfigText.value = formatMcpConfig(mcpConfigText.value);
  }
  function useMcpTemplate() {
    mcpConfigText.value = MCP_TEMPLATE;
  }

  // ---------- 校验 ----------
  /**
   * 有没有"来源" —— code 就是从这儿派生的:
   *   技能/插件 → 选了安装包; 连接器 → 填了 MCP 配置.
   */
  const hasSource = computed(() => {
    // ⚠️ 编辑模式: 安装包**已经存在**了 —— 不是"缺来源", 别把它算成缺项.
    if (isEdit.value) return true;
    return isMcp.value ? !!mcpConfigText.value.trim() : !!pkgFile.value;
  });

  /**
   * code 的格式错误.
   *
   * ⚠️ code 是**派生值** (取包名 / MCP 连接器名) —— 不可编辑, 所以只在
   *    新建时报错; 更新时那是老资产的 code, 标红没有意义.
   */
  const codeError = computed(() => {
    if (mode() === 'update' || isEdit.value) return '';
    // ⚠️ 还没选包 / 没填配置时, code 还是初始的 "dml-" —— 那不是错误,
    //    是"还没派生出来". 提前标红会让人以为填错了.
    if (!hasSource.value) return '';
    return validateCode(form.code);
  });
  const versionError = computed(() => {
    const v = (form.version || '').trim();
    if (!v) return '版本必填';
    if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(v)) return '版本格式应为 1.0.0';
    return '';
  });
  /**
   * 安装包名 (去掉扩展名) —— 跟 code 应该一致
   *
   * ⚠️ 这里**没有** "请选择安装包" 这种缺项提示 —— 还没选包是缺项,
   *    底部「还缺」清单会列出来, 不是错误, 别一上来就标红.
   */
  const pkgBaseName = computed(() => codeFromPackageName(pkgFile.value?.name || ''));
  /**
   * code 与「包名 / MCP 连接器名」不一致时的报错 (空串 = 一致 / 还不用管).
   *
   * 约定: **code 就是那个名字本身** ——
   *   技能/插件 → code = 安装包名 (去扩展名)
   *   连接器     → code = MCP 配置里的连接器名
   * 不一致 → 报错 + 不让上架 (免得装出来/抄下来对不上)。
   *
   * ⚠️ 更新**连接器**时跳过: code 不可改, 用户改了 MCP 配置里的名字也没法同步 code
   *    → 硬拦等于死锁 (后端也只在 create 时强制这条, 见 market_naming)。
   */
  const codeSyncError = computed(() => {
    if (mode() === 'update' && isMcp.value) return '';
    if (isMcp.value) {
      const p = mcpParsed.value;
      const names = p.ok ? Object.keys((p.config as any)?.mcpServers || {}) : [];
      return checkCodeSync(form.code, { isMcp: true, mcpNames: names });
    }
    return checkCodeSync(form.code, { pkgBase: pkgBaseName.value });
  });

  /** code 字段上要显示的错误 (格式 + 一致性, 一起说清) */
  const codeFieldError = computed(() =>
    [codeError.value, codeSyncError.value].filter(Boolean).join('; '));
  /**
   * 安装包名本身的合法性.
   *
   * ⚠️ `requirePrefix` 只在**新建**时为 true —— 存量资产的 code 本身就没有
   *    dml- 前缀, 更新时强制前缀等于把那些资产锁死 (后端同理, 见 market_naming)。
   */
  const pkgNameError = computed(() => {
    // ⚠️ 编辑模式没有安装包 —— 别拿"包名不合规"吓人
    if (isEdit.value) return '';
    return pkgFile.value
      ? validatePackageName(pkgFile.value.name, { requirePrefix: mode() === 'create' })
      : '';
  });

  /**
   * 体检结论: 包装不上.
   *
   * ⚠️ 包名不合规 (没 dml- 开头) 也要算装不上 ——
   *    否则用户看到「体检通过」, 却又提交不了, 前后自相矛盾。
   */
  const previewBad = computed(() => {
    const p = preview.value;
    if (!p) return false;
    if (pkgNameError.value) return true;
    return !p.ok || p.issues.length > 0;
  });
  /** 体检问题清单: 服务端解包问题 + 本地包名问题 */
  const previewIssues = computed(() => {
    const p = preview.value;
    const out: string[] = [...(p?.issues || [])];
    if (pkgNameError.value) out.push(pkgNameError.value);
    return out;
  });

  /**
   * 图标可选范围: 分类池 + 通用池 + 兜底池, **并且排除已被别的资产用掉的**.
   *
   * 两条要求同时成立:
   *  ① 不重复 —— 重复图标在卡片上根本分不清谁是谁;
   *  ② 够多   —— 资产多了也得有的选, 所以三个池子都拉进来 (上百个)。
   */
  const iconChoices = computed(() => {
    const pool = ICON_POOLS[form.category] || [];
    const all = Array.from(new Set([...pool, ...GENERAL_ICONS, ...FALLBACK_ICONS]));
    return all.filter((ic) => {
      // ⚠️ 编辑模式: 资产**自己**正在用的图标也得能选 ——
      //    它本来就在"已占用"名单里 (usedIcons 是全部资产的图标),
      //    被过滤掉的话用户连"不改图标"都做不到 (下拉里根本看不到当前图标).
      if (isEdit.value && ic === asset()?.icon) return true;
      return !usedIcons.value.has(ic);
    });
  });

  /** 缺什么 —— 一次说清, 别让人点一次报一个 */
  const missing = computed(() => {
    const out: string[] = [];
    // ⚠️ 「只改元信息」模式: **不用安装包 / 不用版本 / 不用 code** ——
    //    那些东西都已经在仓库里了, 这条路只改说明文字.
    if (isEdit.value) {
      if (!form.name.trim()) out.push('名称');
      if (!form.summary.trim()) out.push('一句话简介');
      if (!form.category) {
        out.push(categoriesError.value ? '分类 (列表加载失败, 可先选「其他」)' : '分类');
      }
      return out;
    }
    if (isMcp.value) {
      // 连接器: 要配置, 不要包
      if (mcpConfigError.value) out.push('MCP 配置');
    } else if (!pkgFile.value) {
      out.push('安装包');
    }
    if (!form.name.trim()) out.push('名称');
    if (!form.summary.trim()) out.push('一句话简介');
    if (mode() === 'create' && hasSource.value) {
      // ⚠️ 只有**已经有来源** (选了包 / 填了 MCP 配置) 才校验 code ——
      //    否则 code 还是初始的 "dml-", 报了名儿用户也改不了 (它是派生值)
      const c = validateCode(form.code);
      if (c) out.push('资产 code');
      // code 必须跟包名 / MCP 连接器名一致 —— 不一致不让上架
      if (codeSyncError.value) out.push('code 与名称一致');
    }
    if (!form.category) {
      // ⚠️ 分类表加载失败时, 「还缺: 分类」是**误导** ——
      //    用户会以为自己没选 (其实下拉是空的, 选不了).
      //    说清是"列表加载失败", 并给出还能走的路 (兜底分类「其他」).
      out.push(categoriesError.value ? '分类 (列表加载失败, 可先选「其他」)' : '分类');
    }
    if (versionError.value) out.push('版本');
    if (pkgNameError.value) out.push('安装包名');
    return out;
  });
  const canSubmit = computed(() =>
    missing.value.length === 0
    && (isEdit.value || isMcp.value || (!previewBad.value && !pkgNameError.value)));

  // ---------- 加载 ----------
  async function loadCategories() {
    // ⚠️ 原来 `if (categories.value.length) return` —— 失败过一次之后**再也刷不进来**
    //    (旧列表还留着 → 直接 return → 永远重试不了). 失败时必须允许重试.
    if (categories.value.length && !categoriesError.value) return;
    categoriesLoading.value = true;
    try {
      const r = await listCategories();
      categories.value = (r?.items || []) as typeof categories.value;
      categoriesError.value = '';
    } catch (e: any) {
      // ⚠️ 原来这里是空 catch —— 失败被吞成空数组, 「上架」按钮**永久置灰**且无任何说明.
      //    现在把原因记下来: 界面会显示「分类列表加载失败」+ 一个「重试」按钮.
      categoriesError.value = httpErrorText(errorStatus(e), errorDetail(e), '未知错误');
    } finally {
      categoriesLoading.value = false;
    }
  }

  /**
   * 拉项目列表 (设置项 marketplace.projects) —— 适用项目的下拉选项.
   *
   * ⚠️ **不缓存** —— 管理员在设置里加了项目, 用户不刷新页面也得能选到.
   *    (以前只拉一次, 新项目在下拉里根本不出现)
   */
  async function loadProjects() {
    try {
      const r = await listProjects();
      projectOptions.value = (r?.items || [])
        // ⚠️ 过滤掉「通用」(is_general) —— 它是默认选项, 不是某个项目
        .filter((i: { is_general?: boolean }) => !i.is_general)
        .map((i: { code: string }) => (i.code || '').trim())
        .filter(Boolean);
    } catch {
      /* 拿不到就退回空列表 —— 只剩「通用」可选, 不影响上架 */
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
    // ⚠️ 清单拿到**之后**再分配一次 —— 否则自动分配的图标可能正好撞上别人的
    if (!iconTouched.value) autoIcon();
  }

  /** 自动分配图标 (避开已被用掉的) */
  function autoIcon() {
    // ⚠️ 更新版本 / 编辑信息时**保留原图标** —— 分配逻辑会跳过"已被占用"的图标,
    //    而这个资产自己的图标正好在占用名单里 → 结果每次都换个图标,
    //    用户完全没感知, 卡片上的图标就悄悄变了.
    if (mode() === 'update' || isEdit.value) return;
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

  // ---------- 包 ----------
  function clearPackage() {
    pkgFile.value = null;
    preview.value = null;
    if (fileInput.value) fileInput.value.value = '';
  }

  async function onPickPackage(e: Event) {
    const input = e.target as HTMLInputElement;
    pkgFile.value = input.files?.[0] ?? null;
    await runPreview();
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
        issues: ['体检失败: ' + (httpErrorText(errorStatus(e), errorDetail(e)))],
        warnings: [],
      };
    } finally {
      previewing.value = false;
    }
  }

  /**
   * 第 ① 步: 选定形态 → 直接进对应表单.
   *
   * ⚠️ 换形态要把**上一形态的专属状态**清掉 —— 否则:
   *   技能选了包 → 切到连接器 → 包还在内存里 (还带着体检结论);
   *   连接器填了 MCP 配置 → 切回技能 → code 还锁在连接器名上, 同步不进包名.
   */
  function chooseKind(k: MarketKind) {
    form.kind = k;
    if (k === 'mcp') {
      clearPackage();
    } else {
      mcpConfigText.value = '';
    }
    step.value = 'form';
  }

  // ---------- 生命周期 ----------
  /** 打开抽屉时初始化 / 重置 —— 每次都是干净的一份 */
  function reset() {
    loadCategories();
    loadProjects();
    loadUsedIcons();
    pkgFile.value = null;
    preview.value = null;
    previewing.value = false;
    iconPanel.value = false;
    // ⚠️ 必须重置: 上一轮用户手选过图标 → iconTouched 残留为 true →
    //    这次新资产的图标就**不再自动分配**了 (还可能撞上别人已用的图标)
    iconTouched.value = false;
    if (fileInput.value) fileInput.value.value = '';
    const a = asset();
    if ((mode() === 'update' || isEdit.value) && a) {
      step.value = 'form';
      form.code = a.code; form.kind = a.kind; form.name = a.name; form.version = a.version;
      form.summary = a.summary;
      form.use_when = a.use_when;
      form.category = a.category; form.icon = a.icon;
      form.project = a.project || '';   // 适用项目: 带出原值 (可改)
      // 连接器: 带出老配置 (发布新版本 = 只改这段配置)
      mcpConfigText.value = a.mcp_config ? JSON.stringify(a.mcp_config, null, 2) : '';
      form.tags = [...a.tags];
      form.files = [];
      tagsText.value = (a.tags || []).join(', ');
      keywordsText.value = (a.keywords || []).join(', ');
      // ⚠️ 2026-10-30: 编辑模式要能改这几项 —— 上架表单里没有这些输入框
      form.description = a.description || '';
      form.not_for = a.not_for || '';
      form.installStepsText = (a.install_steps || []).join('\n');
    } else {
      // 新建: 形态在入口就选好了 (initialKind) —— 直接进对应表单;
      // 没带形态 (别处打开) 就先走第 ① 步让人选, 别再默认「技能」。
      const k = (opts.initialKind() || 'skill') as MarketKind;
      Object.assign(form, {
        code: CODE_PREFIX, kind: k, name: '', version: '1.0.0', summary: '',
        use_when: '', category: '', icon: '🧩',
        project: '',        // 新建默认通用
        tags: [], files: [],
        // ⚠️ 2026-10-30: 新建时这几个字段没有输入框 —— 重置干净,
        //    别把上一个资产的说明文字带进新建表单.
        description: '', not_for: '', installStepsText: '',
      });
      step.value = opts.initialKind() ? 'form' : 'pick';
      tagsText.value = ''; keywordsText.value = '';
      mcpConfigText.value = '';
    }
  }

  /**
   * 选了包 → code 自动跟包名一致.
   *
   * ⚠️ 放在 watch 里而不是 onPickPackage 里 —— 这样**任何**途径换包都会同步
   *    (也才好单测); code 是派生值, 用户改不了它.
   */
  watch(() => pkgFile.value, (f) => {
    if (mode() !== 'create') return;
    const derived = codeFromPackageName(f?.name || '');
    if (derived) form.code = derived;
  });

  // 类型变了, 体检结论也得重算 (skill 要 SKILL.md, plugin 要 plugin.json)
  watch(() => form.kind, () => {
    if (pkgFile.value) runPreview();
  });

  // 名字/简介/分类变了 → 图标跟着重新猜 (但用户手选过就别乱动)
  watch(() => [form.name, form.summary], () => {
    if (!iconTouched.value) autoIcon();
  });

  /**
   * MCP 配置变了 → code 跟着配置里的连接器名走 (用户没手改过时).
   *
   * ⚠️ 只在**新建**时同步 —— 更新时 code 不可改 (后端也只允许改配置, 不改 code).
   *    连接器名在新建时得是 dml- 开头 (配置校验会拦), 这里原样带成 code, 不另做加工.
   */
  watch(() => mcpConfigText.value, () => {
    if (mode() !== 'create' || !isMcp.value) return;
    const p = mcpParsed.value;
    if (!p.ok) return;
    const names = Object.keys((p.config as any)?.mcpServers || {});
    const slug = (names[0] || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    if (!slug) return;
    form.code = slug;
  });

  return {
    // 状态
    form, tagsText, keywordsText, mcpConfigText, step, hasSource,
    fileInput, pkgFile, preview, previewing, iconPanel, usedIcons, iconTouched,
    categories, categoriesError, categoriesLoading, projectOptions,
    // 派生
    isMcp, isEdit, kind, mcpParsed, mcpConfigError, mcpHint, mcpHintState,
    codeError, codeFieldError,
    codeSyncError, versionError, pkgNameError, pkgBaseName,
    previewBad, previewIssues, iconChoices, missing, canSubmit,
    // 动作
    formatMcp, useMcpTemplate, loadCategories, loadProjects, loadUsedIcons,
    autoIcon, onCategoryChange, chooseIcon, clearPackage, onPickPackage,
    runPreview, chooseKind, reset,
  };
}
