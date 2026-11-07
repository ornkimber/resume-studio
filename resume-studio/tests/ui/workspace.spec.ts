import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
const fixture = (name: string) => readFileSync(new URL('../../fixtures/' + name, import.meta.url), 'utf8');
const initialWorkspace = () => ({ activeId: 'english', documents: [
  { id: 'english', title: 'English resume', language: 'en', resume: fixture('resume_en.yaml'), style: fixture('style_config.yaml'), resumeFormat: 'yaml', styleFormat: 'yaml' },
  { id: 'chinese', title: '中文简历', language: 'zh', resume: fixture('resume_zh.yaml'), style: fixture('style_config.yaml'), resumeFormat: 'yaml', styleFormat: 'yaml' },
], revisions: [] });

test.beforeEach(async ({ request }) => { await request.post('/api/workspace', { data: initialWorkspace() }); });
test('edit, preview, save, compare, restore, convert, export and reload', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Preview up to date', { exact: true })).toBeVisible();
  await expect(page.locator('.docx-mount')).toContainText('John Doe');
  const role = await page.locator('.preview-date-left').first().boundingBox();
  const dates = await page.locator('.preview-date-right').first().boundingBox();
  expect(Math.abs(role!.y - dates!.y)).toBeLessThan(3);
  expect(dates!.x).toBeGreaterThan(role!.x + role!.width);
  await page.getByLabel('Version name').fill('First draft');
  await page.getByRole('button', { name: 'Save version', exact: true }).click();
  const editor = page.locator('.source-container .cm-content');
  await editor.click(); await page.keyboard.press('Control+Home');
  await page.keyboard.insertText('# Version comparison check\n');
  await expect(page.getByText('Preview up to date', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /Version history/ }).click();
  await expect(page.locator('.source-diff')).toContainText('Version comparison check');
  await page.getByRole('button', { name: 'Document previews' }).click();
  await expect(page.locator('.compare-previews .docx-mount').first()).toContainText('John Doe');
  await page.getByRole('button', { name: 'Restore earlier version' }).click();
  await expect(editor).not.toContainText('Version comparison check');
  await page.getByLabel('Source format').selectOption('toml');
  await expect(editor).toContainText('[profile]');
  await expect(page.getByText('Preview up to date', { exact: true })).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export DOCX', exact: true }).click();
  expect((await download).suggestedFilename()).toBe('resume_en.docx');
  await expect(page.getByText('Saved on this device', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Source format')).toHaveValue('toml');
  await expect(page.getByText('Preview up to date', { exact: true })).toBeVisible();
  await expect(page.locator('.docx-mount')).toContainText('John Doe');
  await page.screenshot({ path: 'test-results/resume-studio.png', fullPage: true });
});
test('invalid source shows a location and keeps the previous valid preview', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Preview up to date', { exact: true })).toBeVisible();
  await page.locator('.source-container .cm-content').click();
  await page.keyboard.press('Control+Home'); await page.keyboard.insertText('invalid: [\n');
  await expect(page.getByText('Changes need attention', { exact: true })).toBeVisible();
  await expect(page.locator('.issue')).toContainText('resume:');
  await expect(page.getByText('Previous valid preview')).toBeVisible();
  await expect(page.locator('.docx-mount')).toContainText('John Doe');
  await page.getByRole('button', { name: 'Export DOCX', exact: true }).click();
  await expect(page.getByText('Export failed — check the issues below')).toBeVisible();
});
test('Chinese source retains Chinese preview and styles', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /中文简历 Chinese/ }).click();
  await expect(page.getByText('Preview up to date', { exact: true })).toBeVisible();
  await expect(page.locator('.docx-mount')).toContainText('陈大文');
  await page.getByRole('button', { name: 'Style', exact: true }).click();
  await page.getByLabel('Source format').selectOption('toml');
  await expect(page.getByText('Preview up to date', { exact: true })).toBeVisible();
  await page.locator('.source-container .cm-content').click();
  await page.keyboard.press('Control+End');
  await expect(page.locator('.source-container')).toContainText('[language_overrides.zh');
});

for (const width of [1440, 900]) {
  test(`source editor scrolls independently at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1080 });
    await page.goto('/');
    const container = page.locator('.source-container');
    const scroller = container.locator('.cm-scroller');
    await expect(container.locator('.cm-content')).toContainText('profile:');
    expect(await scroller.evaluate(element => element.clientHeight)).toBeLessThanOrEqual(await container.evaluate(element => element.clientHeight));
    expect(await scroller.evaluate(element => element.scrollHeight - element.clientHeight)).toBeGreaterThan(200);
    await container.hover();
    const pageScroll = await page.evaluate(() => window.scrollY);
    await page.mouse.wheel(0, 650);
    await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(100);
    expect(await page.evaluate(() => window.scrollY)).toBe(pageScroll);
    await container.locator('.cm-content').click();
    await page.keyboard.press('Control+End');
    await expect.poll(() => scroller.evaluate(element => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThan(30);
    await page.getByRole('button', { name: 'Style', exact: true }).click();
    await container.locator('.cm-content').click();
    await page.keyboard.press('Control+Home');
    await container.hover();
    await page.mouse.wheel(0, 650);
    await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(100);
    await page.getByLabel('Source format').selectOption('toml');
    await container.locator('.cm-content').click();
    await page.keyboard.press('Control+Home');
    await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeLessThan(30);
    await container.hover();
    await page.mouse.wheel(0, 650);
    await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(100);
  });
}

test('history source comparisons scroll together without moving the page', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Preview up to date', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Save version', exact: true }).click();
  await page.getByRole('button', { name: /Version history/ }).click();
  const comparison = page.locator('.source-diff .cm-mergeView');
  const panes = comparison.locator('.cm-editor');
  await expect(panes).toHaveCount(2);
  await comparison.hover();
  const before = await panes.evaluateAll(elements => elements.map(element => element.getBoundingClientRect().top));
  const pageScroll = await page.evaluate(() => window.scrollY);
  await page.mouse.wheel(0, 650);
  await expect.poll(() => comparison.evaluate(element => element.scrollTop)).toBeGreaterThan(100);
  const after = await panes.evaluateAll(elements => elements.map(element => element.getBoundingClientRect().top));
  expect(before[0] - after[0]).toBeGreaterThan(100);
  expect(before[0] - after[0]).toBeCloseTo(before[1] - after[1]);
  expect(await page.evaluate(() => window.scrollY)).toBe(pageScroll);
});
