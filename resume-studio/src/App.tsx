import { useEffect, useRef, useState } from 'react';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { ArrowDownToLine, ArrowRight, Check, Clock3, Code2, Download, FileText, FolderOpen, Globe2, History, Layers3, LoaderCircle, Plus, RefreshCw, RotateCcw, Settings2, ShieldCheck, TriangleAlert } from 'lucide-react';
import { desktop, engine, exportFile, importSource, loadWorkspace, saveWorkspace } from './bridge';
import { convertSource, documentKey, initialWorkspace, isWorkspace } from './documents';
import { DocxPreview, SourceDiff, SourceEditor } from './components';
import type { DocumentState, EngineResult, Format, Issue, Revision, Workspace } from './types';

const dateLabel = (date: string) => new Date(date).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
export default function App() {
  const [workspace, setWorkspace] = useState<Workspace>(initialWorkspace);
  const [hydrated, setHydrated] = useState(false);
  const [storageBlocked, setStorageBlocked] = useState(false);
  const [saveStatus, setSaveStatus] = useState('Loading workspace');
  const [tab, setTab] = useState<'resume' | 'style'>('resume');
  const [screen, setScreen] = useState<'editor' | 'history'>('editor');
  const [status, setStatus] = useState('Ready to create');
  const [notice, setNotice] = useState('');
  const [result, setResult] = useState<EngineResult | null>(null);
  const [preview, setPreview] = useState<{ key: string; data: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [autoPreview, setAutoPreview] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [jumpIssue, setJumpIssue] = useState<Issue | null>(null);
  const [revisionLabel, setRevisionLabel] = useState('');
  const [leftId, setLeftId] = useState('');
  const [rightId, setRightId] = useState('working');
  const [comparisonMode, setComparisonMode] = useState<'source' | 'preview'>('source');
  const [comparisonPreview, setComparisonPreview] = useState<{ left?: string; right?: string }>({});
  const [comparisonBusy, setComparisonBusy] = useState(false);
  const [comparisonError, setComparisonError] = useState('');
  const [exporting, setExporting] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const generation = useRef(0);
  const comparisonGeneration = useRef(0);
  const saveQueue = useRef(Promise.resolve());
  const saveRevision = useRef(0);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeState = useRef({ workspace, hydrated, storageBlocked, saveStatus });
  closeState.current = { workspace, hydrated, storageBlocked, saveStatus };
  const current = workspace.documents.find(d => d.id === workspace.activeId)!;
  const key = documentKey(current);
  const revisions = workspace.revisions.filter(r => r.document.id === current.id).slice().reverse();
  const selectedLeft = revisions.find(r => r.id === leftId) || revisions[0];
  const selectedRight = rightId === 'working' ? undefined : revisions.find(r => r.id === rightId);
  const before = selectedLeft?.document;
  const after = selectedRight?.document || current;
  const content = current[tab];
  const format = current[tab === 'resume' ? 'resumeFormat' : 'styleFormat'];
  const previewCurrent = preview?.key === key;

  useEffect(() => {
    const warnUnsaved = (event: BeforeUnloadEvent) => {
      if (closeState.current.saveStatus.startsWith('Saving') || closeState.current.saveStatus.includes('failed')) {
        event.preventDefault(); event.returnValue = '';
      }
    };
    if (!desktop) { window.addEventListener('beforeunload', warnUnsaved); return () => window.removeEventListener('beforeunload', warnUnsaved); }
    let disposed = false;
    let unlisten: (() => void) | undefined;
    const windowHandle = getCurrentWindow();
    windowHandle.onCloseRequested(async event => {
      const latest = closeState.current;
      if (!latest.hydrated || latest.storageBlocked) return;
      event.preventDefault();
      if (saveTimer.current) clearTimeout(saveTimer.current);
      try {
        await saveQueue.current.catch(() => {});
        await saveWorkspace(latest.workspace);
        await windowHandle.destroy();
      } catch (e) { setNotice(`Could not save before closing: ${String(e)}. Export a workspace backup before closing.`); }
    }).then(stop => { if (disposed) stop(); else unlisten = stop; }).catch(e => setNotice(String(e)));
    return () => { disposed = true; unlisten?.(); };
  }, []);

  useEffect(() => {
    loadWorkspace().then(saved => {
      if (saved !== null) {
        if (!isWorkspace(saved)) throw new Error('The saved workspace has an unsupported structure. It has been preserved; automatic saving is disabled.');
        setWorkspace(saved);
      }
      setSaveStatus('Saved on this device');
    }).catch(e => { setNotice(String(e)); setStorageBlocked(true); setSaveStatus('Automatic saving unavailable'); }).finally(() => setHydrated(true));
  }, []);

  useEffect(() => {
    if (!hydrated || storageBlocked) return;
    const revision = ++saveRevision.current;
    setSaveStatus('Saving changes…');
    const timer = setTimeout(() => {
      saveQueue.current = saveQueue.current.catch(() => {}).then(() => saveWorkspace(workspace)).then(() => {
        if (revision === saveRevision.current) setSaveStatus('Saved on this device');
      }).catch(e => { setSaveStatus('Save failed — export a backup'); setNotice(String(e)); });
    }, 300);
    saveTimer.current = timer;
    return () => clearTimeout(timer);
  }, [workspace, hydrated, storageBlocked]);

  useEffect(() => {
    const token = ++generation.current;
    if (!hydrated) return;
    setResult(null); setJumpIssue(null);
    setBusy(true);
    setStatus(autoPreview ? 'Updating preview…' : 'Checking source…');
    const timer = setTimeout(async () => {
      try {
        const response = await engine({ ...current, action: autoPreview ? 'generate' : 'validate' });
        if (token !== generation.current) return;
        setResult(response);
        if (response.docx) setPreview({ key, data: response.docx });
        setStatus(response.ok ? autoPreview ? 'Preview up to date' : 'Source is valid' : 'Changes need attention');
      } catch (e) {
        if (token !== generation.current) return;
        setResult({ ok: false, errors: [{ source: 'app', path: '', stage: 'connection', message: String(e) }] });
        setStatus('Engine unavailable');
      } finally { if (token === generation.current) setBusy(false); }
    }, 800);
    return () => { clearTimeout(timer); generation.current++; };
  }, [key, hydrated, refresh, autoPreview]);

  useEffect(() => {
    setLeftId(''); setRightId('working'); setComparisonMode('source'); setPreview(null); setRevisionLabel('');
  }, [current.id]);

  useEffect(() => {
    const token = ++comparisonGeneration.current;
    setComparisonPreview({}); setComparisonError('');
    if (screen !== 'history' || comparisonMode !== 'preview' || !before) { setComparisonBusy(false); return; }
    setComparisonBusy(true);
    Promise.all([engine({ ...before, action: 'generate' }), engine({ ...after, action: 'generate' })]).then(([left, right]) => {
      if (token !== comparisonGeneration.current) return;
      setComparisonPreview({ left: left.docx, right: right.docx });
      if (!left.ok || !right.ok) setComparisonError([...left.errors, ...right.errors].map(e => `${e.path}: ${e.message}`).join(' · '));
    }).catch(e => { if (token === comparisonGeneration.current) setComparisonError(String(e)); }).finally(() => { if (token === comparisonGeneration.current) setComparisonBusy(false); });
    return () => { comparisonGeneration.current++; };
  }, [screen, comparisonMode, selectedLeft?.id, selectedRight?.id, key]);

  function update(patch: Partial<DocumentState>) {
    setWorkspace(w => ({ ...w, documents: w.documents.map(d => d.id === w.activeId ? { ...d, ...patch } : d) }));
  }
  function snapshot(document = current, label = revisionLabel.trim() || `Revision ${revisions.length + 1}`): Revision {
    return { id: crypto.randomUUID(), label, createdAt: new Date().toISOString(), engineVersion: '0.1.0', document: { ...document } };
  }
  function saveRevisionNow() {
    const revision = snapshot();
    setWorkspace(w => ({ ...w, revisions: [...w.revisions, revision] }));
    setRevisionLabel(''); setNotice(`Saved “${revision.label}” with its style settings.`);
  }
  async function convert(to: Format) {
    if (to === format) return;
    try {
      const text = convertSource(content, format, to);
      const revision = snapshot(current, `Before ${tab} conversion to ${to.toUpperCase()}`);
      setWorkspace(w => ({ ...w, revisions: [...w.revisions, revision], documents: w.documents.map(d => d.id === current.id ? { ...d, [tab]: text, [tab === 'resume' ? 'resumeFormat' : 'styleFormat']: to } : d) }));
      setNotice(`Converted to ${to.toUpperCase()}. Comments are omitted in the converted copy; the original is saved in history.`);
    } catch (e) { setNotice(`Conversion failed: ${String(e)}`); }
  }
  async function importFile() {
    try {
      const file = await importSource(); if (!file) return;
      const format: Format = /\.toml$/i.test(file.name) ? 'toml' : 'yaml';
      const revision = snapshot(current, `Before importing ${file.name}`);
      setWorkspace(w => ({ ...w, revisions: [...w.revisions, revision], documents: w.documents.map(d => d.id === current.id ? { ...d, [tab]: file.text, [tab === 'resume' ? 'resumeFormat' : 'styleFormat']: format } : d) }));
      setNotice(`Imported ${file.name}. The previous draft is saved in history.`);
    } catch (e) { setNotice(String(e)); }
  }
  async function exportDocx(document = current) {
    setExporting(true);
    try {
      const response = document === current && previewCurrent && result?.ok && preview ? { ...result, docx: preview.data } : await engine({ ...document, action: 'generate' });
      if (!response.ok || !response.docx) {
        setResult(response); setStatus('Export failed — check the issues below'); setScreen('editor'); return;
      }
      const filename = `resume_${document.language}.docx`;
      if (await exportFile(filename, response.docx, true)) { setStatus('DOCX exported successfully'); setNotice(`Saved ${filename}. Open it in Word for final layout review and PDF export.`); }
    } catch (e) { setNotice(`Export failed: ${String(e)}`); setStatus('Export failed'); }
    finally { setExporting(false); }
  }
  async function exportBoth() {
    setExporting(true);
    try {
      // Validate/generate every document before showing save dialogs.
      const responses = await Promise.all(workspace.documents.map(d => engine({ ...d, action: 'generate' })));
      const failed = responses.findIndex(r => !r.ok);
      if (failed !== -1) { setNotice(`${workspace.documents[failed].title}: ${responses[failed].errors.map(e => e.message).join(' ')}`); return; }
      for (let i = 0; i < responses.length; i++) {
        const d = workspace.documents[i];
        if (!await exportFile(`resume_${d.language}.docx`, responses[i].docx!, true)) { setNotice('Batch export stopped. Files already saved are available.'); return; }
      }
      setNotice('Both resumes exported successfully.');
    } catch (e) { setNotice(`Batch export failed: ${String(e)}`); }
    finally { setExporting(false); }
  }
  async function exportSource() {
    try { if (await exportFile(tab === 'resume' ? `resume_${current.language}.${format}` : `style_config.${format}`, content)) setNotice('Source file exported.'); }
    catch (e) { setNotice(String(e)); }
  }
  function restore() {
    if (!before) return;
    const recovery = snapshot(current, 'Draft before restore');
    setWorkspace(w => ({ ...w, revisions: [...w.revisions, recovery], documents: w.documents.map(d => d.id === current.id ? { ...before, id: d.id, title: d.title } : d) }));
    setScreen('editor'); setNotice(`Restored “${selectedLeft!.label}”. Your previous draft is saved in history.`);
  }
  async function backup() {
    try { if (await exportFile('resume-studio-backup.json', JSON.stringify(workspace, null, 2))) setNotice('Workspace backup exported.'); }
    catch (e) { setNotice(String(e)); }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><FileText size={22} /></div><div>Resume Studio<span>A LITTLE SPACE FOR YOUR NEXT STEP</span></div></div>
      <div className="workspace-label">YOUR WORKSPACE <span>LOCAL</span></div>
      <nav aria-label="Resume documents" className="document-nav">{workspace.documents.map(document => <button key={document.id} className={`document-button ${document.id === current.id ? 'selected' : ''}`} onClick={() => setWorkspace(w => ({ ...w, activeId: document.id }))}><FileText size={18} /><span>{document.title}<small>{document.language === 'en' ? 'English · en' : 'Chinese · zh'}</small></span>{document.id === current.id && <span className="active-dot" />}</button>)}</nav>
      <div className="sidebar-divider" />
      <nav className="view-nav" aria-label="Workspace views"><button className={screen === 'editor' ? 'active' : ''} onClick={() => setScreen('editor')}><Layers3 size={17} /> Editor <span>01</span></button><button className={screen === 'history' ? 'active' : ''} onClick={() => setScreen('history')}><History size={17} /> Version history <span>{String(revisions.length).padStart(2, '0')}</span></button></nav>
      <div className="sidebar-note"><div className="note-icon"><ShieldCheck size={19} /></div><strong>Your work stays with you.</strong><p>Sources, styles, and saved versions live on this device.</p><button onClick={backup}><Download size={14} /> Export workspace backup</button></div>
      <div className="sidebar-footer"><span className="connection-dot" /> {desktop ? 'Desktop workspace' : 'Local development'}<span>v0.1</span></div>
    </aside>
    <main>
      <header className="topbar"><div className="breadcrumb">Workspace <span>/</span> <strong>{current.title}</strong></div><div className="save-indicator"><span className={`connection-dot ${saveStatus.includes('failed') || storageBlocked ? 'warning' : ''}`} />{saveStatus}</div></header>
      <section className="page-heading"><div><div className="eyebrow">MAKE YOUR NEXT CHAPTER COUNT</div><h1>{screen === 'editor' ? 'A resume, thoughtfully made.' : 'Every draft has a story.'}</h1><p>{screen === 'editor' ? 'Refine your words. Keep your style. See it come together.' : 'Compare what changed, revisit a version, and keep moving forward.'}</p></div><div className="heading-actions"><button className="button secondary" onClick={exportBoth} disabled={exporting || !hydrated}><Layers3 size={15} /> Export both</button><button className="button primary" onClick={() => exportDocx()} disabled={exporting || !hydrated}>{exporting ? <LoaderCircle size={16} className="spin" /> : <ArrowDownToLine size={16} />} Export DOCX</button></div></section>
      {notice && <div className="notice" role="status"><span>{notice}</span><button aria-label="Dismiss notification" onClick={() => setNotice('')}>×</button></div>}
      <div className="workspace-bar"><div className="workspace-tabs"><button className={screen === 'editor' ? 'selected' : ''} onClick={() => setScreen('editor')}><Code2 size={15} /> Compose</button><button className={screen === 'history' ? 'selected' : ''} onClick={() => setScreen('history')}><Clock3 size={15} /> History <span>{revisions.length}</span></button></div><div className="language-select"><Globe2 size={14} /><label htmlFor="language">Language</label><select id="language" value={current.language} onChange={e => update({ language: e.target.value as 'en' | 'zh' })}><option value="en">English</option><option value="zh">中文</option></select></div></div>
      {screen === 'editor' ? <>
        <section className="editor-grid">
          <div className="editor-panel panel"><div className="panel-heading"><div className="source-tabs"><button className={tab === 'resume' ? 'selected' : ''} onClick={() => setTab('resume')}><FileText size={14} /> Resume</button><button className={tab === 'style' ? 'selected' : ''} onClick={() => setTab('style')}><Settings2 size={14} /> Style</button></div><select aria-label="Source format" className="format-select" value={format} onChange={e => convert(e.target.value as Format)}><option value="yaml">YAML</option><option value="toml">TOML</option></select></div><div className="file-toolbar"><span><span className="file-dot" />{tab === 'resume' ? `resume_${current.language}` : 'style_config'}.{format}</span><div><button title="Import source" aria-label="Import source" onClick={importFile}><FolderOpen size={15} /></button><button title="Export source" aria-label="Export source" onClick={exportSource}><Download size={15} /></button></div></div><div className="source-container"><SourceEditor value={content} format={format} onChange={value => update({ [tab]: value })} issue={jumpIssue?.source === tab ? jumpIssue : null} /></div><div className="editor-footer"><span>{content.split('\n').length} lines</span><span>UTF-8 <span className="footer-divider">/</span> {format.toUpperCase()}</span></div></div>
          <div className="preview-panel panel"><div className="panel-heading"><span className="panel-title"><FileText size={15} /> Document preview</span><span className="a4-badge">A4</span></div><div className="preview-toolbar"><label className="auto-preview"><input type="checkbox" checked={autoPreview} onChange={e => setAutoPreview(e.target.checked)} /> Live preview</label><div><span className={previewCurrent ? 'preview-current' : 'preview-stale'}>{previewCurrent ? 'Up to date' : preview ? 'Previous valid preview' : 'Preparing'}</span><button title="Refresh preview" aria-label="Refresh preview" onClick={() => { setAutoPreview(true); setRefresh(r => r + 1); }}><RefreshCw size={14} className={busy ? 'spin' : ''} /></button></div></div><DocxPreview data={preview?.data} busy={busy} /><div className="preview-footer">Preview is approximate. Review page breaks in Word before PDF export.</div></div>
        </section>
        <section className={`generation-status ${result && !result.ok ? 'has-errors' : ''}`} aria-live="polite"><div className="status-main">{busy ? <LoaderCircle className="spin" size={17} /> : result?.ok ? <Check size={18} /> : result ? <TriangleAlert size={18} /> : <Clock3 size={17} />}<div><strong>{status}</strong><span>{result?.ok ? `${result.sectionCount} sections · ${result.name} · Original Word styles` : 'Validation and generation messages appear here.'}</span></div><button onClick={() => setShowDetails(!showDetails)}>{showDetails ? 'Hide details' : 'View details'}</button></div>{result?.errors.map((issue, index) => <button className="issue" key={index} onClick={() => { if (issue.source !== 'app') { setTab(issue.source); setJumpIssue({ ...issue }); } }}><TriangleAlert size={14} /><span><strong>{issue.source}{issue.line ? `:${issue.line}:${issue.column || 1}` : ''} {issue.path}</strong>{issue.message}</span>{issue.line && <ArrowRight size={14} />}</button>)}{showDetails && <pre className="technical-details">{result?.details || result?.log || (result ? JSON.stringify(result.errors, null, 2) : 'No generation details yet.')}</pre>}</section>
        <section className="revision-strip"><div className="revision-icon"><History size={20} /></div><div><strong>A version worth keeping?</strong><p>Save your content and style together, ready to revisit.</p></div><input aria-label="Version name" placeholder="Version name, e.g. Project manager role" value={revisionLabel} onChange={e => setRevisionLabel(e.target.value)} maxLength={120} /><button className="button secondary" onClick={saveRevisionNow} disabled={!hydrated}><Plus size={16} /> Save version</button></section>
      </> : <section className="history-workspace">
        <div className="history-top"><div><h2>Version history <span>{revisions.length}</span></h2><p>Each version includes the resume, style settings, and language.</p></div><button className="button secondary" onClick={saveRevisionNow}><Plus size={15} /> Save current draft</button></div>
        {before ? <><div className="compare-controls"><label>Earlier version<select aria-label="Earlier version" value={selectedLeft?.id || ''} onChange={e => setLeftId(e.target.value)}>{revisions.map(r => <option key={r.id} value={r.id}>{r.label} · {dateLabel(r.createdAt)}</option>)}</select></label><ArrowRight size={18} /><label>Compare with<select aria-label="Compare with" value={rightId} onChange={e => setRightId(e.target.value)}><option value="working">Current working draft</option>{revisions.map(r => <option key={r.id} value={r.id}>{r.label} · {dateLabel(r.createdAt)}</option>)}</select></label><button className="button secondary" onClick={restore}><RotateCcw size={14} /> Restore earlier version</button></div><div className="comparison-toolbar"><div className="source-tabs"><button className={tab === 'resume' ? 'selected' : ''} onClick={() => setTab('resume')}>Resume</button><button className={tab === 'style' ? 'selected' : ''} onClick={() => setTab('style')}>Style</button></div><div className="segmented"><button className={comparisonMode === 'source' ? 'selected' : ''} onClick={() => setComparisonMode('source')}>Source changes</button><button className={comparisonMode === 'preview' ? 'selected' : ''} onClick={() => setComparisonMode('preview')}>Document previews</button></div></div><div className="compare-labels"><span>{selectedLeft?.label} <small>{before.language.toUpperCase()} · {before[tab === 'resume' ? 'resumeFormat' : 'styleFormat'].toUpperCase()}</small></span><span>{selectedRight?.label || 'Current working draft'} <small>{after.language.toUpperCase()} · {after[tab === 'resume' ? 'resumeFormat' : 'styleFormat'].toUpperCase()}</small></span></div>{comparisonMode === 'source' ? <SourceDiff before={before[tab]} after={after[tab]} format={format} /> : <>{comparisonError && <div className="error-message">{comparisonError}</div>}<div className="compare-previews"><DocxPreview data={comparisonPreview.left} busy={comparisonBusy} compact /><DocxPreview data={comparisonPreview.right} busy={comparisonBusy} compact /></div><div className="preview-footer">Both previews use the saved Python renderer. Word determines final pagination.</div></>}</> : <div className="empty-history"><History size={40} strokeWidth={1} /><h3>Your first version starts here.</h3><p>Save a draft to compare changes and return to it later.</p><button className="button primary" onClick={saveRevisionNow}><Plus size={15} /> Save first version</button></div>}
      </section>}
      <footer className="page-footer"><span>Made for your next opportunity.</span><span>Local files. Familiar Word formatting.</span></footer>
    </main>
  </div>;
}
