/**
 * **钉钉通知消息的内容与开关** (2026-10-30 · 第十一轮 · 问题2/3/4).
 *
 * 用户要求:
 *   ② 「插件技能连接编辑信息就不需要通知到钉钉了」
 *   ③ 「软件库的上架和发布新版本需要通知到钉钉, 钉钉在设置中配置,
 *       上架和发布新版本共有一个配置」
 *   ④ 「完成钉钉推送的通知信息, 上架补充发描述 比如是干嘛的, 发布更新, 补充更新了啥等,
 *       信息要区分是插件技能还是连接还是软件包, 最后附上连接……消息简洁明了, 好看」
 *
 * ⚠️ 后端那部分是**真发**逻辑, 这里只做**源码断言** (前端仓库里没有后端源码).
 *    真发路径由 backend_gateway/tests/test_dingtalk.py 覆盖.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const read = (p: string) => readFileSync(path.resolve(process.cwd(), p), 'utf-8');
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '');

const settingsRaw = read('src/views/Settings/index.vue');
const settings = strip(settingsRaw);
const assetsApi = strip(read('src/api/assets.ts'));

describe('② 资产的「编辑信息」不该通知钉钉', () => {
  it('资产编辑的接口走 PATCH (只改元信息)', () => {
    expect(assetsApi).toMatch(/export async function updateAssetMeta/);
    expect(assetsApi).toMatch(/apiPatch<AssetJob>/);
  });
});

describe('③ 设置页: 通知区要有「预览消息」入口 (不发送)', () => {
  it('预览按钮 + 展示区', () => {
    expect(settingsRaw).toContain('预览消息');
    expect(settingsRaw).toContain('notif-preview');
    expect(settingsRaw).toContain('previewNotifications');
  });

  it('预览区要说清「不会往群里发任何消息」', () => {
    expect(settingsRaw).toMatch(/预览不会往群里发任何消息/);
  });

  it('前端调的是只读的预览接口', () => {
    expect(assetsApi).toMatch(/apiGet<NotifyPreview\[\]>\('\/assets\/notifications\/preview'\)/);
  });
});

describe('③ 设置页: 通知事件的中文映射要含软件库两个', () => {
  it('NOTIFY_EVENTS 里有 software_publish / software_update', () => {
    const m = settings.match(/const NOTIFY_EVENTS[^=]*=\s*\{([\s\S]*?)\n\};/);
    expect(m, '没找到 NOTIFY_EVENTS').toBeTruthy();
    expect(m![1]).toContain('software_publish');
    expect(m![1]).toContain('software_update');
  });

  it('通知区的说明要提到软件库也走这个群', () => {
    expect(settingsRaw).toContain('软件库');
  });
});
