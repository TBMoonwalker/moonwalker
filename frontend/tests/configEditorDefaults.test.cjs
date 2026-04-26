const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const configEditorDefaultsSource = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'helpers', 'configEditorDefaults.ts'),
    'utf8',
)
const configEditorAssemblySource = fs.readFileSync(
    path.join(
        __dirname,
        '..',
        'src',
        'composables',
        'useConfigEditorAssembly.ts',
    ),
    'utf8',
)

const {
    buildMoonwalkerApiUrl,
    CONFIG_ADVANCED_GENERAL_PREFERENCE_KEY,
    CONFIG_DEFAULT_SYMSIGNAL_URL,
    CONFIG_DEFAULT_SYMSIGNAL_VERSION,
    CONFIG_SUBMIT_PAYLOAD_DEFAULTS,
} = loadFrontendModule('src/helpers/configEditorDefaults.ts')

test('config editor defaults expose the shared API and payload defaults', () => {
    assert.equal(
        CONFIG_ADVANCED_GENERAL_PREFERENCE_KEY,
        'moonwalker.config.showAdvancedGeneral',
    )
    assert.equal(CONFIG_DEFAULT_SYMSIGNAL_URL, 'https://stream.3cqs.com')
    assert.equal(CONFIG_DEFAULT_SYMSIGNAL_VERSION, '3.0.1')
    assert.equal(
        buildMoonwalkerApiUrl('/config/live/activate'),
        'http://127.0.0.1:8130/config/live/activate',
    )
    assert.deepEqual(CONFIG_SUBMIT_PAYLOAD_DEFAULTS, {
        advancedWsHealthcheckIntervalMs: 5000,
        advancedWsStaleTimeoutMs: 20000,
        advancedWsReconnectDebounceMs: 2000,
        defaultTpSpikeConfirmSeconds: 3,
        defaultTpSpikeConfirmTicks: 0,
        defaultGreenPhaseRampDays: 30,
        defaultGreenPhaseEvalIntervalSec: 60,
        defaultGreenPhaseWindowMinutes: 60,
        defaultGreenPhaseMinProfitableCloseRatio: 0.8,
        defaultGreenPhaseSpeedMultiplier: 1.5,
        defaultGreenPhaseExitMultiplier: 1.15,
        defaultGreenPhaseMaxExtraDeals: 2,
        defaultGreenPhaseConfirmCycles: 2,
        defaultGreenPhaseReleaseCycles: 4,
        defaultGreenPhaseMaxLockedFundPercent: 85,
        defaultAutopilotProfitStretchRatio: 0,
        defaultAutopilotProfitStretchMax: 0,
        defaultAutopilotBaseOrderStretchMaxMultiplier: 1,
    })
})

test('config editor defaults centralize shared config-editor scaffolding', () => {
    const requiredHelperSnippets = [
        'export const CONFIG_ADVANCED_GENERAL_PREFERENCE_KEY =',
        'export const CONFIG_SUBMIT_PAYLOAD_DEFAULTS: ConfigSubmitPayloadDefaults =',
        'export function getClientTimezone(): string {',
        'export function buildMoonwalkerApiUrl(path: string): string {',
    ]
    const requiredAssemblySnippets = [
        "from '../helpers/configEditorDefaults'",
        'buildMoonwalkerApiUrl,',
        'CONFIG_ADVANCED_GENERAL_PREFERENCE_KEY,',
        'CONFIG_SUBMIT_PAYLOAD_DEFAULTS,',
        'getClientTimezone,',
        'export function useConfigEditorAssembly(',
    ]

    for (const snippet of requiredHelperSnippets) {
        assert.ok(
            configEditorDefaultsSource.includes(snippet),
            `expected config editor defaults helper to include ${snippet}`,
        )
    }
    for (const snippet of requiredAssemblySnippets) {
        assert.ok(
            configEditorAssemblySource.includes(snippet),
            `expected useConfigEditorAssembly.ts to include ${snippet}`,
        )
    }

    assert.equal(
        configEditorAssemblySource.includes('function getClientTimezone(): string {'),
        false,
    )
    assert.equal(
        configEditorAssemblySource.includes('const configSubmitPayloadDefaults:'),
        false,
    )
    assert.equal(configEditorAssemblySource.includes('const apiUrl ='), false)
})
