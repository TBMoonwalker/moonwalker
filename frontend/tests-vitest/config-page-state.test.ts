import { describe, expect, it } from 'vitest'

import { useConfigPageState } from '../src/composables/useConfigPageState'
import type { ConfigSubmitPayloadDefaults } from '../src/helpers/configSubmitPayload'

describe('configuration exchange options', () => {
    it('maps Bybit EU to the CCXT bybiteu exchange class', () => {
        const { exchanges } = useConfigPageState({
            defaults: {} as ConfigSubmitPayloadDefaults,
        })

        expect(exchanges).toContainEqual({
            label: 'Bybit EU',
            value: 'bybiteu',
        })
    })
})
