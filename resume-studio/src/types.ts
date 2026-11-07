export type Format = 'yaml' | 'toml';
export type Language = 'en' | 'zh';
export type DocumentState = { id: string; title: string; language: Language; resume: string; style: string; resumeFormat: Format; styleFormat: Format };
export type Issue = { source: 'resume' | 'style' | 'app'; path: string; message: string; stage: string; line?: number; column?: number };
export type EngineResult = { ok: boolean; errors: Issue[]; docx?: string; log?: string; details?: string; engineVersion?: string; name?: string; sectionCount?: number };
export type EngineRequest = Pick<DocumentState, 'resume' | 'style' | 'language' | 'resumeFormat' | 'styleFormat'> & { action: 'generate' | 'validate' };
export type Revision = { id: string; label: string; createdAt: string; engineVersion: string; document: DocumentState };
export type Workspace = { documents: DocumentState[]; revisions: Revision[]; activeId: string };
