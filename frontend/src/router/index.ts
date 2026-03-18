import { createRouter, createWebHistory } from 'vue-router'
import { fetchJson } from '../api/client'

type ConfigPayload = Record<string, unknown>

function hasRequiredValue(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    return normalized.length > 0 && normalized !== 'false'
  }
  if (typeof value === 'number') {
    return Number.isFinite(value)
  }
  if (typeof value === 'boolean') {
    return true
  }
  if (Array.isArray(value)) {
    return value.length > 0
  }
  return true
}

function parseSignalSettings(raw: unknown): Record<string, unknown> {
  if (!raw) {
    return {}
  }
  if (typeof raw === 'object') {
    return raw as Record<string, unknown>
  }
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw.replace(/'/g, '"')) as Record<string, unknown>
    } catch {
      return {}
    }
  }
  return {}
}

function isConfigComplete(config: ConfigPayload): boolean {
  const alwaysRequiredKeys = [
    'timezone',
    'signal',
    'exchange',
    'timeframe',
    'key',
    'secret',
    'currency',
    'max_bots',
    'bo',
    'tp'
  ]

  if (alwaysRequiredKeys.some((key) => !hasRequiredValue(config[key]))) {
    return false
  }

  if (!hasRequiredValue(config.history_lookback_time)) {
    return false
  }

  const dcaEnabled = Boolean(config.dca)
  if (dcaEnabled) {
    const dynamicDcaEnabled = Boolean(config.dynamic_dca)
    const dcaRequiredKeys = dynamicDcaEnabled
      ? ['mstc', 'sos']
      : ['so', 'mstc', 'sos', 'ss', 'os']
    if (dcaRequiredKeys.some((key) => !hasRequiredValue(config[key]))) {
      return false
    }
  }

  const signal = String(config.signal ?? '')
  if (signal === 'asap') {
    return hasRequiredValue(config.symbol_list)
  }

  if (signal === 'sym_signals') {
    const settings = parseSignalSettings(config.signal_settings)
    return (
      hasRequiredValue(settings.api_url) &&
      hasRequiredValue(settings.api_key) &&
      hasRequiredValue(settings.api_version)
    )
  }

  if (signal === 'csv_signal') {
    const settings = parseSignalSettings(config.signal_settings)
    return hasRequiredValue(settings.csv_source)
  }

  return true
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'trades',
      component: () => import('../views/TradesView.vue')
    },
    {
      path: '/config',
      name: 'config',
      component: () => import('../views/ConfigView.vue')
    },
  ]
})

router.beforeEach(async (to) => {
  if (to.name === 'config') {
    return true
  }

  try {
    const config = await fetchJson<ConfigPayload>('/config/all')
    if (isConfigComplete(config)) {
      return true
    }
    return { name: 'config', query: { setup: 'required' } }
  } catch {
    return true
  }
})

export default router
