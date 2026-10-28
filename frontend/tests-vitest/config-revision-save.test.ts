import { computed, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useConfigSaveFlow } from '../src/composables/useConfigSaveFlow'

const post = vi.hoisted(() => vi.fn())
vi.mock('axios', () => ({ default: { post, isAxiosError: (error: any) => !!error?.isAxiosError } }))

describe('configuration revision saves', () => {
  it('sends the loaded revision and retains the server revision after saving', async () => {
    post.mockResolvedValueOnce({ status: 201, data: { config_revision: 5 } })
    const revision = ref<number | null>(4)
    const baseline = vi.fn()
    const flow = useConfigSaveFlow({
      apiUrl: path => path, buildPayload: () => ({ timezone: { value: 'UTC', type: 'str' } }),
      changedSectionLabels: computed(() => ['General']), changedSections: computed(() => ['general']),
      isDirty: computed(() => true), isLoading: ref(false), configRevision: revision,
      message: { error: vi.fn(), info: vi.fn(), success: vi.fn() }, syncBaselineState: baseline,
    })
    expect((await flow.submitForm()).status).toBe('success')
    expect(post).toHaveBeenCalledWith('/config/multiple', expect.any(Object), {
      headers: { 'X-Moonwalker-Config-Revision': '4' },
    })
    expect(revision.value).toBe(5)
    expect(baseline).toHaveBeenCalledOnce()
  })

  it('keeps the draft when its revision is unavailable', async () => {
    post.mockClear()
    const baseline = vi.fn()
    const flow = useConfigSaveFlow({
      apiUrl: path => path, buildPayload: () => ({}),
      changedSectionLabels: computed(() => []), changedSections: computed(() => []),
      isDirty: computed(() => true), isLoading: ref(false), configRevision: ref(null),
      message: { error: vi.fn(), info: vi.fn(), success: vi.fn() }, syncBaselineState: baseline,
    })
    expect((await flow.submitForm()).status).toBe('blocked')
    expect(post).not.toHaveBeenCalled()
    expect(baseline).not.toHaveBeenCalled()
  })

  it('keeps an edited draft when another client has saved first', async () => {
    post.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 409, data: { message: 'Configuration changed since this form was loaded.' } },
    })
    const baseline = vi.fn()
    const revision = ref<number | null>(4)
    const flow = useConfigSaveFlow({
      apiUrl: path => path, buildPayload: () => ({}),
      changedSectionLabels: computed(() => ['General']), changedSections: computed(() => ['general']),
      isDirty: computed(() => true), isLoading: ref(false), configRevision: revision,
      message: { error: vi.fn(), info: vi.fn(), success: vi.fn() }, syncBaselineState: baseline,
    })
    const result = await flow.submitForm()
    expect(result.status).toBe('blocked')
    expect(result.message).toContain('Configuration changed')
    expect(revision.value).toBe(4)
    expect(baseline).not.toHaveBeenCalled()
  })
})
