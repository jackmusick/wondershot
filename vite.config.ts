import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    // flatpak-builder writes build-flatpak/ + .flatpak-builder/ into the repo;
    // they contain symlink loops (udev watch dirs) that crash chokidar. Never watch them.
    watch: { ignored: ['**/build-flatpak/**', '**/.flatpak-builder/**', '**/fp-build/**', '**/fp-repo/**'] }
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.{js,ts}']
  }
});
