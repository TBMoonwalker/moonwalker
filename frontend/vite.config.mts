import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'

const lowMemoryBuild = process.env.MOONWALKER_LOW_MEMORY_BUILD === '1'

// https://vitejs.dev/config/
export default defineConfig({
  server: {
    // Keep SPA view paths local while forwarding dashboard data to the backend.
    proxy: {
      '^/(analytics|autopilot|config|data|orders|statistic|strategies|trades)(/|$)': 'http://127.0.0.1:8130',
      '^/backtest/': 'http://127.0.0.1:8130',
      '^/control-center/[^/]+/': 'http://127.0.0.1:8130',
      '^/monitoring/': 'http://127.0.0.1:8130',
      '/ws': { target: 'ws://127.0.0.1:8130', ws: true },
    },
  },
  plugins: [
    vue(),
    Components({
      dts: false,
      resolvers: [NaiveUiResolver()],
    }),
  ],
  build: {
    ...(lowMemoryBuild ? { minify: false } : {}),
    cssCodeSplit: !lowMemoryBuild,
    chunkSizeWarningLimit: 600,
    // Automatic splitting keeps route-only dependencies out of startup.
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
})
