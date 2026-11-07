import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  testDir: './tests/ui', fullyParallel: false, workers: 1, timeout: 45_000,
  use: { baseURL: 'http://127.0.0.1:1420', channel: process.env.CI ? undefined : 'msedge', headless: true, viewport: { width: 1440, height: 1080 }, screenshot: 'only-on-failure' },
  webServer: { command: 'npm run dev', url: 'http://127.0.0.1:1420', reuseExistingServer: false, timeout: 30_000, env: { RESUME_STUDIO_DATA: fileURLToPath(new URL('./.test-data/ui', import.meta.url)) } },
});
