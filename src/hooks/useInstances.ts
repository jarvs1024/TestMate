import { useCallback, useEffect, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import {
  addInstance as addToStorage,
  exportToJSON,
  importFromJSON,
  listInstances,
  removeInstance as removeFromStorage,
  updateInstance as updateInStorage
} from '../storage/instances';
import type { Instance, InstanceType } from '../types';

export function useInstances() {
  const [instances, setInstances] = useState<Instance[]>(() => listInstances());

  const refresh = useCallback(() => {
    setInstances(listInstances());
  }, []);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'ai-platform:instances:v1') refresh();
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [refresh]);

  const add = useCallback(
    (type: InstanceType, payload: Omit<Instance, 'id' | 'type' | 'createdAt' | 'updatedAt'>) => {
      const now = new Date().toISOString();
      const base = { id: uuidv4(), createdAt: now, updatedAt: now, ...payload };
      const item = { ...base, type } as Instance;
      addToStorage(item);
      refresh();
      return item;
    },
    [refresh]
  );

  const update = useCallback(
    (id: string, patch: Partial<Instance>) => {
      const result = updateInStorage(id, patch);
      refresh();
      return result;
    },
    [refresh]
  );

  const remove = useCallback(
    (id: string) => {
      const ok = removeFromStorage(id);
      refresh();
      return ok;
    },
    [refresh]
  );

  const exportConfig = useCallback(() => exportToJSON(), []);

  const importConfig = useCallback(
    (json: string) => {
      const result = importFromJSON(json);
      refresh();
      return result;
    },
    [refresh]
  );

  return { instances, add, update, remove, exportConfig, importConfig, refresh };
}
