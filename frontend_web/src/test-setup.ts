/**
 * 测试环境准备 —— 2026-11-05.
 *
 * ⚠️ 为什么需要这个文件:
 *
 *   Node 25 起内置了 Web Storage (实验特性, 默认开着) → `globalThis.localStorage` 存在.
 *   但 vitest 的 jsdom environment **不覆盖已经存在的全局** —— 也就是说
 *   `globalThis.localStorage` 这个名字被 **Node 的实现**占住了, jsdom 那份够不着.
 *
 *   而 Node 那份是残的: 原型上只有 getItem/setItem/removeItem/key,
 *   **没有 clear()** —— 于是测试里一句 `localStorage.clear()` 直接
 *   `TypeError: localStorage.clear is not a function`, 197 条用例一起红.
 *
 *   (Node 那份还是个 Proxy —— 连 `localStorage.getItem` / `localStorage.constructor`
 *    都取不到, 是个半残的实现.)
 *
 * 这里自己实现一份**完整的内存版 Storage**, 把 localStorage / sessionStorage 装上 ——
 * 行为跟真浏览器一致, 而且跟 Node 版本无关 (Node 22 / 25 都一样).
 *
 * ⚠️ 为什么不用 `--no-experimental-webstorage` 解决:
 *   那个 flag 要靠 NODE_OPTIONS 传, 忘了设就又炸 —— 而且 CI / 别的同事机器上
 *   谁也不知道要设它. 写进仓库里才是一劳永逸的.
 *
 * ⚠️ 为什么必须挂到全局 `Storage` 上:
 *   测试里会这么 mock —— `Storage.prototype.getItem = () => { throw ... }`
 *   (见 src/utils/__tests__/clientId.spec.ts).
 *   如果全局 Storage 不是我们这个实现的构造器, 那条 mock 就**打不中**,
 *   「localStorage 不可用时退化成会话级 id」那条用例会假绿.
 */

/** 内存版 Storage —— 完整实现 Web Storage 接口 (含 clear, 浏览器语义) */
class MemoryStorage implements Storage {
  private readonly _map = new Map<string, string>();

  get length(): number {
    return this._map.size;
  }

  key(index: number): string | null {
    const keys = Array.from(this._map.keys());
    return index >= 0 && index < keys.length ? keys[index] : null;
  }

  getItem(key: string): string | null {
    const k = String(key);
    return this._map.has(k) ? this._map.get(k)! : null;
  }

  setItem(key: string, value: string): void {
    this._map.set(String(key), String(value));
  }

  removeItem(key: string): void {
    this._map.delete(String(key));
  }

  clear(): void {
    this._map.clear();
  }
}

/**
 * 装一个 Storage 实例.
 *
 * ⚠️ 用 Proxy 是为了支持**索引访问** (`storage[0]`) —— Web Storage 标准里有,
 *    jsdom 也支持, 补上才跟浏览器一致.
 *
 * ⚠️ Reflect.get 用 target 当 receiver —— 这样 `Storage.prototype.getItem`
 *    被测试 mock 掉之后, 实例调用能真的走那份 mock (而不是绕过).
 */
function createStorage(): Storage {
  const inst = new MemoryStorage();
  return new Proxy(inst, {
    get(target, prop, _receiver) {
      if (typeof prop === 'string' && /^\d+$/.test(prop)) {
        const v = target.key(Number(prop));
        return v === null ? undefined : v;
      }
      const v = Reflect.get(target, prop, target);
      return typeof v === 'function' ? v.bind(target) : v;
    },
  }) as Storage;
}

// 全局 Storage 必须是我们这个实现的构造器 —— 否则测试里的
// `Storage.prototype.getItem = ...` mock 打不中 (见文件头说明)
const g = globalThis as unknown as Record<string, unknown>;
g.Storage = MemoryStorage;

for (const key of ['localStorage', 'sessionStorage'] as const) {
  try {
    // 先删掉原属性 —— jsdom/Node 那份可能是 getter, 不先删可能定义不上去
    delete g[key];
  } catch {
    /* 删不掉就硬覆盖, 下面的 defineProperty 会给出真正的错误 */
  }
  Object.defineProperty(globalThis, key, {
    value: createStorage(),
    configurable: true,
    writable: true,
  });
}
