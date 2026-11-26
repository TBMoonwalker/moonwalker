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
      '^/(accumulation|analytics|autopilot|config|data|orders|statistic|strategies|trades)(/|$)': 'http://127.0.0.1:8130',
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
    // Keep the self-hosted woff2 files as separate files so unicode-range can
    // gate each subset at the network level (2026-11-25 design review DV-2).
    // Inlining small subsets as data URIs would ship them inside the CSS on
    // every page, even though the dashboard never renders those scripts.
    // Everything else keeps Vite's default 4KB inline threshold.
    assetsInlineLimit(filePath, content) {
      return filePath.endsWith('.woff2') ? false : content.length < 4096
    },
    // Automatic splitting keeps route-only dependencies out of startup.
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
})
