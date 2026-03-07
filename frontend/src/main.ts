// General Font
import 'vfonts/Lato.css'
// Monospace Font
import 'vfonts/FiraCode.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { initUiTelemetry } from './utils/uiTelemetry'

const app = createApp(App)
const pinia = createPinia()

initUiTelemetry()

app.use(pinia)
app.use(router)

app.mount('#app')
