import { onScopeDispose, ref } from 'vue'
import { fetchAccumulationStrategies } from '../api/accumulation'
import type { AccumulationStrategy, AccumulationStrategyPage } from '../types/accumulation'

/** Each consumer owns its catalog, cursor and pending request. */
export function useAccumulationStrategies(formatError: (cause: unknown) => string) {
  const versions = ref<AccumulationStrategy[]>([])
  const cursor = ref<number | null>(null)
  const loading = ref(false)
  const error = ref('')
  let disposed = false
  onScopeDispose(() => { disposed = true })

  async function load(more = false): Promise<AccumulationStrategyPage | null> {
    if (disposed || loading.value || (more && cursor.value === null)) return null
    loading.value = true
    error.value = ''
    try {
      const page = await fetchAccumulationStrategies(more ? cursor.value! : 0)
      if (disposed) return null
      const existing = more ? versions.value : []
      const seen = new Set(existing.map(version => version.id))
      versions.value = [...existing, ...page.versions.filter(version => {
        if (seen.has(version.id)) return false
        seen.add(version.id)
        return true
      })]
      cursor.value = page.next_after_id
      return page
    } catch (cause) {
      if (!disposed) error.value = formatError(cause)
      return null
    } finally {
      if (!disposed) loading.value = false
    }
  }

  return { versions, cursor, loading, error, load }
}
