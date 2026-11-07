import { parse as parseYaml, stringify as stringifyYaml } from 'yaml';
import { parse as parseToml, stringify as stringifyToml } from 'smol-toml';
import english from '../fixtures/resume_en.yaml?raw';
import chinese from '../fixtures/resume_zh.yaml?raw';
import style from '../fixtures/style_config.yaml?raw';
import type { DocumentState, Format, Workspace } from './types';

export function initialWorkspace(): Workspace {
  return { activeId: 'english', documents: [
    { id: 'english', title: 'English resume', language: 'en', resume: english, style, resumeFormat: 'yaml', styleFormat: 'yaml' },
    { id: 'chinese', title: '中文简历', language: 'zh', resume: chinese, style, resumeFormat: 'yaml', styleFormat: 'yaml' },
  ], revisions: [] };
}
export function convertSource(text: string, from: Format, to: Format): string {
  if (from === to) return text;
  const data = from === 'yaml' ? parseYaml(text) : parseToml(text);
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('The source must contain named fields.');
  const result = to === 'yaml' ? stringifyYaml(data, { lineWidth: 0 }) : stringifyToml(data);
  // Refuse lossy conversions (e.g. null or unsupported TOML value types).
  const roundTrip = to === 'yaml' ? parseYaml(result) : parseToml(result);
  if (canonical(data) !== canonical(roundTrip)) throw new Error('This file contains values that cannot be converted without changes.');
  return result;
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => JSON.stringify(key) + ':' + canonical(item)).join(',') + '}';
  return JSON.stringify(value);
}
export function documentKey(document: DocumentState): string {
  return JSON.stringify([document.resume, document.style, document.language, document.resumeFormat, document.styleFormat]);
}
export function isWorkspace(value: unknown): value is Workspace {
  if (!value || typeof value !== 'object') return false;
  const w = value as Workspace;
  const validDoc = (d: DocumentState) => d && typeof d.id === 'string' && typeof d.title === 'string' && ['en', 'zh'].includes(d.language) && typeof d.resume === 'string' && typeof d.style === 'string' && ['yaml', 'toml'].includes(d.resumeFormat) && ['yaml', 'toml'].includes(d.styleFormat);
  return Array.isArray(w.documents) && w.documents.length > 0 && w.documents.every(validDoc) && w.documents.some(d => d.id === w.activeId) && Array.isArray(w.revisions) && w.revisions.every(r => r && typeof r.id === 'string' && typeof r.label === 'string' && typeof r.createdAt === 'string' && validDoc(r.document));
}
