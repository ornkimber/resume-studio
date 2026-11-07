import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { spawn } from 'node:child_process';
import { readFile, mkdir, writeFile, rename, unlink } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Development transport exercises the real Python engine in a browser. Desktop
// builds use Tauri commands; no HTTP server is shipped in the installed app.
const root = fileURLToPath(new URL('.', import.meta.url));
function localEngine(): Plugin {
  return { name: 'resume-local-engine', configureServer(server) {
    server.middlewares.use('/api', async (req, res) => {
      res.setHeader('Content-Type', 'application/json');
      const origin = req.headers.origin;
      if (origin && !['http://127.0.0.1:1420', 'http://localhost:1420'].includes(origin)) { res.statusCode = 403; res.end('{}'); return; }
      const workspacePath = resolve(process.env.RESUME_STUDIO_DATA || resolve(root, '.test-data'), 'workspace.json');
      try {
        if (req.url === '/workspace' && req.method === 'GET') {
          let saved = 'null';
          try { saved = await readFile(workspacePath, 'utf8'); } catch (e) { if ((e as NodeJS.ErrnoException).code !== 'ENOENT') throw e; }
          res.end(saved); return;
        }
        if (req.method !== 'POST' || !['/engine', '/workspace'].includes(req.url || '')) { res.statusCode = 404; res.end('{}'); return; }
        let body = '';
        for await (const chunk of req) { body += chunk; if (body.length > 12_000_000) throw new Error('Request too large.'); }
        JSON.parse(body);
        if (req.url === '/workspace') {
          await mkdir(resolve(workspacePath, '..'), { recursive: true });
          const temp = workspacePath + '.' + crypto.randomUUID() + '.tmp';
          try { await writeFile(temp, body); await rename(temp, workspacePath); }
          finally { await unlink(temp).catch(() => {}); }
          res.end('{}'); return;
        }
        const child = spawn(process.env.RESUME_STUDIO_PYTHON || 'python', [resolve(root, 'python/engine.py')], { windowsHide: true });
        let stdout = '', stderr = '';
        const timeout = setTimeout(() => child.kill(), 60_000);
        child.stdout.on('data', chunk => { stdout += chunk; });
        child.stderr.on('data', chunk => { stderr += chunk; });
        child.once('error', error => { clearTimeout(timeout); res.statusCode = 500; res.end(JSON.stringify({ message: error.message })); });
        child.once('close', () => {
          clearTimeout(timeout); if (res.writableEnded) return;
          try { JSON.parse(stdout); res.end(stdout); }
          catch { res.statusCode = 500; res.end(JSON.stringify({ message: stderr || 'The engine stopped before returning a result.' })); }
        });
        child.stdin.on('error', () => {}); child.stdin.end(body);
      } catch (e) { if (!res.writableEnded) { res.statusCode = 500; res.end(JSON.stringify({ message: String(e) })); } }
    });
  }};
}
export default defineConfig({ plugins: [react(), localEngine()], clearScreen: false, server: { host: '127.0.0.1', port: 1420, strictPort: true }, build: { target: 'es2022' } });
