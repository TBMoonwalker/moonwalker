import { MOONWALKER_API_ORIGIN } from '../config'

const baseUrl = MOONWALKER_API_ORIGIN
export const MOONWALKER_CLIENT_HEADER = 'X-Moonwalker-Client'
export const MOONWALKER_CLIENT_HEADER_VALUE = 'dashboard'
export const MOONWALKER_OPERATION_HEADER = 'X-Moonwalker-Operation-Id'

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set(MOONWALKER_CLIENT_HEADER, MOONWALKER_CLIENT_HEADER_VALUE)
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers })
  if (!response.ok) {
    let detail = ''
    try {
      const payload = (await response.json()) as { error?: string }
      detail = payload.error ? ` - ${payload.error}` : ''
    } catch {
      detail = ''
    }
    throw new Error(`Request failed: ${response.status} ${response.statusText}${detail}`)
  }
  return (await response.json()) as T
}
