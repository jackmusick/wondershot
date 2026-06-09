import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests-ui',
  use: { baseURL: 'http://localhost:1420', viewport: { width: 1280, height: 800 } },
  webServer: {
    command: 'VITE_MOCK_IPC=1 npm run dev',
    url: 'http://localhost:1420',
    reuseExistingServer: true,
    timeout: 60_000
  }
});
