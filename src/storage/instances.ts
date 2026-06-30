import type { ExportPayload, Instance, InstanceType } from '../types';

const STORAGE_KEY = 'ai-platform:instances:v1';

function readRaw(): Instance[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as Instance[]) : [];
  } catch {
    return [];
  }
}

function writeRaw(items: Instance[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

export function listInstances(): Instance[] {
  return readRaw();
}

export function addInstance<T extends Instance>(item: T): T {
  const items = readRaw();
  items.push(item);
  writeRaw(items);
  return item;
}

export function updateInstance(id: string, patch: Partial<Instance>): Instance | null {
  const items = readRaw();
  const idx = items.findIndex((i) => i.id === id);
  if (idx === -1) return null;
  const updated: Instance = {
    ...items[idx],
    ...patch,
    id: items[idx].id,
    type: items[idx].type,
    updatedAt: new Date().toISOString()
  } as Instance;
  items[idx] = updated;
  writeRaw(items);
  return updated;
}

export function removeInstance(id: string): boolean {
  const items = readRaw();
  const next = items.filter((i) => i.id !== id);
  if (next.length === items.length) return false;
  writeRaw(next);
  return true;
}

export function exportToJSON(): string {
  const payload: ExportPayload = {
    version: 1,
    exportedAt: new Date().toISOString(),
    instances: readRaw()
  };
  return JSON.stringify(payload, null, 2);
}

function isInstance(value: unknown): value is Instance {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  if (typeof v.id !== 'string' || typeof v.name !== 'string' || typeof v.url !== 'string') return false;
  if (v.type !== 'ragflow' && v.type !== 'dify') return false;
  if (typeof v.createdAt !== 'string' || typeof v.updatedAt !== 'string') return false;
  if (v.type === 'ragflow' && v.authToken !== undefined && typeof v.authToken !== 'string') return false;
  if (v.type === 'dify' && v.apiKey !== undefined && typeof v.apiKey !== 'string') return false;
  return true;
}

export function importFromJSON(json: string): { added: number; skipped: number } {
  const data = JSON.parse(json) as ExportPayload;
  if (!data || data.version !== 1 || !Array.isArray(data.instances)) {
    throw new Error('配置格式不匹配,需要 version: 1');
  }
  const incoming = data.instances.filter(isInstance);
  const existing = readRaw();
  const existingIds = new Set(existing.map((i) => i.id));
  const merged = [...existing];
  let added = 0;
  let skipped = 0;
  for (const item of incoming) {
    if (existingIds.has(item.id)) {
      skipped++;
      console.warn(`[import] 跳过重复 id: ${item.id}`);
    } else {
      merged.push(item);
      existingIds.add(item.id);
      added++;
    }
  }
  writeRaw(merged);
  return { added, skipped };
}

export function instancesByType(type: InstanceType): Instance[] {
  return readRaw().filter((i) => i.type === type);
}
