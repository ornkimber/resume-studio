import { describe, expect, it } from 'vitest';
import { parse as parseYaml } from 'yaml';
import { parse as parseToml } from 'smol-toml';
import { convertSource, documentKey, initialWorkspace, isWorkspace } from '../src/documents';

describe('source and workspace compatibility', () => {
  it('converts both complete resumes and style settings without changing data', () => {
    for (const document of initialWorkspace().documents) {
      for (const source of [document.resume, document.style]) {
        const toml = convertSource(source, 'yaml', 'toml');
        expect(parseToml(toml)).toEqual(parseYaml(source));
        expect(parseYaml(convertSource(toml, 'toml', 'yaml'))).toEqual(parseYaml(source));
      }
    }
  });
  it('rejects lossy conversions and invalid syntax', () => {
    expect(() => convertSource('key: null', 'yaml', 'toml')).toThrow();
    expect(() => convertSource('key: [', 'yaml', 'toml')).toThrow();
  });
  it('invalidates previews when styles or language change', () => {
    const document = initialWorkspace().documents[0];
    expect(documentKey(document)).not.toBe(documentKey({ ...document, language: 'zh' }));
    expect(documentKey(document)).not.toBe(documentKey({ ...document, style: document.style + '\n# edited' }));
  });
  it('does not silently accept corrupted workspace contents', () => {
    expect(isWorkspace(initialWorkspace())).toBe(true);
    expect(isWorkspace({ ...initialWorkspace(), activeId: 'missing' })).toBe(false);
    expect(isWorkspace({ ...initialWorkspace(), revisions: [{}] })).toBe(false);
  });
});
