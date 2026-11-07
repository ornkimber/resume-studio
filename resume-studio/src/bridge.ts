import { invoke, isTauri } from '@tauri-apps/api/core';
import { open, save } from '@tauri-apps/plugin-dialog';
import type { EngineRequest, EngineResult, Workspace } from './types';

export const desktop = isTauri();
export async function engine(request: EngineRequest): Promise<EngineResult> {
  if (desktop) return invoke('run_engine', { request });
  const response = await fetch('/api/engine', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) });
  if (!response.ok) throw new Error('The local Python engine is unavailable. Start the app using npm run dev.');
  return response.json();
}
export async function loadWorkspace(): Promise<unknown> {
  if (desktop) return invoke('load_workspace');
  const response = await fetch('/api/workspace');
  if (!response.ok) throw new Error('Could not load the saved workspace.');
  return response.json();
}
export async function saveWorkspace(workspace: Workspace): Promise<void> {
  if (desktop) return invoke('save_workspace', { workspace });
  const response = await fetch('/api/workspace', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(workspace) });
  if (!response.ok) throw new Error('Could not save the workspace. Your changes are still in this window.');
}
export async function importSource(): Promise<{ text: string; name: string } | null> {
  if (desktop) {
    const path = await open({ multiple: false, filters: [{ name: 'Resume sources', extensions: ['yaml', 'yml', 'toml'] }] });
    if (!path) return null;
    return { text: await invoke('read_source', { path }), name: path.split(/[\\/]/).pop()! };
  }
  return new Promise(resolve => {
    const input = document.createElement('input'); input.type = 'file'; input.accept = '.yaml,.yml,.toml';
    input.onchange = async () => { const file = input.files?.[0]; resolve(file ? { text: await file.text(), name: file.name } : null); };
    input.addEventListener('cancel', () => resolve(null)); input.click();
  });
}
export async function exportFile(name: string, content: string, binary = false): Promise<boolean> {
  if (desktop) {
    const extension = name.split('.').pop()!;
    const path = await save({ defaultPath: name, filters: [{ name: extension.toUpperCase(), extensions: [extension] }] });
    if (!path) return false;
    await invoke('write_export', { path, content, binary });
    return true;
  }
  const data = binary ? Uint8Array.from(atob(content), c => c.charCodeAt(0)) : content;
  const url = URL.createObjectURL(new Blob([data], { type: binary ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' : 'text/plain;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = name; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 3000); return true;
}
