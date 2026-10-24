/**
 * MCP 配置的前端校验 —— 规则跟后端 `app/core/mcp_config.py` **保持一致**.
 *
 * 前端只是**提前提示** (别让用户填完一整张表单才被 422 拦下),
 * 真正的拦截在后端 —— 两边规则要一样, 不然会出现"前端说行、后端说不行".
 */
import { CODE_PATTERN } from './assetForm';
export interface McpParseOk {
  ok: true;
  config: Record<string, any>;
}
export interface McpParseErr {
  ok: false;
  error: string;
}
export type McpParseResult = McpParseOk | McpParseErr;

/** 校验一段 MCP 配置文本, 返回结构化的结果 (不抛异常) */
export function parseMcpConfig(text: string): McpParseResult {
  const raw = (text || '').trim();
  if (!raw) return { ok: false, error: '连接器必须提供 MCP 配置 (mcpServers)' };

  let cfg: any;
  try {
    cfg = JSON.parse(raw);
  } catch (e: any) {
    const msg = e?.message || String(e);
    const pos = /position (\d+)/i.exec(msg);
    if (pos) {
      const at = Number(pos[1]);
      const line = raw.slice(0, at).split('\n').length;
      return { ok: false, error: `JSON 格式错误 (第 ${line} 行): ${msg.split(' in JSON')[0]}` };
    }
    return { ok: false, error: `JSON 格式错误: ${msg.split(' in JSON')[0]}` };
  }

  if (!cfg || typeof cfg !== 'object' || Array.isArray(cfg)) {
    return { ok: false, error: 'MCP 配置必须是一个 JSON 对象' };
  }
  const servers = cfg.mcpServers;
  if (servers === undefined) {
    return { ok: false, error: '缺少 mcpServers —— 配置形如 {"mcpServers": {"名字": {...}}}' };
  }
  if (typeof servers !== 'object' || Array.isArray(servers)) {
    return { ok: false, error: 'mcpServers 必须是一个对象' };
  }
  const names = Object.keys(servers);
  if (!names.length) {
    return { ok: false, error: 'mcpServers 里至少要有一个连接器' };
  }
  for (const name of names) {
    const spec = servers[name];
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) {
      return { ok: false, error: `连接器「${name}」的配置必须是一个对象` };
    }
    // ⚠️ 连接器名 = 资产 code 的约定: dml- 开头 + 小写字母/数字/连字符.
    //    详情页会**原样展示**这份配置, 用户照着加进自己的 MCP 配置里 ——
    //    名字起得像 "xx-xxx" 会跟市场里的资产对不上, 也分不清是谁。
    if (!CODE_PATTERN.test(name)) {
      return {
        ok: false,
        error: `连接器「${name}」的名字必须以 dml- 开头, 且只能用小写字母/数字/连字符 (如 dml-my-connector)`,
      };
    }
    const { command, url, args } = spec as Record<string, any>;
    if (!command && !url) {
      return {
        ok: false,
        error: `连接器「${name}」缺启动方式: 要么给 command (进程型), 要么给 url (远程型)`,
      };
    }
    if (command !== undefined && typeof command !== 'string') {
      return { ok: false, error: `连接器「${name}」的 command 必须是字符串` };
    }
    if (url !== undefined) {
      if (typeof url !== 'string') {
        return { ok: false, error: `连接器「${name}」的 url 必须是字符串` };
      }
      if (!url.startsWith('http://') && !url.startsWith('https://')) {
        return { ok: false, error: `连接器「${name}」的 url 必须以 http:// 或 https:// 开头` };
      }
    }
    if (args !== undefined && !Array.isArray(args)) {
      return { ok: false, error: `连接器「${name}」的 args 必须是数组` };
    }
    for (const opt of ['env', 'headers']) {
      const v = (spec as Record<string, any>)[opt];
      if (v !== undefined && (typeof v !== 'object' || v === null || Array.isArray(v))) {
        return { ok: false, error: `连接器「${name}」的 ${opt} 必须是一个对象` };
      }
    }
  }
  return { ok: true, config: cfg };
}

/** 格式化 (能解析就格式化, 解析不了就原样返回) */
export function formatMcpConfig(text: string): string {
  const r = parseMcpConfig(text);
  if (!r.ok) return text;
  return JSON.stringify(r.config, null, 2);
}

/** 新建连接器的配置模板 —— 照着改比从零想快 */
export const MCP_TEMPLATE = `{
  "mcpServers": {
    "dml-xxx": {
      "url": "http://host.docker.internal:5050/mcp"
    }
  }
}`;
