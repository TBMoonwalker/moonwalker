import { MOONWALKER_API_HOST, MOONWALKER_API_PORT } from '../config'

const baseUrl = `http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}`

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, init)
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
