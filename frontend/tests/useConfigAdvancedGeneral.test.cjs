const assert = require('node:assert/strict')
const test = require('node:test')

const { ref, nextTick } = require('vue')

const { loadFrontendModule } = require('./helpers/loadFrontendModule.cjs')

const { useConfigAdvancedGeneral } = loadFrontendModule(
    'src/composables/useConfigAdvancedGeneral.ts',
)

function createPayloadDefaults(overrides = {}) {
    return {
        advancedWsHealthcheckIntervalMs: 30000,
        advancedWsStaleTimeoutMs: 45000,
        advancedWsReconnectDebounceMs: 5000,
        defaultTpSpikeConfirmSeconds: 20,
        defaultTpSpikeConfirmTicks: 5,
        defaultGreenPhaseRampDays: 7,
        defaultGreenPhaseEvalIntervalSec: 600,
        defaultGreenPhaseWindowMinutes: 90,
        defaultGreenPhaseMinProfitableCloseRatio: 0.35,
        defaultGreenPhaseSpeedMultiplier: 1.5,
        defaultGreenPhaseExitMultiplier: 1.1,
        defaultGreenPhaseMaxExtraDeals: 4,
        defaultGreenPhaseConfirmCycles: 3,
        defaultGreenPhaseReleaseCycles: 2,
        defaultGreenPhaseMaxLockedFundPercent: 55,
        defaultAutopilotProfitStretchRatio: 0,
        defaultAutopilotProfitStretchMax: 0,
        defaultAutopilotEntryStretchMaxMultiplier: 1,
        defaultAutopilotSafetyStretchMaxMultiplier: 1,
        ...overrides,
    }
}

function installLocalStorageMock(initialEntries = {}) {
    const store = new Map(Object.entries(initialEntries))
    const original = global.localStorage

    global.localStorage = {
        getItem(key) {
            return store.has(key) ? store.get(key) : null
        },
        setItem(key, value) {
            store.set(key, String(value))
        },
        removeItem(key) {
            store.delete(key)
        },
        clear() {
            store.clear()
        },
    }

    return {
        restore() {
            if (original === undefined) {
                delete global.localStorage
                return
            }
            global.localStorage = original
        },
        store,
    }
}

function createComposableOptions() {
    return {
        advancedPreferenceKey: 'moonwalker:test:advanced-general',
        defaultSymSignalUrl: 'https://signals.example/api',
        defaultSymSignalVersion: 'v2',
        defaults: createPayloadDefaults(),
        exchange: ref({
            name: 'binance',
            timeframe: '1h',
            key: 'key',
            secret: 'secret',
            exchange_hostname: 'api.exchange.test',
            dry_run: true,
            currency: 'USDT',
            market: 'spot',
            watcher_ohlcv: false,
        }),
        general: ref({
            timezone: 'Europe/Vienna',
            debug: false,
            ws_watchdog_enabled: false,
            ws_healthcheck_interval_ms: 12000,
            ws_stale_timeout_ms: 18000,
            ws_reconnect_debounce_ms: 24000,
        }),
        getClientTimezone: () => 'Europe/Vienna',
        isLoading: ref(false),
        showAdvancedGeneral: ref(true),
    }
}

test('useConfigAdvancedGeneral builds load defaults from local storage', () => {
    const localStorageMock = installLocalStorageMock({
        'moonwalker:test:advanced-general': 'true',
    })

    try {
        const options = createComposableOptions()
        const { buildConfigLoadDefaults } = useConfigAdvancedGeneral(options)
        const defaults = buildConfigLoadDefaults()

        assert.equal(defaults.clientTimezone, 'Europe/Vienna')
        assert.equal(defaults.showAdvancedGeneral, true)
        assert.equal(defaults.defaultSymSignalUrl, 'https://signals.example/api')
        assert.equal(defaults.defaultSymSignalVersion, 'v2')
        assert.equal(
            defaults.advancedWsHealthcheckIntervalMs,
            options.defaults.advancedWsHealthcheckIntervalMs,
        )
    } finally {
        localStorageMock.restore()
    }
})

test(
    'useConfigAdvancedGeneral persists the toggle without mutating config values',
    async () => {
        const localStorageMock = installLocalStorageMock()

        try {
            const options = createComposableOptions()
            useConfigAdvancedGeneral(options)

            options.showAdvancedGeneral.value = false
            await nextTick()

            assert.equal(
                localStorageMock.store.get(
                    'moonwalker:test:advanced-general',
                ),
                'false',
            )
            assert.equal(options.general.value.ws_watchdog_enabled, false)
            assert.equal(options.general.value.ws_healthcheck_interval_ms, 12000)
            assert.equal(options.general.value.ws_stale_timeout_ms, 18000)
            assert.equal(options.general.value.ws_reconnect_debounce_ms, 24000)
            assert.equal(options.exchange.value.exchange_hostname, 'api.exchange.test')
        } finally {
            localStorageMock.restore()
        }
    },
)
