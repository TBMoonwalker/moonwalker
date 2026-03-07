import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import Components from 'unplugin-vue-components/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'

const lowMemoryBuild = process.env.MOONWALKER_LOW_MEMORY_BUILD === '1'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    vueJsx(),
    Components({
      dts: false,
      resolvers: [NaiveUiResolver()],
    }),
  ],
  build: {
    minify: lowMemoryBuild ? false : 'esbuild',
    cssCodeSplit: !lowMemoryBuild,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: lowMemoryBuild
          ? undefined
          : (id) => {
              if (!id.includes('/node_modules/')) {
                return undefined
              }

              if (
                id.includes('/node_modules/echarts/') ||
                id.includes('/node_modules/zrender/') ||
                id.includes('/node_modules/vue-echarts/')
              ) {
                if (id.includes('/echarts/charts/')) {
                  return 'vendor-echarts-charts'
                }
                if (id.includes('/echarts/components/')) {
                  return 'vendor-echarts-components'
                }
                if (id.includes('/echarts/renderers/')) {
                  return 'vendor-echarts-renderers'
                }
                if (id.includes('/node_modules/zrender/')) {
                  return 'vendor-echarts-zrender'
                }
                return 'vendor-echarts-core'
              }

              if (id.includes('/node_modules/naive-ui/')) {
                return 'vendor-naive'
              }

              if (
                id.includes('/node_modules/vue/') ||
                id.includes('/node_modules/vue-router/') ||
                id.includes('/node_modules/pinia/') ||
                id.includes('/node_modules/@vueuse/core/')
              ) {
                return 'vendor-vue'
              }

              if (id.includes('/node_modules/lightweight-charts/')) {
                return 'vendor-lightweight-charts'
              }

              if (id.includes('/node_modules/@vicons/')) {
                return 'vendor-icons'
              }

              if (id.includes('/node_modules/')) {
                return 'vendor-misc'
              }

              return undefined
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
