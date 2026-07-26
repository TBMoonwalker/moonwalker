import { describe, expect, it } from 'vitest'

import {
    CONFIG_CONTRACT_VERSION,
    getConfigContractDefault,
} from '../src/helpers/configContract'

describe('config contract defaults', () => {
    it('uses a matching backend contract default', () => {
        const response = {
            config_contract: {
                version: CONFIG_CONTRACT_VERSION,
                fields: {
                    dynamic_so_atr_length: {
                        default: 21,
                    },
                },
            },
        }

        expect(
            getConfigContractDefault(response, 'dynamic_so_atr_length', 14),
        ).toBe(21)
    })

    it('falls back for missing or incompatible contracts', () => {
        expect(getConfigContractDefault({}, 'ai_trust_timeout_ms', 10_000)).toBe(
            10_000,
        )
        expect(
            getConfigContractDefault(
                {
                    config_contract: {
                        version: CONFIG_CONTRACT_VERSION + 1,
                        fields: {
                            ai_trust_timeout_ms: {
                                default: 50,
                            },
                        },
                    },
                },
                'ai_trust_timeout_ms',
                10_000,
            ),
        ).toBe(10_000)
    })

    it('supports false and empty defaults without treating them as missing', () => {
        const response = {
            config_contract: {
                version: CONFIG_CONTRACT_VERSION,
                fields: {
                    ai_trust_enabled: { default: false },
                    ai_trust_ollama_model: { default: '' },
                },
            },
        }

        expect(getConfigContractDefault(response, 'ai_trust_enabled', true)).toBe(
            false,
        )
        expect(
            getConfigContractDefault(
                response,
                'ai_trust_ollama_model',
                'fallback',
            ),
        ).toBe('')
    })
})
