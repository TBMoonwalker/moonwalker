import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'

const lowMemoryBuild = process.env.MOONWALKER_LOW_MEMORY_BUILD === '1'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    vueJsx(),
  ],
  build: {
    minify: lowMemoryBuild ? false : 'esbuild',
    cssCodeSplit: !lowMemoryBuild,
    rollupOptions: {
      output: {
        manualChunks: lowMemoryBuild
          ? undefined
          : {
              echarts: ['echarts', 'vue-echarts'],
              naive: ['naive-ui'],
              charts: ['lightweight-charts'],
              vue: ['vue', 'vue-router', 'pinia', '@vueuse/core']
            }
      }
    }
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
})
