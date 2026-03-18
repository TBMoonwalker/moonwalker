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
    ...(lowMemoryBuild ? { minify: false } : {}),
    cssCodeSplit: !lowMemoryBuild,
    chunkSizeWarningLimit: 600,
    rolldownOptions: {
      output: {
        ...(lowMemoryBuild
          ? {}
          : {
              codeSplitting: {
                groups: [
                  {
                    name(id) {
                      if (!id.includes('/node_modules/')) {
                        return null
                      }

                      if (
                        id.includes('/node_modules/echarts/') ||
                        id.includes('/node_modules/zrender/') ||
                        id.includes('/node_modules/vue-echarts/')
                      ) {
                        if (
                          id.includes('/echarts/charts.js') ||
                          id.includes('/echarts/lib/chart/')
                        ) {
                          return 'vendor-echarts-charts'
                        }
                        if (
                          id.includes('/echarts/components.js') ||
                          id.includes('/echarts/lib/component/')
                        ) {
                          return 'vendor-echarts-components'
                        }
                        if (
                          id.includes('/echarts/renderers.js') ||
                          id.includes('/echarts/lib/renderer/')
                        ) {
                          return 'vendor-echarts-renderers'
                        }
                        if (id.includes('/node_modules/zrender/')) {
                          return 'vendor-echarts-zrender'
                        }
                        if (id.includes('/node_modules/vue-echarts/')) {
                          return 'vendor-echarts-vue'
                        }
                        return 'vendor-echarts-core'
                      }

                      if (id.includes('/node_modules/naive-ui/')) {
                        if (
                          id.includes('/naive-ui/es/config-provider/') ||
                          id.includes('/naive-ui/es/global-style/') ||
                          id.includes('/naive-ui/es/themes/')
                        ) {
                          return 'vendor-naive-core'
                        }

                        if (
                          id.includes('/naive-ui/es/dialog/') ||
                          id.includes('/naive-ui/es/message/') ||
                          id.includes('/naive-ui/es/modal/') ||
                          id.includes('/naive-ui/es/notification/')
                        ) {
                          return 'vendor-naive-feedback'
                        }

                        if (
                          id.includes('/naive-ui/es/form/') ||
                          id.includes('/naive-ui/es/input/') ||
                          id.includes('/naive-ui/es/input-number/') ||
                          id.includes('/naive-ui/es/date-picker/') ||
                          id.includes('/naive-ui/es/slider/') ||
                          id.includes('/naive-ui/es/select/') ||
                          id.includes('/naive-ui/es/switch/') ||
                          id.includes('/naive-ui/es/checkbox/') ||
                          id.includes('/naive-ui/es/radio/')
                        ) {
                          return 'vendor-naive-form'
                        }

                        if (
                          id.includes('/naive-ui/es/data-table/') ||
                          id.includes('/naive-ui/es/button/') ||
                          id.includes('/naive-ui/es/button-group/') ||
                          id.includes('/naive-ui/es/divider/') ||
                          id.includes('/naive-ui/es/icon/') ||
                          id.includes('/naive-ui/es/tooltip/')
                        ) {
                          return 'vendor-naive-trades'
                        }

                        return 'vendor-naive-misc'
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

                      return null
                    },
                  },
                ],
              },
            }),
      }
    }
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
})
