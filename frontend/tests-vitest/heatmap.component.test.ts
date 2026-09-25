import { mount, type VueWrapper } from '@vue/test-utils'
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import Heatmap from '../src/components/Heatmap.vue'
import { useThemeStore } from '../src/theme/themeStore'

// jsdom provides no matchMedia, which vooks' useOsTheme() reads when the theme
// store is created; stub a controllable one before any mount. Forced schemes are
// OS-independent, so a single "false" (light) stub suffices — auto-follows-OS is
// covered by themeMode.test.ts against the pure resolveScheme().
function installMatchMediaStub(): void {
  const stub = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
   })) as unknown as (query: string) => MediaQueryList

  window.matchMedia = stub
}

// The per-scheme empty-cell wash; mirrors MINIMUM_COLOR_BY_SCHEME in Heatmap.vue.
const MIN_COLOR: Record<'light' | 'dark', string> = {
  light: 'rgba(29, 92, 73, 0.12)',
  dark: 'rgba(36, 95, 78, 0.12)',
}

function rectStyleColors(wrapper: VueWrapper): string[] {
  return wrapper.findAll('.n-heatmap-rect').map((el) => el.attributes('style'))
}

function hasWash(wrapper: VueWrapper, scheme: 'light' | 'dark'): boolean {
  const target = MIN_COLOR[scheme]
  return rectStyleColors(wrapper).some((style) => (style ?? '').includes(target))
}

describe('Heatmap', () => {
  beforeAll(installMatchMediaStub)

  beforeEach(() => {
    document.documentElement.removeAttribute('data-mw-theme')
    setActivePinia(createPinia())
   })

  function mountHeatmap(data: { timestamp: number; value: number }[]): VueWrapper {
    return mount(Heatmap, { props: { data } })
   }

  it('renders a visible empty state when no trades exist', () => {
    const wrapper = mountHeatmap([])

    expect(wrapper.get('.n-empty__description').text()).toBe('No data to display')
    expect(wrapper.find('.heatmap-container').exists()).toBe(false)
   })

  it('renders the calendar surface when trade data exists', () => {
    const wrapper = mountHeatmap([{ timestamp: Date.UTC(2026, 0, 2), value: 3 }])

    expect(wrapper.get('.n-heatmap').exists()).toBe(true)
    expect(wrapper.findAll('.n-heatmap-rect').length).toBeGreaterThan(0)
    expect(wrapper.text()).toContain('less')
    expect(wrapper.text()).toContain('more')
    expect(wrapper.find('.heatmap-empty').exists()).toBe(false)
   })

  it('forces the dark wash on the empty cells when the user selects dark', () => {
    useThemeStore().setMode('dark')

    const wrapper = mountHeatmap([{ timestamp: Date.UTC(2026, 0, 2), value: 3 }])

    expect(wrapper.find('.n-heatmap').exists()).toBe(true)
    expect(hasWash(wrapper, 'dark')).toBe(true)
    expect(hasWash(wrapper, 'light')).toBe(false)
   })

  it('uses the light wash on the empty cells when the user selects light', () => {
    useThemeStore().setMode('light')

    const wrapper = mountHeatmap([{ timestamp: Date.UTC(2026, 0, 2), value: 3 }])

    expect(wrapper.find('.n-heatmap').exists()).toBe(true)
    expect(hasWash(wrapper, 'light')).toBe(true)
    expect(hasWash(wrapper, 'dark')).toBe(false)
   })
})
