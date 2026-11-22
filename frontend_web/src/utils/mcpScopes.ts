/**
 * MCP 权限的中文文案与所属系统。
 *
 * ⚠️ 访问令牌按系统分组展示（TestMate / PingCode / PLM）——
 *    用户要一眼看出一个令牌能碰哪个系统的数据，而不是看裸 scope 字符串。
 *    新增 scope 时先在后端 oauth.SCOPE_ORDER 注册，再来这里补文案。
 */
import type { McpScope } from '@/api/mcp';

export type ScopeSystem = 'testmate' | 'pingcode' | 'plm';

export interface ScopeSystemMeta {
  code: ScopeSystem;
  label: string;
  hint: string;
  enabled: boolean;
}

export const SCOPE_SYSTEMS: ScopeSystemMeta[] = [
  { code: 'testmate', label: 'TestMate', hint: '平台内的扩展与知识库', enabled: true },
  { code: 'pingcode', label: 'PingCode', hint: '外部缺陷/需求系统', enabled: true },
  { code: 'plm', label: 'PLM', hint: '外部问题单与用例库系统', enabled: true },
];

export interface ScopeMeta {
  label: string;
  description: string;
  system: ScopeSystem;
}

export const SCOPE_INFO: Record<McpScope, ScopeMeta> = {
  'extensions:read': {
    label: '读取资产',
    description: '查看插件、技能、连接器及其版本信息，并读取你本可访问的内容。',
    system: 'testmate',
  },
  'extensions:write': {
    label: '管理资产',
    description: '以你的名义新建、修改、发布或下架你有权操作的插件、技能和连接器。',
    system: 'testmate',
  },
  'kb:read': {
    label: '读取知识库',
    description: '查看数据集、文档与分段，并按问题检索知识库内容。',
    system: 'testmate',
  },
  'kb:write': {
    label: '写入知识库',
    description: '在你可操作的数据集里新建数据集、上传或替换文档、重新解析。',
    system: 'testmate',
  },
  'pingcode:read': {
    label: '读取 PingCode',
    description: '查看 PingCode 项目、缺陷/需求、用例、测试计划与执行报告、评论和附件，并可下载附件。',
    system: 'pingcode',
  },
  'pingcode:write': {
    label: '写入 PingCode',
    description: '以你的名义在 PingCode 中创建缺陷/需求并发表评论。',
    system: 'pingcode',
  },
  'plm:read': {
    label: '读取 PLM',
    description: '查看 PLM 项目、问题单、评论和附件、用例库，并可下载附件。',
    system: 'plm',
  },
  'plm:write': {
    label: '写入 PLM',
    description: '以你的名义在 PLM 中创建问题单并发表评论。',
    system: 'plm',
  },
};

export function scopeMeta(scope: McpScope): ScopeMeta {
  return (
    SCOPE_INFO[scope] ?? { label: scope, description: '', system: 'testmate' }
  );
}

export function systemOfScope(scope: McpScope): ScopeSystem {
  return scopeMeta(scope).system;
}

/** 某个系统支持的全部权限（按 SCOPE_INFO 声明顺序）。 */
export function scopesOfSystem(system: ScopeSystem): McpScope[] {
  return (Object.keys(SCOPE_INFO) as McpScope[]).filter(
    (scope) => SCOPE_INFO[scope].system === system,
  );
}

export interface ScopeGroup {
  system: ScopeSystemMeta;
  scopes: McpScope[];
}

/** 按系统分组；只返回含权限的系统，保持 SCOPE_SYSTEMS 的顺序。 */
export function groupScopes(scopes: McpScope[]): ScopeGroup[] {
  return SCOPE_SYSTEMS.map((system) => ({
    system,
    scopes: scopes.filter((scope) => systemOfScope(scope) === system.code),
  })).filter((group) => group.scopes.length > 0);
}
