// General Font
import 'vfonts/Lato.css'
// Monospace Font
import 'vfonts/FiraCode.css'

import axios from 'axios'
import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import {
  MOONWALKER_CLIENT_HEADER,
  MOONWALKER_CLIENT_HEADER_VALUE,
} from './api/client'
import './assets/main.css'
import router from './router'
import { initUiTelemetry } from './utils/uiTelemetry'

const app = createApp(App)
const pinia = createPinia()

initUiTelemetry()
axios.defaults.headers.common[MOONWALKER_CLIENT_HEADER] =
  MOONWALKER_CLIENT_HEADER_VALUE

app.use(pinia)
app.use(router)

app.mount('#app')
