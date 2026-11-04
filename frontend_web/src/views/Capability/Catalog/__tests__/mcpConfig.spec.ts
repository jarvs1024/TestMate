/**
 * MCP 配置的前端校验 —— 规则跟后端 `app/core/mcp_config.py` **必须一致**.
 *
 * 前端只是提前提示 (别让用户填完一整张表单才被 422 拦下),
 * 真正的拦截在后端 —— 两边规则不一样就会出现"前端说行、后端说不行".
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { marketRules } from '../assetForm';
import { formatMcpConfig, parseMcpConfig } from '../mcpConfig';

beforeEach(() => {
  marketRules.value = {
    code: {
      pattern: '^(?=.{3,64}$)[a-z0-9]+(?:-[a-z0-9]+)*$',
      example: 'ssd-log-doctor', min_length: 3, max_length: 64,
    },
    segment: {
      pattern: '^(?=.{3,64}$)[a-z0-9]+(?:-[a-z0-9]+)*$', min_length: 3, max_length: 64,
    },
  } as any;
});

describe('MCP 配置解析', () => {
  it('进程型配置合法', () => {
    const r = parseMcpConfig('{"mcpServers": {"dml-demo": {"command": "npx", "args": ["-y", "dml-demo"]}}}');
    expect(r.ok).toBe(true);
  });

  it('远程型配置合法', () => {
    const r = parseMcpConfig('{"mcpServers": {"dml-demo": {"url": "http://h:5050/mcp"}}}');
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
    const r = parseMcpConfig('{"mcpServers": {"dml-demo": {"args": ["x"]}}}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('缺启动方式');
  });

  it('url 协议不对报错', () => {
    const r = parseMcpConfig('{"mcpServers": {"dml-demo": {"url": "ftp://h/mcp"}}}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('http://');
  });

  it('args 必须是数组', () => {
    const r = parseMcpConfig('{"mcpServers": {"dml-demo": {"command": "npx", "args": "x"}}}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('args');
  });

  it('env 必须是对象', () => {
    const r = parseMcpConfig('{"mcpServers": {"dml-demo": {"command": "npx", "env": ["A=1"]}}}');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('env');
  });

  it('格式化: 合法就格式化, 不合法原样返回', () => {
    const ok = formatMcpConfig('{"mcpServers":{"dml-demo":{"url":"http://h/mcp"}}}');
    expect(ok).toContain('\n  "mcpServers"');
    const bad = formatMcpConfig('{oops');
    expect(bad).toBe('{oops');
  });

  it('连接器名不要求 dml- 前缀', () => {
    const r = parseMcpConfig('{"mcpServers": {"xx-xxx": {"url": "http://h/mcp"}}}');
    expect(r.ok).toBe(true);
  });

  it('命名校验消息使用当前规则的示例', () => {
    marketRules.value = {
      ...marketRules.value!,
      code: {
        pattern: '^[a-z0-9]+$', example: 'demo',
        min_length: 3, max_length: 64,
      },
    };
    const r = parseMcpConfig('{"mcpServers": {"bad_name": {"url": "http://h/mcp"}}}');
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error).toContain('demo');
      expect(r.error).not.toContain('dml-');
    }
  });

  it('存量连接器的老名字照常合法', () => {
    // 存量连接器本来就没前缀 —— 不该被拦
    const r = parseMcpConfig(
      '{"mcpServers": {"review-agent-board": {"url": "http://h/mcp"}}}',
    );
    expect(r.ok).toBe(true);
  });

  it('不要求前缀也要守住字符集', () => {
    const r = parseMcpConfig(
      '{"mcpServers": {"Bad_Name": {"url": "http://h/mcp"}}}',
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain('小写字母');
  });

  it('连接器名只能用小写字母/数字/连字符', () => {
    const r = parseMcpConfig('{"mcpServers": {"dml-Bad_Name": {"url": "http://h/mcp"}}}');
    expect(r.ok).toBe(false);
  });
});
