/**
 * 资产市场 —— **「编辑信息」** (2026-10-30 · 第十一轮 · 问题6).
 *
 * 用户报的问题: "插件技能连接器支持编辑相关信息（同样是作者和管理才能编辑）".
 *
 * ✅ 做的是一条**新路**: `PATCH /assets/{code}` —— 只改元信息, 不碰安装包,
 *    也不动版本号. 跟原来的「发布新版本」(PUT, 必须重传包) 分开.
 *
 * ⚠️ 最要紧的一条是**后端**: 走错分支会把别人上传的安装包删掉
 *    (见 backend_gateway/app/api/marketplace.py 的 `_stage_asset_locked`).
 *    这里盯的是前端这一半: 编辑模式**不能出现安装包上传区**, 提交走 PATCH.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const read = (p: string) => readFileSync(path.resolve(process.cwd(), p), 'utf-8');
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '');

const dialogRaw = read('src/views/Capability/Catalog/AssetUploadDialog.vue');
const dialog = strip(dialogRaw);
const dialogTpl = dialogRaw.split('<script setup')[0];

const detailRaw = read('src/views/Capability/Catalog/AssetDetailDrawer.vue');
const detailTpl = detailRaw.split('<script setup')[0];

const catalogRaw = read('src/views/Capability/Catalog/index.vue');
const catalog = strip(catalogRaw);

describe('资产详情抽屉: 「编辑信息」按钮', () => {
  it('要有一个单独的「编辑信息」按钮 (跟「发布新版本」分开)', () => {
    expect(detailTpl).toContain('编辑信息');
    expect(detailTpl).toContain('发布新版本');
  });

  it('「编辑信息」触发的是 edit-meta (edit = 发布新版本, 两个不能混)', () => {
    expect(detailTpl).toMatch(/emit\('edit-meta', item\)/);
    expect(detailTpl).toMatch(/emit\('edit', item\)/);
  });

  it('只有 canEdit (作者本人 或 管理员) 才显示', () => {
    const m = detailTpl.match(/<el-button[^>]*v-if="canEdit"[^>]*>\s*编辑信息/);
    expect(m, '「编辑信息」按钮没有挂在 canEdit 上').toBeTruthy();
  });

  it('市场页把 edit-meta 接到了「只改元信息」那条路', () => {
    expect(catalog).toMatch(/@edit-meta="openEditMeta"/);
    expect(catalog).toMatch(/uploadMode\.value = 'edit'/);
  });
});

describe('编辑模式: 不出现安装包上传区', () => {
  it('安装包那一段在编辑模式下要隐藏', () => {
    // ⚠️ `v-else-if="mode !== 'edit'"` —— 少了这个, 编辑模式会把上传框摆出来,
    //    用户传了包也不知道传去哪儿 (提交走 PATCH, 不带文件).
    expect(dialogTpl).toMatch(/v-else-if="mode !== 'edit'" class="up-sec"/);
  });

  it('版本号在编辑模式下要隐藏 (改版本 = 发新版本)', () => {
    expect(dialogTpl).toMatch(/v-if="mode !== 'edit'" label="版本 \(semver\)"/);
  });

  it('连接器的 MCP 配置在编辑模式下**仍然要能改** (那是连接器的元信息)', () => {
    // ⚠️ 连接器是配置型资产 —— 它的"包"就是那段 JSON, 必须留着.
    expect(dialogTpl).toMatch(/<section v-if="isMcp" class="up-sec">/);
  });

  it('要有一句说明, 免得用户以为还能改包', () => {
    expect(dialogTpl).toContain('只改');
  });
});

describe('提交: 编辑模式走 PATCH (只改元信息)', () => {
  it('提交时按 mode 分流', () => {
    expect(dialog).toMatch(/if \(props\.mode === 'edit'\)/);
    expect(dialog).toMatch(/await updateAssetMeta\(/);
  });

  it('编辑模式**不能**调用 updateAsset (那是发新版本, 要重传包)', () => {
    const editBlock = dialog.split("if (props.mode === 'edit')")[1] || '';
    const chunk = editBlock.split('return;')[0] || '';
    expect(chunk).not.toContain('updateAsset(');
  });

  it('api 层要有 updateAssetMeta → PATCH /assets/{code}', () => {
    const api = strip(read('src/api/assets.ts'));
    expect(api).toMatch(/export async function updateAssetMeta/);
    expect(api).toMatch(/apiPatch<AssetJob>\(`\/assets\/\$\{encodeURIComponent\(code\)\}`/);
  });

  it('编辑模式不发 version (版本号归「发新版本」管)', () => {
    const api = strip(read('src/api/assets.ts'));
    const metaIface = api.split('export interface AssetMetaForm')[1] || '';
    const body = metaIface.split('}')[0];
    expect(body).not.toContain('version');
    expect(body).not.toContain('package');
  });
});
