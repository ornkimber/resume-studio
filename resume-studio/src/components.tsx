import { useEffect, useRef, useState } from 'react';
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror';
import { yaml } from '@codemirror/lang-yaml';
import { StreamLanguage } from '@codemirror/language';
import { toml } from '@codemirror/legacy-modes/mode/toml';
import { EditorView } from '@codemirror/view';
import { EditorState } from '@codemirror/state';
import { MergeView } from '@codemirror/merge';
import { renderAsync } from 'docx-preview';
import { FileText, LoaderCircle } from 'lucide-react';
import type { Format, Issue } from './types';

const editorTheme = EditorView.theme({
  '&': { fontSize: '12.5px', background: '#fff' },
  '.cm-content': { fontFamily: 'Consolas, "SFMono-Regular", monospace', padding: '18px 0' },
  '.cm-line': { padding: '0 18px 0 8px' },
  '.cm-gutters': { background: '#fafaf8', color: '#a0a59e', border: 'none' },
  '.cm-activeLine': { background: '#f4f8f5' },
  '.cm-activeLineGutter': { background: '#eef3ee' },
});
// MergeView owns a shared scroll container; only standalone editors scroll internally.
const sourceEditorTheme = EditorView.theme({
  '&': { height: '100%', minHeight: '0' },
  '.cm-scroller': { overflow: 'auto', minHeight: '0', overscrollBehaviorY: 'contain' },
});
export function SourceEditor({ value, format, onChange, issue }: { value: string; format: Format; onChange: (value: string) => void; issue?: Issue | null }) {
  const editor = useRef<ReactCodeMirrorRef>(null);
  useEffect(() => {
    const view = editor.current?.view;
    if (view && issue?.line) {
      const line = view.state.doc.line(Math.min(issue.line, view.state.doc.lines));
      view.dispatch({ selection: { anchor: line.from }, effects: EditorView.scrollIntoView(line.from, { y: 'center' }) });
      view.focus();
    }
  }, [issue]);
  return <CodeMirror ref={editor} className="source-editor" value={value} height="100%" extensions={[format === 'yaml' ? yaml() : StreamLanguage.define(toml), EditorView.lineWrapping, editorTheme, sourceEditorTheme]} onChange={onChange} basicSetup={{ foldGutter: true, highlightActiveLine: true }} aria-label="Source editor" />;
}
export function SourceDiff({ before, after, format }: { before: string; after: string; format: Format }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current) return;
    const extensions = [EditorView.editable.of(false), EditorState.readOnly.of(true), EditorView.lineWrapping, editorTheme, format === 'yaml' ? yaml() : StreamLanguage.define(toml)];
    const merge = new MergeView({ a: { doc: before, extensions }, b: { doc: after, extensions }, parent: container.current, highlightChanges: true, gutter: true });
    return () => merge.destroy();
  }, [before, after, format]);
  return <div className="source-diff" ref={container} />;
}
export function DocxPreview({ data, busy = false, compact = false }: { data?: string; busy?: boolean; compact?: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const target = container.current;
    if (!target || !data) return;
    let disposed = false;
    setError('');
    // Each render gets a detached container so an old async render cannot replace a newer preview.
    const next = document.createElement('div');
    const bytes = Uint8Array.from(atob(data), character => character.charCodeAt(0));
    renderAsync(bytes, next, undefined, { className: 'resume-docx', inWrapper: true, ignoreLastRenderedPageBreak: false, renderAltChunks: false, renderComments: false, experimental: false }).then(() => {
      // docx-preview's experimental tab measurements do not account for CSS zoom.
      // Our renderer emits one right tab between a role/school and its date.
      // Lay out that known pattern with flex in the preview only.
      next.querySelectorAll('p').forEach(paragraph => {
        const tab = Array.from(paragraph.querySelectorAll('span')).find(span => span.childElementCount === 0 && span.textContent === '\u2003');
        if (!tab) return;
        let run: HTMLElement = tab;
        while (run.parentElement && run.parentElement !== paragraph) run = run.parentElement;
        if (run.parentElement !== paragraph || !run.nextSibling) return;
        const left = document.createElement('span'); left.className = 'preview-date-left';
        const right = document.createElement('span'); right.className = 'preview-date-right';
        while (paragraph.firstChild && paragraph.firstChild !== run) left.appendChild(paragraph.firstChild);
        run.remove();
        while (paragraph.firstChild) right.appendChild(paragraph.firstChild);
        paragraph.classList.add('preview-date-line'); paragraph.append(left, right);
      });
      if (!disposed) target.replaceChildren(next);
    }).catch(e => { if (!disposed) setError(String(e)); });
    return () => { disposed = true; };
  }, [data]);
  return <div className={`preview-canvas ${compact ? 'compact' : ''}`}>
    {busy && <div className="preview-progress"><LoaderCircle className="spin" size={14} /> Updating document…</div>}
    {!data && <div className="empty-preview"><FileText size={40} strokeWidth={1} /><h3>Your document, as you work</h3><p>Generate a preview to see your resume with its saved styles.</p></div>}
    {error && <p role="alert" className="error-message">Preview could not be displayed. DOCX export is still available. {error}</p>}
    <div className="docx-mount" ref={container} />
  </div>;
}
