import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import MonitoringLogPanel from '../src/components/MonitoringLogPanel.vue'
import { fetchJson } from '../src/api/client'

vi.mock('../src/api/client', () => ({
  fetchJson: vi.fn(async (url: string) =>
    String(url).endsWith('/monitoring/logs')
      ? { sources: [{ source: 'watcher', label: 'Watcher', available: true }] }
      : {
          source: 'watcher',
          label: 'Watcher',
          available: true,
          lines: [],
          cursor: 0,
          oldest_cursor: 0,
          has_more_before: false,
          rotated: false,
        },
  ),
}))

const POLL_INTERVAL_MS = 2500

// Naive UI scrolls cached cards back into view on activation; jsdom has no
// scrollTo implementation, so the tests install a no-op and restore it after.
const originalScrollTo = window.HTMLElement.prototype.scrollTo

type SetIntervalFn = typeof window.setInterval
type ClearIntervalFn = typeof window.clearInterval

function installTimerHarness() {
  const origSet = window.setInterval
  const origClear = window.clearInterval
  const liveTimers = new Set<unknown>()

  vi.spyOn(window, 'setInterval').mockImplementation(
    ((fn: Parameters<SetIntervalFn>[0], ms?: Parameters<SetIntervalFn>[1]) => {
      const id = origSet(fn, ms)
      if (ms === POLL_INTERVAL_MS) liveTimers.add(id)
      return id
    }) as SetIntervalFn,
  )
  vi.spyOn(window, 'clearInterval').mockImplementation(
    ((id?: Parameters<ClearIntervalFn>[0]) => {
      if (id !== undefined && liveTimers.has(id)) liveTimers.delete(id)
      return origClear(id)
    }) as ClearIntervalFn,
  )

  return { liveTimers }
}

it('stops log polling when the cached view deactivates and restarts on activation', async () => {
  window.HTMLElement.prototype.scrollTo = (() => undefined) as unknown as typeof originalScrollTo
  const { liveTimers } = installTimerHarness()
  const active = ref(true)
  const Blank = defineComponent({ name: 'Blank', template: '<div class="blank" />' })
  const wrapper = mount(
    defineComponent({
      setup() {
        return () =>
          h(
            KeepAlive,
            null,
            { default: () => (active.value ? h(MonitoringLogPanel) : h(Blank)) },
          )
      },
    }),
  )
  await flushPromises()

  // Mount leaves exactly one live polling timer.
  expect(liveTimers.size).toBe(1)

  // Navigating away deactivates the cached view: the poll must stop.
  active.value = false
  await nextTick()
  expect(liveTimers.size).toBe(0)

  // Returning reactivates the view: polling resumes.
  active.value = true
  await nextTick()
  await flushPromises()
  expect(liveTimers.size).toBe(1)

  wrapper.unmount()
  vi.restoreAllMocks()
})

// Value: protects=user-initiated pause survives a KeepAlive de/activation
// round trip (onActivated must not restart the poll while paused);
// fails_when=a regression drops the `!paused` guard and resumes polling
// against the user's explicit pause; why_new=the existing test only covers
// the unpaused activation path; seam=none;
// no_claim=real timer scheduling (setInterval/clearInterval are spied).
it('keeps log polling paused when a paused cached view is reactivated', async () => {
  window.HTMLElement.prototype.scrollTo = (() => undefined) as unknown as typeof originalScrollTo
  const { liveTimers } = installTimerHarness()
  const active = ref(true)
  const Blank = defineComponent({ name: 'Blank', template: '<div class="blank" />' })
  const wrapper = mount(
    defineComponent({
      setup() {
        return () =>
          h(
            KeepAlive,
            null,
            { default: () => (active.value ? h(MonitoringLogPanel) : h(Blank)) },
          )
      },
    }),
  )
  await flushPromises()
  expect(liveTimers.size).toBe(1)

  // The user pauses live polling.
  const pauseSwitch = wrapper.find('div[role="switch"][aria-label="Pause log polling"]')
  expect(pauseSwitch.exists()).toBe(true)
  await pauseSwitch.trigger('click')
  await flushPromises()
  expect(liveTimers.size).toBe(0)

  // A menu round trip deactivates and reactivates the cached view.
  active.value = false
  await nextTick()
  active.value = true
  await nextTick()
  await flushPromises()

  // The pause must survive the round trip: no polling timer restarts.
  expect(liveTimers.size).toBe(0)
  expect(wrapper.text()).toContain('Live polling paused.')

  wrapper.unmount()
  vi.restoreAllMocks()
})

// Value: protects=the mount continuation (onMounted awaits loadSources() and
// then started polling unconditionally) must not start a poll timer on a
// deactivated cached panel once the pending source request settles;
// fails_when=a regression drops the post-await state check and a 2.5s
// interval runs on the deactivated panel (and one on an unmounted one);
// why_new=the existing tests only cover de/activation round trips after the
// mount continuation had already run; seam=none; no_claim=real timer
// scheduling (setInterval/clearInterval are spied; the source request is a
// controlled promise).
it('does not restart polling when the initial source request settles after deactivation', async () => {
  window.HTMLElement.prototype.scrollTo = (() => undefined) as unknown as typeof originalScrollTo
  const { liveTimers } = installTimerHarness()
  let resolveSources!: (value: unknown) => void
  vi.mocked(fetchJson).mockReset()
  vi.mocked(fetchJson).mockImplementation((url: string) =>
    String(url).endsWith('/monitoring/logs')
      ? new Promise(resolve => { resolveSources = resolve })
      : Promise.resolve({ source: 'watcher', label: 'Watcher', available: true, lines: [], cursor: 0, oldest_cursor: 0, has_more_before: false, rotated: false }),
  )
  const active = ref(true)
  const Blank = defineComponent({ name: 'Blank', template: '<div class="blank" />' })
  const wrapper = mount(
    defineComponent({
      setup() {
        return () => h(KeepAlive, null, { default: () => (active.value ? h(MonitoringLogPanel) : h(Blank)) })
      },
    }),
  )
  await flushPromises()
  // Activation at mount starts the poll (existing behavior); the source
  // request is still pending.
  expect(liveTimers.size).toBe(1)

  // Navigate away while the request is in flight.
  active.value = false
  await nextTick()
  expect(liveTimers.size).toBe(0)

  // The request settles on the deactivated panel: the mount continuation
  // must not start a poll timer.
  resolveSources({ sources: [{ source: 'watcher', label: 'Watcher', available: true }] })
  await flushPromises()
  expect(liveTimers.size).toBe(0)

  // Returning still starts the poll exactly once.
  active.value = true
  await nextTick()
  await flushPromises()
  expect(liveTimers.size).toBe(1)

  wrapper.unmount()
  vi.restoreAllMocks()
})

afterEach(() => {
  window.HTMLElement.prototype.scrollTo = originalScrollTo
  vi.restoreAllMocks()
  vi.mocked(fetchJson).mockReset()
})
