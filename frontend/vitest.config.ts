import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [
    vue(),
    Components({
      dts: false,
      resolvers: [NaiveUiResolver()],
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['tests-vitest/**/*.test.ts'],
    setupFiles: ['./tests-vitest/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary'],
      reportsDirectory: './coverage/frontend',
      include: [
        'src/components/Heatmap.vue',
        'src/control-center/blockers.ts',
        'src/control-center/readiness.ts',
        'src/control-center/routerGuard.ts',
        'src/helpers/configForm.ts',
        'src/helpers/heatmap.ts',
        'src/helpers/tradeLifecycle.ts',
      ],
      thresholds: {
        statements: 84,
        branches: 72,
        functions: 89,
        lines: 84,
        'src/control-center/readiness.ts': {
          statements: 70,
          branches: 60,
          functions: 80,
          lines: 70,
        },
        'src/control-center/routerGuard.ts': {
          statements: 95,
          branches: 80,
          functions: 100,
          lines: 95,
        },
        'src/helpers/configForm.ts': {
          statements: 90,
          branches: 82,
          functions: 100,
          lines: 90,
        },
      },
    },
  },
})
