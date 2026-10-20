import {defineConfig} from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: 'quality.spec.mjs',
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 20_000,
  reporter: [['list'], ['json', {outputFile: 'test-output/quality-browser.json'}]],
  outputDir: 'test-output/quality-browser',
  use: {baseURL: 'http://127.0.0.1:4179', browserName: 'chromium',
    ...(process.env.CI ? {} : {channel: 'chrome'}), viewport: {width: 1280, height: 900}},
  webServer: {command: 'npm run dev -- --port 4179 --strictPort',
    url: 'http://127.0.0.1:4179', reuseExistingServer: false, timeout: 20_000},
});
