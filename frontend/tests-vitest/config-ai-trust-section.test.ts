import { mount } from '@vue/test-utils'
import { NSwitch } from 'naive-ui'
import { describe, expect, it } from 'vitest'

import ConfigAiTrustSection from '../src/components/config/ConfigAiTrustSection.vue'
import type { AiTrustAdvancedModel } from '../src/config-editor/types'

const baseTrust: AiTrustAdvancedModel = {
    ai_trust_enabled: false,
    ai_trust_enforce_warnings: false,
    ai_trust_ollama_base_url: '',
    ai_trust_ollama_model: '',
    ai_trust_timeout_ms: 10_000,
    ai_trust_max_retries: 0,
}

function mountSection(trust: Partial<AiTrustAdvancedModel> = {}, rules: unknown = {}) {
    return mount(ConfigAiTrustSection, {
        props: {
            aiTrust: { ...baseTrust, ...trust },
            rules: rules as never,
          },
     })
}

describe('ConfigAiTrustSection control surface', () => {
    it('renders every AI-trust calibration field with its label', () => {
        const wrapper = mountSection()

        for (const label of [
             'AI Trust Cockpit enabled',
             'Block AI warning entries',
             'Ollama base URL',
             'Ollama model',
             'AI timeout (ms)',
             'AI retry budget',
          ]) {
            expect(wrapper.text()).toContain(label)
         }
        // The Ollama fields expose their placeholders as the operator's cue.
        expect(wrapper.find('input[placeholder="http://localhost:11434"]').exists()).toBe(true)
        expect(wrapper.find('input[placeholder="qwen3:8b"]').exists()).toBe(true)
      })

    it('keeps the warn-block switch inert until the cockpit is enabled', async () => {
        const wrapper = mountSection({ ai_trust_enabled: false })
        const warnSwitch = wrapper.findComponent(NSwitch)
        expect(warnSwitch.props('disabled')).toBe(true)

        // Toggling the master switch unlocks the dependent control.
        await wrapper.setProps({ aiTrust: { ...wrapper.props('aiTrust'), ai_trust_enabled: true } })
        expect(warnSwitch.props('disabled')).toBe(false)
      })

    it('exposes validate() that resolves true for a clean form', async () => {
        const wrapper = mountSection({ ai_trust_enabled: true })
        const withApi = wrapper.vm as unknown as { validate: () => Promise<boolean> }
        expect(await withApi.validate()).toBe(true)
      })
})
