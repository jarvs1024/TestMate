/**
 * 三种资产形态的元信息 —— **市场页入口**与**上传抽屉**共用同一份,
 * 免得两处各写一套说辞, 改一边忘了另一边。
 *
 * 为什么要有这个文件 (2026-10-24):
 *   以前上传抽屉默认就是「技能」, 要传连接器得先滚到基础信息里改类型下拉,
 *   改了才知道表单会换成 JSON 配置 —— 选类型这一步被藏起来了。
 *   现在: 点「上传资产」→ 先选形态 → 直接进对应表单; 类型元信息集中在这里。
 *
 * 三种形态的差别:
 *   技能 / 插件 → 上传安装包 (zip), 靠包里的文档 + 清单说话
 *   连接器     → **只填一段 MCP JSON 配置**, 没有安装包, 也没有 README
 */
import type { MarketKind } from '@/api/assets';

export interface KindMeta {
  /** 类型值 (后端 kind) */
  value: MarketKind;
  /** 中文名 */
  label: string;
  /** 英文名 (后端 kind 原样) */
  code: string;
  /** 卡片图标 */
  icon: string;
  /** 一句话: 它是什么 */
  tagline: string;
  /** 需要准备什么 —— 给用户看, 免得选错了才被拦 */
  needs: string[];
  /** 表单顶部提示: 这一步要填什么 */
  formHint: string;
}

/** 三种形态 —— 顺序即展示顺序 (技能 → 插件 → 连接器) */
export const KIND_META: KindMeta[] = [
  {
    value: 'skill',
    label: '技能',
    code: 'skill',
    icon: '🧠',
    tagline: '一段可复用的方法与知识, 装进宿主后 Agent 直接照着做',
    needs: [
      '上传一个 .zip 安装包',
      '包内含 SKILL.md (它就是展示文档)',
      '包名 = 资产 code',
    ],
    formHint: '上传安装包 —— 包里要有 SKILL.md',
  },
  {
    value: 'plugin',
    label: '插件',
    code: 'plugin',
    icon: '🧩',
    tagline: '带命令、脚本和工具的扩展包, 能真的动手干活',
    needs: [
      '上传一个 .zip 安装包',
      '包内含 README.md + .qoder-plugin/plugin.json',
      '包名 = 资产 code',
    ],
    formHint: '上传安装包 —— 包里要有 README.md 和 plugin.json',
  },
  {
    value: 'mcp',
    label: '连接器',
    code: 'mcp',
    icon: '🔌',
    tagline: '一段 MCP 配置, 让宿主连到外部服务 —— 不用打包',
    needs: [
      '准备一段 MCP JSON 配置',
      '形如 {"mcpServers": {"名字": {...}}}',
      '不需要安装包, 也没有 README',
    ],
    formHint: '只填一段 MCP JSON 配置 —— 不需要安装包',
  },
];

/** 取某个类型的元信息 (未知类型兜底回技能) */
export function kindMeta(kind: MarketKind | string | undefined | null): KindMeta {
  return KIND_META.find((k) => k.value === kind) || KIND_META[0];
}
