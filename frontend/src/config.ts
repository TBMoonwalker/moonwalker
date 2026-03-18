const DEFAULT_API_ORIGIN = 'http://127.0.0.1:8130'

const resolveApiOrigin = (): string => {
  const envOrigin = import.meta.env.VITE_MOONWALKER_API_ORIGIN?.trim()
  if (envOrigin) {
    return envOrigin
  }

  const envHost = import.meta.env.VITE_MOONWALKER_API_HOST?.trim()
  const envPort = import.meta.env.VITE_MOONWALKER_API_PORT?.trim()
  if (envHost) {
    const protocol =
      typeof window !== 'undefined' ? window.location.protocol : 'http:'
    const portSuffix = envPort ? `:${envPort}` : ''
    return `${protocol}//${envHost}${portSuffix}`
  }

  if (typeof window !== 'undefined' && window.location.origin) {
    return window.location.origin
  }

  return DEFAULT_API_ORIGIN
}

export const MOONWALKER_API_ORIGIN = resolveApiOrigin()

const apiUrl = new URL(MOONWALKER_API_ORIGIN)

export const MOONWALKER_API_HOST = apiUrl.hostname
export const MOONWALKER_API_PORT = apiUrl.port || ''
