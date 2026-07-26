import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import Heatmap from '../src/components/Heatmap.vue'

describe('Heatmap', () => {
  it('renders a visible empty state when no trades exist', () => {
    const wrapper = mount(Heatmap, {
      props: { data: [] },
    })

    expect(wrapper.get('.n-empty__description').text()).toBe(
      'No data to display',
    )
    expect(wrapper.find('.heatmap-container').exists()).toBe(false)
  })

  it('renders the calendar surface when trade data exists', () => {
    const wrapper = mount(Heatmap, {
      props: {
        data: [{ timestamp: Date.UTC(2026, 0, 2), value: 3 }],
      },
    })

    expect(wrapper.get('.n-heatmap').exists()).toBe(true)
    expect(wrapper.findAll('.n-heatmap-rect').length).toBeGreaterThan(0)
    expect(wrapper.text()).toContain('less')
    expect(wrapper.text()).toContain('more')
    expect(wrapper.find('.heatmap-empty').exists()).toBe(false)
  })
})
