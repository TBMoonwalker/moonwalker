import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import axios from 'axios'
import AccumulationReplay from '../src/components/AccumulationReplay.vue'
vi.mock('axios', () => ({ default: { post: vi.fn() } }))

describe('isolated historical accumulation comparison', () => {
  it('requires a reviewed strategy and candle data before requesting simulation', async () => {
    const wrapper = mount(AccumulationReplay, { props: { strategies: [] } })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('Select a strategy')
    expect(axios.post).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('does not use your wallet or submit orders')
    await flushPromises()
  })
})
