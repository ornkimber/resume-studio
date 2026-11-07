// Start the release app with WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS set to
// --remote-debugging-port=9227, then run this script. No network or server is used.
import { chromium } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
const root = new URL('../', import.meta.url);
const browser = await chromium.connectOverCDP('http://127.0.0.1:9227');
const page = browser.contexts()[0].pages()[0];
await page.waitForSelector('.source-container', { timeout: 30_000 });
await page.getByRole('button', { name: /English resume English/ }).click();
await page.getByText('Preview up to date', { exact: true }).waitFor({ timeout: 60_000 });
await page.locator('.docx-mount').getByText('John Doe', { exact: true }).first().waitFor();
const source = page.locator('.source-container');
const scroller = source.locator('.cm-scroller');
const sourceHeight = await source.evaluate(element => element.clientHeight);
const editorHeight = await scroller.evaluate(element => element.clientHeight);
if (editorHeight > sourceHeight) throw new Error('Native source editor exceeds its panel height.');
await source.hover();
const pageScroll = await page.evaluate(() => window.scrollY);
await page.mouse.wheel(0, 650);
await page.waitForFunction(() => document.querySelector('.source-container .cm-scroller').scrollTop > 100);
if (await page.evaluate(() => window.scrollY) !== pageScroll) throw new Error('Source wheel scrolling moved the outer page.');
await source.locator('.cm-content').click();
await page.keyboard.press('Control+End');
await page.waitForFunction(() => { const scroller = document.querySelector('.source-container .cm-scroller'); return scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop < 30; });
await page.keyboard.press('Control+Home');
const role = await page.locator('.preview-date-left').first().boundingBox();
const date = await page.locator('.preview-date-right').first().boundingBox();
if (!role || !date || Math.abs(role.y - date.y) > 3 || date.x <= role.x + role.width) throw new Error('Native preview date alignment failed.');
const request = {
  action: 'generate', language: 'zh', resumeFormat: 'yaml', styleFormat: 'yaml',
  resume: readFileSync(new URL('fixtures/resume_zh.yaml', root), 'utf8'),
  style: readFileSync(new URL('fixtures/style_config.yaml', root), 'utf8'),
};
const outcome = await page.evaluate(async ({ request, path }) => {
  const invoke = window.__TAURI_INTERNALS__.invoke;
  const result = await invoke('run_engine', { request });
  if (!result.ok || !result.docx) throw new Error(JSON.stringify(result));
  await invoke('write_export', { path, content: result.docx, binary: true });
  const invalid = await invoke('run_engine', { request: { ...request, resume: 'profile: [' } });
  if (invalid.ok || !invalid.errors[0].line) throw new Error('Native error propagation failed.');
  const saved = await invoke('load_workspace');
  if (!saved || saved.documents.length !== 2) throw new Error('Native workspace persistence failed.');
  return { generation: result.ok, name: result.name, errorLocation: invalid.errors[0].line, documents: saved.documents.length };
}, { request, path: resolve('tests/native-export.docx') });
await page.screenshot({ path: 'test-results/native-desktop.png', fullPage: true });
console.log(JSON.stringify({ ...outcome, sourceScrolling: true }));
await browser.close();
