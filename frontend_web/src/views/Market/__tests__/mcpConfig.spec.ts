/**
 * MCP 配置的前端校验 —— 规则跟后端 `app/core/mcp_config.py` **必须一致**.
 *
 * 前端只是提前提示 (别让用户填完一整张表单才被 422 拦下),
 * 真正的拦截在后端 —— 两边规则不一样就会出现"前端说行、后端说不行".
 */
import { describe, expect, it } from 'vitest';
import { formatMcpConfig, parseMcpConfig } from '../mcpConfig';

describe('MCP 配置解析', () => {
  it('进程型配置合法', () => {
    const r = parseMcpConfig('{"mcpServers": {"demo": {"command": "npx", "args": ["-y", "demo"]}}}');
    expect(r.ok).toBe(true);
  });

  it('远程型配置合法', () => {
    const r = parseMcpConfig('{"mcpServers": {"demo": {"url": "http://h:5050/mcp"}}}');
    expect(r.ok).toBe(true);
  });

  it('空配置报错', () => {
    const r = parseMcpConfig('   ');
    expect(r.ok).toBe(false);
  });

  it('JSON 语法错会指出行号', () => {
    const r = parseMcpConfig('{\n  "mcpServers": {,}\n}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('JSON 格式错误');
  });

  it('缺 mcpServers 报错', () => {
    const r = parseMcpConfig('{"foo": 1}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('mcpServers');
  });

  it('mcpServers 为空报错', () => {
    const r = parseMcpConfig('{"mcpServers": {}}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('至少要有一个');
  });

  it('缺 command/url 报错', () => {
    const r = parseMcpConfig('{"mcpServers": {"demo": {"args": ["x"]}}}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('缺启动方式');
  });

  it('url 协议不对报错', () => {
    const r = parseMcpConfig('{"mcpServers": {"demo": {"url": "ftp://h/mcp"}}}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('http://');
  });

  it('args 必须是数组', () => {
    const r = parseMcpConfig('{"mcpServers": {"demo": {"command": "npx", "args": "x"}}}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('args');
  });

  it('env 必须是对象', () => {
    const r = parseMcpConfig('{"mcpServers": {"demo": {"command": "npx", "env": ["A=1"]}}}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('env');
  });

  it('格式化: 合法就格式化, 不合法原样返回', () => {
    const ok = formatMcpConfig('{"mcpServers":{"demo":{"url":"http://h/mcp"}}}');
    expect(ok).toContain('\n  "mcpServers"');
    const bad = formatMcpConfig('{oops');
    expect(bad).toBe('{oops');
  });
});
