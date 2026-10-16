import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    // Ignore the developer's .env logging flags: tests must never post
    // their logs to a running backend
    env: {
      VITE_DEBUG_MODE: 'false',
      VITE_ENABLE_LOGS: 'false',
      VITE_LOG_TO_FILE: 'false'
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.config.js',
        '**/*.config.ts',
        'dist/',
        '.eslintrc.cjs'
      ],
    },
  },
});