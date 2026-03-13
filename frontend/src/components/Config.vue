<template>
    <n-flex vertical class="config-form-shell">
        <n-card title="General settings">
            <n-form ref="generalFormRef" :model="general" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="Timezone" path="timezone">
                    <n-select v-model:value="general.timezone" placeholder="Select" :options="timezone" filterable />
                </n-form-item>
                <n-form-item label="Debug mode" path="debug" label-placement="left">
                    <n-checkbox v-model:checked="general.debug" />
                </n-form-item>
                <n-form-item label="Advanced configuration" label-placement="left">
                    <n-switch v-model:value="showAdvancedGeneral" />
                </n-form-item>
                <template v-if="showAdvancedGeneral">
                    <n-form-item label="WebSocket watchdog enabled" path="ws_watchdog_enabled" label-placement="left">
                        <n-checkbox v-model:checked="general.ws_watchdog_enabled" />
                    </n-form-item>
                    <n-form-item label="WebSocket healthcheck interval (ms)" path="ws_healthcheck_interval_ms">
                        <n-input-number v-model:value="general.ws_healthcheck_interval_ms" :min="1000" />
                    </n-form-item>
                    <n-form-item label="WebSocket stale timeout (ms)" path="ws_stale_timeout_ms">
                        <n-input-number v-model:value="general.ws_stale_timeout_ms" :min="5000" />
                    </n-form-item>
                    <n-form-item label="WebSocket reconnect debounce (ms)" path="ws_reconnect_debounce_ms">
                        <n-input-number v-model:value="general.ws_reconnect_debounce_ms" :min="500" />
                    </n-form-item>
                </template>
            </n-form>
        </n-card>

        

        <n-card title="Exchange settings">
            <n-form ref="exchangeFormRef" :model="exchange" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="Exchange" path="name">
                    <n-select v-model:value="exchange.name" placeholder="Select" :options="exchanges" />
                </n-form-item>
                <n-form-item label="Timerange" path="timeframe">
                    <n-select v-model:value="exchange.timeframe" placeholder="Select" :options="timerange" />
                </n-form-item>
                <n-form-item label="Key" path="key">
                    <n-input v-model:value="exchange.key" type="password" show-password-on="click"
                        placeholder="Exchange Key" />
                </n-form-item>
                <n-form-item label="Secret" path="secret">
                    <n-input v-model:value="exchange.secret" type="password" show-password-on="click"
                        placeholder="Exchange Secret" />
                </n-form-item>
                <n-form-item v-if="showAdvancedGeneral" label="Exchange Hostname" path="exchange_hostname">
                    <n-input v-model:value="exchange.exchange_hostname" placeholder="e.g. bybit.eu" />
                </n-form-item>
                <n-form-item label="Dry Run (Demo Trading)" path="dryrun" label-placement="left">
                    <n-checkbox v-model:checked="exchange.dry_run" />
                </n-form-item>
                <n-form-item label="Currency" path="currency">
                    <n-select v-model:value="exchange.currency" placeholder="Select" :options="currency" />
                </n-form-item>
                <n-form-item label="Market" path="market">
                    <n-select v-model:value="exchange.market" placeholder="Select" :options="market" />
                </n-form-item>
                <n-form-item label="Use OHCLV" path="watcher" label-placement="left">
                    <n-checkbox v-model:checked="exchange.watcher_ohlcv" />
                </n-form-item>
            </n-form>
        </n-card>

        <n-card title=" Signal settings">
            <n-form ref="signalFormRef" :model="signal" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="Signal Plugin" path="signal">
                    <n-select v-model:value="signal.signal" placeholder="Select" :options="signal.plugins"
                        @update:value="handle_signal_settings_select" @blur="handle_signal_settings_select" />
                </n-form-item>

                <!-- Dynamic check for Sym Signal settings -->
                <template v-for="(index) in dynamicSymSignalSettingsForm" :key="index">
                    <n-form-item :label="'URL'" :path="'url.' + index">
                        <n-input v-model:value="signal.symsignal_url" placeholder="URL" />
                    </n-form-item>
                    <n-form-item :label="'Key'" :path="'key.' + index">
                        <n-input v-model:value="signal.symsignal_key" type="password" show-password-on="click"
                            placeholder="Key" />
                    </n-form-item>
                    <n-form-item :label="'Version'" :path="'version.' + index">
                        <n-input v-model:value="signal.symsignal_version" placeholder="Version" />
                    </n-form-item>
                    <n-form-item label="Allowed Signals" path="signals">
                        <n-select v-model:value="signal.symsignal_allowedsignals" placeholder="Select"
                            :options="symsignals" multiple filterable />
                    </n-form-item>
                </template>

                <!-- Dynamic check for ASAP Signal settings -->
                <template v-for="(index) in dynamicAsapSignalSettingsForm" :key="index">
                    <n-form-item label="Use URL input" path="asap_use_url" label-placement="left">
                        <n-switch v-model:value="signal.asap_use_url" />
                    </n-form-item>
                    <n-form-item v-if="signal.asap_use_url" label="Token/Coin List or URL" path="symbol_list">
                        <n-input
                            :value="signal.symbol_list"
                            placeholder="https://example.com/symbols.txt"
                            @update:value="handleAsapUrlInput"
                        />
                    </n-form-item>
                    <n-form-item v-else label="ASAP Symbol" path="symbol_list">
                        <n-flex vertical :style="{ width: '100%' }">
                            <n-alert v-if="!isAsapExchangeReady()" type="info">
                                Please configure {{ getAsapMissingFieldsLabel() }} in Exchange settings first.
                            </n-alert>
                            <n-alert v-else-if="signal.asap_symbol_fetch_error" type="warning">
                                {{ signal.asap_symbol_fetch_error }}
                            </n-alert>
                            <n-button
                                secondary
                                type="primary"
                                :loading="signal.asap_symbols_loading"
                                :disabled="!isAsapExchangeReady()"
                                @click="fetchAsapSymbolsForCurrency"
                            >
                                Load symbols from exchange
                            </n-button>
                            <n-select v-model:value="signal.asap_symbol_select" :options="signal.asap_symbol_options"
                                multiple
                                :loading="signal.asap_symbols_loading" :disabled="!isAsapExchangeReady() || signal.asap_symbol_options.length === 0"
                                placeholder="Select symbol" filterable />
                        </n-flex>
                    </n-form-item>
                </template>

                <!-- Dynamic check for CSV Signal settings -->
                <template v-for="(index) in dynamicCsvSignalSettingsForm" :key="index">
                    <n-form-item label="CSV input mode" path="csv_signal_mode">
                        <n-radio-group v-model:value="signal.csvsignal_mode">
                            <n-space>
                                <n-radio value="source">Path / URL</n-radio>
                                <n-radio value="inline">Paste text / Upload file</n-radio>
                            </n-space>
                        </n-radio-group>
                    </n-form-item>
                    <n-form-item
                        v-if="signal.csvsignal_mode === 'source'"
                        label="CSV source (path or URL)"
                        path="csv_signal_source"
                    >
                        <n-input
                            v-model:value="signal.csvsignal_source"
                            placeholder="/path/to/trades.csv or https://example.com/trades.csv"
                        />
                    </n-form-item>
                    <template v-else>
                        <n-form-item label="Paste CSV text" path="csv_signal_inline">
                            <n-input
                                v-model:value="signal.csvsignal_inline"
                                type="textarea"
                                :autosize="{
                                    minRows: 6,
                                    maxRows: 16,
                                }"
                                placeholder="date;symbol;price;amount&#10;18/08/2025 19:32:00;BTC/USDC;117644.41;0.00099153"
                            />
                        </n-form-item>
                        <n-form-item label="CSV file upload">
                            <n-flex align="center" :size="10">
                                <input
                                    ref="csvSignalFileInput"
                                    type="file"
                                    accept=".csv,text/csv"
                                    style="display: none;"
                                    @change="handleCsvSignalFileSelected"
                                />
                                <n-button secondary type="primary" @click="openCsvSignalFilePicker">
                                    Upload CSV file
                                </n-button>
                                <n-text v-if="signal.csvsignal_file_name" depth="3">
                                    Loaded: {{ signal.csvsignal_file_name }}
                                </n-text>
                            </n-flex>
                        </n-form-item>
                    </template>
                </template>

                <!-- Dynamic check for Strategy settings -->
                <template v-if="!isCsvSignalSelected">
                    <n-form-item label="Signal initial buy strategy" path="selectValue" label-placement="left">
                        <n-checkbox v-model:checked="signal.strategy_enabled" />
                    </n-form-item>
                    <template v-if="signal.strategy_enabled">
                        <n-form-item label="Strategy" path="strategy">
                            <n-select v-model:value="signal.strategy" placeholder="Select"
                                :options="signal.strategy_plugins" />
                        </n-form-item>
                    </template>
                </template>
            </n-form>
        </n-card>

        <n-card title="Filter settings">
            <n-form ref="filterFormRef" :model="filter" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="Denylist" path="denylist">
                    <n-input v-model:value="filter.denylist" placeholder="Textarea" type="textarea" :autosize="{
                        minRows: 3,
                        maxRows: 5,
                    }" />
                </n-form-item>
                <template v-for="(index) in dynamicAsapSignalSettingsForm" :key="index">
                    <n-form-item :label="'RSI Maximum'" :path="'rsi.' + index">
                        <n-input-number v-model:value="filter.rsi" placeholder="RSI Maximum" />
                    </n-form-item>
                    <n-form-item :label="'CMC API Key'" :path="'cmc_api_key.' + index">
                        <n-input v-model:value="filter.cmc_api_key" type="password" show-password-on="click"
                            placeholder="CMC API Key" />
                    </n-form-item>
                </template>

                <n-form-item :label="'Topcoin Limit'" path="topcoin_limit">
                    <n-input-number v-model:value="filter.topcoin_limit" placeholder="Topcoin Limit" />
                </n-form-item>

                <n-form-item :label="'Volume Limit'" path="volume_limit">
                    <n-input-number v-model:value="filter.volume" placeholder="Volume Limit" />
                </n-form-item>

                <n-form-item label="BTC Pulse" path="btc_pulse" label-placement="left">
                    <n-checkbox v-model:checked="filter.btc_pulse" />
                </n-form-item>

            </n-form>
        </n-card>

        

        <n-card title="DCA settings">
            <n-form ref="dcaFormRef" :model="dca" :rules="rules" label-width="auto" require-mark-placement="right-hanging"
                :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="Enabled" path="enabled" label-placement="left">
                    <n-checkbox v-model:checked="dca.enabled" @change="handle_dca_select" />
                </n-form-item>

                <!-- Dynamic check for Dynamic DCA settings -->
                <template v-for="(index) in DCAForm" :key="index">
                    <n-form-item label="Dynamic DCA" path="dynamic_dca" label-placement="left">
                        <n-checkbox v-model:checked="dca.dynamic" @change="handle_dynamic_dca_select" />
                    </n-form-item>
                    <template v-for="(index) in dynamicDCAForm" :key="index">
                        <n-form-item :label="'Dynamic DCA strategy'" :path="'strategy.' + index">
                            <n-select v-model:value="dca.strategy" placeholder="Select"
                                :options="signal.strategy_plugins" />
                        </n-form-item>
                    </template>
                </template>
                <n-form-item label="Take profit percentage" path="tp">
                    <n-input-number v-model:value="dca.tp" placeholder="TP" />
                </n-form-item>
                <n-form-item label="Trailing Take profit percentage" path="ttp">
                    <n-input-number v-model:value="dca.trailing_tp" placeholder="TTP" />
                </n-form-item>
                <n-form-item label="Max bots running" path="max_bots">
                    <n-input-number v-model:value="dca.max_bots" placeholder="Bot count" />
                </n-form-item>
                <n-form-item label="Base order amount" path="bo">
                    <n-input-number v-model:value="dca.bo" placeholder="BO" />
                </n-form-item>
                <n-form-item label="Sell order type" path="sell_order_type">
                    <n-select
                        v-model:value="dca.sell_order_type"
                        placeholder="Select"
                        :options="sellOrderTypeOptions"
                    />
                </n-form-item>
                <template v-if="dca.sell_order_type === 'limit'">
                    <n-form-item label="Limit sell timeout (seconds)" path="limit_sell_timeout_sec">
                        <n-input-number v-model:value="dca.limit_sell_timeout_sec" placeholder="60" />
                    </n-form-item>
                    <n-form-item label="Fallback to market sell on timeout" path="limit_sell_fallback_to_market" label-placement="left">
                        <n-checkbox v-model:checked="dca.limit_sell_fallback_to_market" />
                    </n-form-item>
                </template>
                <n-form-item v-if="dca.enabled && !dca.dynamic" label="Safety order amount" path="so">
                    <n-input-number v-model:value="dca.so" placeholder="SO" />
                </n-form-item>
                <n-form-item v-if="dca.enabled" label="Max safety order count" path="mstc">
                    <n-input-number v-model:value="dca.mstc" placeholder="MSTC" />
                </n-form-item>
                <n-form-item v-if="dca.enabled" label="Price deviation for first safety order" path="sos">
                    <n-input-number v-model:value="dca.sos" placeholder="SOS" />
                </n-form-item>
                <n-form-item v-if="dca.enabled && !dca.dynamic" label="Safety order step scale" path="ss">
                    <n-input-number v-model:value="dca.ss" placeholder="SS" />
                </n-form-item>
                <n-form-item v-if="dca.enabled && !dca.dynamic" label="Safety order volume scale" path="os">
                    <n-input-number v-model:value="dca.os" placeholder="OS" />
                </n-form-item>
                <n-form-item label="Stop loss percentage" path="sl">
                    <n-input-number v-model:value="dca.sl" placeholder="SL" />
                </n-form-item>
                <n-form-item
                    v-if="dca.enabled && dca.dynamic"
                    label="Safety order budget ratio"
                    path="trade_safety_order_budget_ratio"
                >
                    <n-input-number
                        v-model:value="dca.trade_safety_order_budget_ratio"
                        :min="0.01"
                        :max="1"
                        :step="0.01"
                        placeholder="0.95"
                    />
                </n-form-item>
            </n-form>
        </n-card>

        <n-card title="Autopilot settings">
            <n-form ref="autopilotFormRef" :model="autopilot" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">

                <n-form-item label="Enabled" path="enabled" label-placement="left">
                    <n-checkbox v-model:checked="autopilot.enabled" @change="handle_ap_select" />
                </n-form-item>

                <!-- Dynamic check for Autopilot settings -->
                <template v-for="(index) in APForm" :key="index">
                    <n-form-item label="Max fund" path="maxfund">
                        <n-input-number v-model:value="autopilot.max_fund" placeholder="Max fund" />
                    </n-form-item>
                    <n-form-item label="Max bots for high setting" path="highmad">
                        <n-input-number v-model:value="autopilot.high_mad" placeholder="Max bots high" />
                    </n-form-item>
                    <n-form-item label="Take profit for high setting" path="hightp">
                        <n-input-number v-model:value="autopilot.high_tp" placeholder="Take profit high" />
                    </n-form-item>
                    <n-form-item label="Stop loss for high setting" path="highsl">
                        <n-input-number v-model:value="autopilot.high_sl" placeholder="Stop loss high" />
                    </n-form-item>
                    <n-form-item label="Time threshold (in days) for stop loss" path="highsl_timeout">
                        <n-input-number v-model:value="autopilot.high_sl_timeout" placeholder="Stop loss timeout" />
                    </n-form-item>
                    <n-form-item label="Max threshold (in percent of max fund) for high setting" path="high_threshold">
                        <n-input-number v-model:value="autopilot.high_threshold" placeholder="Fund threshold" />
                    </n-form-item>
                    <n-form-item label="Max bots for medium setting" path="mediummad">
                        <n-input-number v-model:value="autopilot.medium_mad" placeholder="Max bots medium" />
                    </n-form-item>
                    <n-form-item label="Take profit for medium setting" path="mediumtp">
                        <n-input-number v-model:value="autopilot.medium_tp" placeholder="Take profit medium" />
                    </n-form-item>
                    <n-form-item label="Stop loss for medium setting" path="highsl">
                        <n-input-number v-model:value="autopilot.medium_sl" placeholder="Stop loss medium" />
                    </n-form-item>
                    <n-form-item label="Time threshold (in days) for stop loss" path="mediumsl_timeout">
                        <n-input-number v-model:value="autopilot.medium_sl_timeout" placeholder="Stop loss timeout" />
                    </n-form-item>
                    <n-form-item label="Max threshold (in percent of max fund) for medium setting"
                        path="medium_threshold">
                        <n-input-number v-model:value="autopilot.medium_threshold" placeholder="Fund threshold" />
                    </n-form-item>
                </template>

            </n-form>
        </n-card>

        <n-card title="Messaging / Monitoring settings">
            <n-form ref="monitoringFormRef" :model="monitoring" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="Enabled" path="monitoring_enabled" label-placement="left">
                    <n-checkbox v-model:checked="monitoring.enabled" />
                </n-form-item>
                <n-form-item label="Telegram Bot Token" path="monitoring_telegram_bot_token">
                    <n-input v-model:value="monitoring.telegram_bot_token" type="password" show-password-on="click"
                        placeholder="123456:ABC-DEF..." />
                </n-form-item>
                <n-form-item label="Telegram API ID" path="monitoring_telegram_api_id">
                    <n-input-number v-model:value="monitoring.telegram_api_id" placeholder="1234567" />
                </n-form-item>
                <n-form-item label="Telegram API Hash" path="monitoring_telegram_api_hash">
                    <n-input v-model:value="monitoring.telegram_api_hash" type="password" show-password-on="click"
                        placeholder="0123456789abcdef0123456789abcdef" />
                </n-form-item>
                <n-form-item label="Telegram Chat ID" path="monitoring_telegram_chat_id">
                    <n-input v-model:value="monitoring.telegram_chat_id" placeholder="e.g. 123456789 or -100123..." />
                </n-form-item>
                <n-form-item label="Timeout (seconds)" path="monitoring_timeout_sec">
                    <n-input-number v-model:value="monitoring.timeout_sec" placeholder="5" />
                </n-form-item>
                <n-form-item label="Retry count" path="monitoring_retry_count">
                    <n-input-number v-model:value="monitoring.retry_count" placeholder="1" />
                </n-form-item>
                <n-form-item label="Telegram connectivity">
                    <n-button
                        secondary
                        type="primary"
                        :loading="monitoring_test_loading"
                        :disabled="!canTestMonitoringTelegram()"
                        @click="testMonitoringTelegram"
                    >
                        Test Telegram
                    </n-button>
                </n-form-item>
            </n-form>
        </n-card>

        <n-card title="Indicator settings">
            <n-form ref="indicatorFormRef" :model="indicator" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="UPNL history retention (days, 0 = infinite)" path="upnl_housekeeping_interval">
                    <n-input-number v-model:value="indicator.upnl_housekeeping_interval"
                        placeholder="UPNL retention" />
                </n-form-item>
                <n-form-item label="History Lookback Time" path="history_lookback_time">
                    <n-select
                        v-model:value="indicator.history_lookback_time"
                        :options="historyLookbackOptions"
                        filterable
                        tag
                        placeholder="e.g. 90d, 1y"
                    />
                </n-form-item>
            </n-form>
        </n-card>

        <n-alert
            :type="saveBannerType"
            :title="saveBannerTitle"
            role="status"
            aria-live="polite"
        >
            {{ saveBannerMessage }}
        </n-alert>

        <n-button
            class="submit-button"
            round
            type="primary"
            :loading="saveState === 'saving'"
            :disabled="isSubmitDisabled"
            aria-label="Submit configuration changes"
            aria-keyshortcuts="Control+S Meta+S"
            @click="handleValidateButtonClick"
        >
            {{ submitButtonLabel }}
        </n-button>
    </n-flex>

</template>

<script setup lang="ts">
import { MOONWALKER_API_PORT, MOONWALKER_API_HOST } from '../config'
import {
    usePersistableStateTracking,
    type PersistableState,
} from '../composables/usePersistableStateTracking'
import {
    buildSignalSettingsValue,
    buildVolumeConfig,
    getDefaultHistoryLookbackByTimeframe,
    normalizePairEntries,
    parseStructuredConfigValue,
    parseSymbolListToArray,
    parseVolumeLimitToNumber,
    toTokenOnlyEntries,
} from '../helpers/configForm'
import { getAllTimeZones } from '../helpers/timezone'
import { parseBooleanString, isJsonString, toNumberOrNull } from '../helpers/validators'
import type { FormInst, FormItemRule, FormRules } from 'naive-ui/es/form'
import { useMessage } from 'naive-ui/es/message'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import axios from 'axios'
import { trackUiEvent } from '../utils/uiTelemetry'

interface dynamicSelectItem {
    value: string | null;
}

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

function getClientTimezone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
}

// Signal strategy
const dynamicSymSignalSettingsForm = ref<dynamicSelectItem[]>([])
const dynamicAsapSignalSettingsForm = ref<dynamicSelectItem[]>([])
const dynamicCsvSignalSettingsForm = ref<dynamicSelectItem[]>([])
const dynamicDCAForm = ref<dynamicSelectItem[]>([])
const DCAForm = ref<dynamicSelectItem[]>([])
const APForm = ref<dynamicSelectItem[]>([])
const generalFormRef = ref<FormInst | null>(null)
const signalFormRef = ref<FormInst | null>(null)
const filterFormRef = ref<FormInst | null>(null)
const exchangeFormRef = ref<FormInst | null>(null)
const dcaFormRef = ref<FormInst | null>(null)
const autopilotFormRef = ref<FormInst | null>(null)
const monitoringFormRef = ref<FormInst | null>(null)
const indicatorFormRef = ref<FormInst | null>(null)
const csvSignalFileInput = ref<HTMLInputElement | null>(null)
const message = useMessage()
const router = useRouter()
const isLoading = ref(true)
const showAdvancedGeneral = ref(false)
const monitoring_test_loading = ref(false)
const submitAttempted = ref(false)
const saveState = ref<SaveState>('idle')
const saveErrorMessage = ref<string | null>(null)
const lastSavedAt = ref<Date | null>(null)
const ADVANCED_GENERAL_PREFERENCE_KEY = 'moonwalker.config.showAdvancedGeneral'
const ADVANCED_WS_HEALTHCHECK_INTERVAL_MS = 5000
const ADVANCED_WS_STALE_TIMEOUT_MS = 20000
const ADVANCED_WS_RECONNECT_DEBOUNCE_MS = 2000

const DEFAULT_SYMSIGNAL_URL = "https://stream.3cqs.com"
const DEFAULT_SYMSIGNAL_VERSION = "3.0.1"
const timezone = ref([])
const timerange = [
    {
        label: '1m',
        value: '1m'
    },
    {
        label: '15m',
        value: '15m'
    },
    {
        label: '30m',
        value: '30m'
    },
    {
        label: '1h',
        value: '1h'
    },
    {
        label: '4h',
        value: '4h'
    },
    {
        label: '1d',
        value: '1d'
    },
]

const historyLookbackOptions = [
    { label: '30 days (1m default)', value: '30d' },
    { label: '90 days (15m default)', value: '90d' },
    { label: '180 days (1h default)', value: '180d' },
    { label: '1 year (4h default)', value: '1y' },
    { label: '3 years (1d default)', value: '3y' },
]

const exchanges = [
    {
        label: 'Binance',
        value: 'binance'
    },
    {
        label: 'Bybit',
        value: 'bybit'
    },
]

const currency = [
    {
        label: 'USDC',
        value: 'usdc',
    },
    {
        label: 'USDT',
        value: 'usdt',
    },
]

const market = [{
    label: 'Spot',
    value: 'spot'
}]

const sellOrderTypeOptions = [
    {
        label: 'Market',
        value: 'market',
    },
    {
        label: 'Limit',
        value: 'limit',
    },
]

const symsignals = [
    { label: "12 - SymRank Top 10", value: 12 },
    { label: "2 - SymRank Top 30", value: 2 },
    { label: "11 - SymRank Top 50", value: 11 },
    { label: "1 - SymRank Top 100 Triple Tracker", value: 1 },
    { label: "6 - SymRank Top 100 Quadruple Tracker", value: 6 },
    { label: "7 - SymRank Top 250 Quadruple Tracker", value: 7 },
    { label: "13 - SymScore Super Bullish", value: 13 },
    { label: "22 - SymScore Super Bullish Range", value: 22 },
    { label: "29 - SymScore Super-Hyper Bullish Range", value: 29 },
    { label: "14 - SymScore Hyper Bullish", value: 14 },
    { label: "23 - SymScore Hyper Bullish Range", value: 23 },
    { label: "27 - SymScore Hyper-Ultra Bullish Range", value: 27 },
    { label: "15 - SymScore Ultra Bullish", value: 15 },
    { label: "25 - SymScore Ultra Bullish Range", value: 25 },
    { label: "31 - SymScore Ultra-X-Treme Bullish Range", value: 31 },
    { label: "16 - SymScore X-Treme Bullish", value: 16 },
    { label: "54 - SymScore Neutral", value: 54 },
    { label: "17 - SymScore Super Bearish", value: 17 },
    { label: "21 - SymScore Super Bearish Range", value: 21 },
    { label: "30 - SymScore Super-Hyper Bearish Range", value: 30 },
    { label: "18 - SymScore Hyper Bearish", value: 18 },
    { label: "24 - SymScore Hyper Bearish Range", value: 24 },
    { label: "28 - SymScore Hyper-Ultra Bearish Range", value: 28 },
    { label: "19 - SymScore Ultra Bearish", value: 19 },
    { label: "26 - SymScore Ultra Bearish Range", value: 26 },
    { label: "32 - SymScore Ultra-X-Treme Bearish Range", value: 32 },
    { label: "20 - SymScore X-Treme Bearish", value: 20 },
    { label: "39 - SymSense Super Greed", value: 39 },
    { label: "48 - SymSense Super Greed Range", value: 48 },
    { label: "55 - SymSense Super-Hyper Greed Range", value: 55 },
    { label: "40 - SymSense Hyper Greed", value: 40 },
    { label: "49 - SymSense Hyper Greed Range", value: 49 },
    { label: "56 - SymSense Hyper-Ultra Greed Range", value: 56 },
    { label: "41 - SymSense Ultra Greed", value: 41 },
    { label: "50 - SymSense Ultra Greed Range", value: 50 },
    { label: "57 - SymSense Ultra-X-Treme Greed Range", value: 57 },
    { label: "42 - SymSense X-Treme Greed", value: 42 },
    { label: "43 - SymSense Neutral", value: 43 },
    { label: "44 - SymSense Super Fear", value: 44 },
    { label: "51 - SymSense Super Fear Range", value: 51 },
    { label: "58 - SymSense Super-Hyper Fear Range", value: 58 },
    { label: "45 - SymSense Hyper Fear", value: 45 },
    { label: "52 - SymSense Hyper Fear Range", value: 52 },
    { label: "59 - SymSense Hyper-Ultra Fear Range", value: 59 },
    { label: "46 - SymSense Ultra Fear", value: 46 },
    { label: "53 - SymSense Ultra Fear Range", value: 53 },
    { label: "60 - SymSense Ultra-X-Treme Fear Range", value: 60 },
    { label: "47 - SymSense X-Treme Fear", value: 47 },
    { label: "61 - SymSync 100", value: 61 },
    { label: "62 - SymSync 90", value: 62 },
    { label: "63 - SymSync 80", value: 63 },
    { label: "64 - SymSync 70", value: 64 },
    { label: "65 - SymSync 60", value: 65 },
    { label: "66 - SymSync 50", value: 66 },
    { label: "9 - Super Volatility", value: 9 },
    { label: "33 - Super Volatility Range", value: 33 },
    { label: "36 - Super-Hyper Volatility Range", value: 36 },
    { label: "10 - Super Volatility Double Tracker", value: 10 },
    { label: "3 - Hyper Volatility", value: 3 },
    { label: "34 - Hyper Volatility Range", value: 34 },
    { label: "37 - Hyper-Ultra Volatility Range", value: 37 },
    { label: "8 - Hyper Volatility Double Tracker", value: 8 },
    { label: "4 - Ultra Volatility", value: 4 },
    { label: "35 - Ultra Volatility Range", value: 35 },
    { label: "38 - Ultra-X-Treme Volatility Range", value: 38 },
    { label: "5 - X-Treme Volatility", value: 5 },
]

const general = ref({
    timezone: null,
    debug: false,
    ws_watchdog_enabled: true,
    ws_healthcheck_interval_ms: ADVANCED_WS_HEALTHCHECK_INTERVAL_MS,
    ws_stale_timeout_ms: ADVANCED_WS_STALE_TIMEOUT_MS,
    ws_reconnect_debounce_ms: ADVANCED_WS_RECONNECT_DEBOUNCE_MS,
})

const signal = ref({
    symbol_list: null,
    asap_use_url: true,
    asap_symbol_select: [] as string[],
    asap_symbol_options: [],
    asap_symbols_loading: false,
    asap_symbol_fetch_error: null,
    signal: null,
    plugins: [],
    strategy: null,
    strategy_enabled: false,
    strategy_plugins: [],
    timeframe: null,
    symsignal_url: null,
    symsignal_key: null,
    symsignal_version: null,
    symsignal_allowedsignals: [],
    csvsignal_mode: "source",
    csvsignal_source: null,
    csvsignal_inline: null,
    csvsignal_file_name: null,
})

const filter = ref({
    rsi: null,
    cmc_api_key: null,
    denylist: null,
    topcoin_limit: null,
    volume: null,
    btc_pulse: false,
})

const exchange = ref({
    name: null,
    timeframe: null,
    key: null,
    secret: null,
    exchange_hostname: null,
    dry_run: true,
    currency: null,
    market: "spot",
    watcher_ohlcv: false,
})

const dca = ref({
    enabled: false,
    dynamic: false,
    strategy: null,
    timeframe: null,
    trailing_tp: null,
    max_bots: null,
    bo: null,
    sell_order_type: 'market',
    limit_sell_timeout_sec: 60,
    limit_sell_fallback_to_market: true,
    so: null,
    mstc: null,
    sos: null,
    ss: null,
    os: null,
    trade_safety_order_budget_ratio: 0.95,
    tp: null,
    sl: null,
})

const autopilot = ref({
    enabled: false,
    max_fund: null,
    high_mad: null,
    high_tp: null,
    high_sl: null,
    high_sl_timeout: null,
    high_threshold: null,
    medium_mad: null,
    medium_tp: null,
    medium_sl: null,
    medium_sl_timeout: null,
    medium_threshold: null,
})

const monitoring = ref({
    enabled: false,
    telegram_bot_token: null,
    telegram_api_id: null,
    telegram_api_hash: null,
    telegram_chat_id: null,
    timeout_sec: 5,
    retry_count: 1,
})

const indicator = ref({
    upnl_housekeeping_interval: 0,
    history_lookback_time: null,
})
const isCsvSignalSelected = computed(() => signal.value.signal === 'csv_signal')

function resetSignalStrategySelection(): void {
    signal.value.strategy_enabled = false
    signal.value.strategy = null
}

const SECTION_LABELS: Record<string, string> = {
    general: 'General',
    signal: 'Signal',
    filter: 'Filter',
    exchange: 'Exchange',
    dca: 'DCA',
    autopilot: 'Autopilot',
    monitoring: 'Monitoring',
    indicator: 'Indicator',
}

function buildPersistableState(): PersistableState {
    return {
        general: {
            ...general.value,
            show_advanced_general: showAdvancedGeneral.value,
        },
        signal: {
            symbol_list: signal.value.symbol_list,
            asap_use_url: signal.value.asap_use_url,
            asap_symbol_select: signal.value.asap_symbol_select,
            signal: signal.value.signal,
            strategy: signal.value.strategy,
            strategy_enabled: signal.value.strategy_enabled,
            timeframe: signal.value.timeframe,
            symsignal_url: signal.value.symsignal_url,
            symsignal_key: signal.value.symsignal_key,
            symsignal_version: signal.value.symsignal_version,
            symsignal_allowedsignals: signal.value.symsignal_allowedsignals,
            csvsignal_mode: signal.value.csvsignal_mode,
            csvsignal_source: signal.value.csvsignal_source,
            csvsignal_inline: signal.value.csvsignal_inline,
            csvsignal_file_name: signal.value.csvsignal_file_name,
        },
        filter: { ...filter.value },
        exchange: { ...exchange.value },
        dca: { ...dca.value },
        autopilot: { ...autopilot.value },
        monitoring: { ...monitoring.value },
        indicator: { ...indicator.value },
    }
}
const { changedSectionLabels, changedSections, isDirty, syncBaselineState } =
    usePersistableStateTracking({
        buildState: buildPersistableState,
        sectionLabels: SECTION_LABELS,
    })
const submitButtonLabel = computed(() => {
    if (saveState.value === 'saving') {
        return 'Saving...'
    }
    if (isDirty.value) {
        return 'Submit changes'
    }
    return 'No changes'
})
const saveBannerType = computed(() => {
    if (saveState.value === 'error') {
        return 'error'
    }
    if (saveState.value === 'saved') {
        return 'success'
    }
    if (isDirty.value) {
        return 'warning'
    }
    return 'info'
})
const saveBannerTitle = computed(() => {
    if (saveState.value === 'error') {
        return 'Save failed'
    }
    if (saveState.value === 'saved') {
        return 'Saved'
    }
    if (isDirty.value) {
        return 'Unsaved changes'
    }
    return 'No pending changes'
})
const saveBannerMessage = computed(() => {
    if (saveState.value === 'error' && saveErrorMessage.value) {
        return saveErrorMessage.value
    }
    if (saveState.value === 'saved' && lastSavedAt.value) {
        return `Configuration saved at ${lastSavedAt.value.toLocaleTimeString()}`
    }
    if (isDirty.value) {
        const changed = changedSectionLabels.value.join(', ')
        return changed.length > 0
            ? `Changed sections: ${changed}`
            : 'You have unsaved changes.'
    }
    return 'Edit any field and submit to persist updates.'
})
const isSubmitDisabled = computed(
    () => isLoading.value || saveState.value === 'saving' || !isDirty.value,
)

function hasUnsavedChanges(): boolean {
    return !isLoading.value && isDirty.value
}

function setSaveError(messageText: string): void {
    saveState.value = 'error'
    saveErrorMessage.value = messageText
}

function confirmDiscardUnsavedChanges(source: 'route_leave' | 'page_unload'): boolean {
    if (!hasUnsavedChanges()) {
        return true
    }
    if (source === 'page_unload') {
        return false
    }
    const confirmLeave = window.confirm(
        'You have unsaved changes. Leave this page and discard them?',
    )
    trackUiEvent('config_unsaved_prompt', {
        source,
        confirmed: confirmLeave,
        dirty_sections: changedSections.value.length,
    })
    return confirmLeave
}

const handleBeforeUnload = (event: BeforeUnloadEvent) => {
    if (confirmDiscardUnsavedChanges('page_unload')) {
        return
    }
    event.preventDefault()
    event.returnValue = ''
}

function getStoredAdvancedGeneralPreference(): boolean {
    const raw = localStorage.getItem(ADVANCED_GENERAL_PREFERENCE_KEY)
    return raw === 'true'
}

function resetAdvancedGeneralSettings(): void {
    general.value.ws_watchdog_enabled = true
    general.value.ws_healthcheck_interval_ms = ADVANCED_WS_HEALTHCHECK_INTERVAL_MS
    general.value.ws_stale_timeout_ms = ADVANCED_WS_STALE_TIMEOUT_MS
    general.value.ws_reconnect_debounce_ms = ADVANCED_WS_RECONNECT_DEBOUNCE_MS
    exchange.value.exchange_hostname = null
}

function dcaFieldValidator(
    fieldLabel: string,
    requiredWhen: () => boolean = () => true,
) {
    return (_rule: FormItemRule, value: unknown) => {
        if (!dca.value.enabled) {
            return true
        }
        if (!requiredWhen()) {
            return true
        }
        if (value === null || value === undefined) {
            return new Error(`Please add ${fieldLabel}`)
        }
        if (typeof value === 'string' && value.trim().length === 0) {
            return new Error(`Please add ${fieldLabel}`)
        }
        return true
    }
}

function requiredAfterSubmit(messageText: string) {
    return (_rule: FormItemRule, value: unknown) => {
        if (!submitAttempted.value) {
            return true
        }
        if (value === null || value === undefined) {
            return new Error(messageText)
        }
        if (typeof value === 'string' && value.trim().length === 0) {
            return new Error(messageText)
        }
        if (Array.isArray(value) && value.length === 0) {
            return new Error(messageText)
        }
        return true
    }
}

function isCurrencyConfigured(): boolean {
    const configuredCurrency = exchange.value.currency
    if (!configuredCurrency) {
        return false
    }
    return String(configuredCurrency).trim().length > 0
}

function getAsapExchangeMissingFields(): string[] {
    const missing: string[] = []
    if (!exchange.value.name) {
        missing.push('exchange')
    }
    if (!exchange.value.key) {
        missing.push('key')
    }
    if (!exchange.value.secret) {
        missing.push('secret')
    }
    if (!isCurrencyConfigured()) {
        missing.push('currency')
    }
    return missing
}

function isAsapExchangeReady(): boolean {
    return getAsapExchangeMissingFields().length === 0
}

function getAsapMissingFieldsLabel(): string {
    return getAsapExchangeMissingFields().join(', ')
}

function isUrlInput(value: string | null): boolean {
    if (!value) {
        return false
    }
    return /^https?:\/\//i.test(value.trim())
}

const ASAP_URL_PARTIAL_PATTERN =
    /^(?:|h|ht|htt|http|https|http:|https:|http:\/|https:\/|https?:\/\/[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]*)$/

function handleAsapUrlInput(value: string): void {
    if (ASAP_URL_PARTIAL_PATTERN.test(value)) {
        signal.value.symbol_list = value
    }
}

async function fetchAsapSymbolsForCurrency(): Promise<void> {
    signal.value.asap_symbol_options = []
    signal.value.asap_symbol_fetch_error = null
    signal.value.asap_symbols_loading = true

    if (!isAsapExchangeReady()) {
        signal.value.asap_symbol_fetch_error = `Missing exchange configuration: ${getAsapMissingFieldsLabel()}`
        signal.value.asap_symbols_loading = false
        return
    }

    try {
        const quoteCurrency = String(exchange.value.currency).toUpperCase()
        const response = await axios.post(
            `http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/data/exchange/symbols`,
            {
                currency: quoteCurrency,
                exchange_config: {
                    exchange: exchange.value.name,
                    key: exchange.value.key,
                    secret: exchange.value.secret,
                    exchange_hostname: exchange.value.exchange_hostname || undefined,
                    market: exchange.value.market || "spot",
                    dry_run: exchange.value.dry_run ?? true,
                },
            },
        )
        const symbols = Array.isArray(response.data?.symbols) ? response.data.symbols : []
        const missing = Array.isArray(response.data?.missing) ? response.data.missing : []
        if (missing.length > 0) {
            signal.value.asap_symbol_fetch_error = `Missing exchange configuration: ${missing.join(', ')}`
            signal.value.asap_symbol_options = []
            return
        }
        signal.value.asap_symbol_options = symbols.map((symbol: string) => ({
            label: symbol,
            value: symbol,
        }))

        if (
            typeof signal.value.symbol_list === 'string' &&
            signal.value.symbol_list.length > 0
        ) {
            const configuredSymbols = parseSymbolListToArray(signal.value.symbol_list)
            const optionValues = new Set(
                signal.value.asap_symbol_options.map((option) => option.value as string)
            )
            signal.value.asap_symbol_select = configuredSymbols.filter((symbol) =>
                optionValues.has(symbol)
            )
        }
    } catch (error) {
        console.error('Error fetching ASAP symbols:', error)
        signal.value.asap_symbol_fetch_error = 'Failed to fetch symbols from exchange.'
    } finally {
        signal.value.asap_symbols_loading = false
    }
}

const rules: FormRules = {
    timezone: {
        validator: requiredAfterSubmit('Please select timezone'),
        trigger: ['submit', 'change']
    },
    signal: {
        validator: requiredAfterSubmit('Please select signal plugin'),
        trigger: ['submit', 'change']
    },
    signal_settings: {
        validator: requiredAfterSubmit('Please configure signal'),
        trigger: ['submit', 'change']
    },
    symbol_list: {
        validator: () => {
            if (!submitAttempted.value || signal.value.signal !== 'asap') {
                return true
            }
            if (signal.value.asap_use_url) {
                if (
                    signal.value.symbol_list === null ||
                    signal.value.symbol_list === undefined ||
                    String(signal.value.symbol_list).trim().length === 0
                ) {
                    return new Error('Please add symbol list URL')
                }
                if (!isUrlInput(String(signal.value.symbol_list))) {
                    return new Error('Please provide a valid URL (http/https)')
                }
                return true
            }

            if (!isCurrencyConfigured()) {
                return new Error('Please configure currency before selecting symbols')
            }

            if (!isAsapExchangeReady()) {
                return new Error(`Please configure ${getAsapMissingFieldsLabel()} before selecting symbols`)
            }

            if (!signal.value.asap_symbol_select) {
                return new Error('Please select at least one symbol')
            }

            if (Array.isArray(signal.value.asap_symbol_select) && signal.value.asap_symbol_select.length === 0) {
                return new Error('Please select at least one symbol')
            }

            return true
        },
        trigger: ['submit', 'change']
    },
    csv_signal_source: {
        validator: () => {
            if (
                !submitAttempted.value ||
                signal.value.signal !== 'csv_signal' ||
                signal.value.csvsignal_mode !== 'source'
            ) {
                return true
            }
            if (
                signal.value.csvsignal_source === null ||
                signal.value.csvsignal_source === undefined ||
                String(signal.value.csvsignal_source).trim().length === 0
            ) {
                return new Error('Please add CSV source path or URL')
            }
            return true
        },
        trigger: ['submit', 'change']
    },
    csv_signal_inline: {
        validator: () => {
            if (
                !submitAttempted.value ||
                signal.value.signal !== 'csv_signal' ||
                signal.value.csvsignal_mode !== 'inline'
            ) {
                return true
            }
            if (
                signal.value.csvsignal_inline === null ||
                signal.value.csvsignal_inline === undefined ||
                String(signal.value.csvsignal_inline).trim().length === 0
            ) {
                return new Error('Please paste CSV text or upload a CSV file')
            }
            return true
        },
        trigger: ['submit', 'change']
    },
    name: {
        validator: requiredAfterSubmit('Please select exchange'),
        trigger: ['submit', 'change']
    },
    timeframe: {
        validator: requiredAfterSubmit('Please select timeframe'),
        trigger: ['submit', 'change']
    },
    key: {
        validator: requiredAfterSubmit('Please add key'),
        trigger: ['submit', 'change']
    },
    secret: {
        validator: requiredAfterSubmit('Please add secret'),
        trigger: ['submit', 'change']
    },
    currency: {
        validator: requiredAfterSubmit('Please select currency'),
        trigger: ['submit', 'change']
    },
    max_bots: {
        validator: requiredAfterSubmit('Please add max bots'),
        trigger: ['submit', 'change']
    },
    bo: {
        validator: requiredAfterSubmit('Please add bo'),
        trigger: ['submit', 'change']
    },
    so: {
        validator: dcaFieldValidator(
            'safety order amount',
            () => !dca.value.dynamic,
        ),
        trigger: ['submit'],
    },
    mstc: {
        validator: dcaFieldValidator('max safety order count'),
        trigger: ['submit'],
    },
    sos: {
        validator: dcaFieldValidator('price deviation'),
        trigger: ['submit'],
    },
    ss: {
        validator: dcaFieldValidator(
            'step scale',
            () => !dca.value.dynamic,
        ),
        trigger: ['submit'],
    },
    os: {
        validator: dcaFieldValidator(
            'volume scale',
            () => !dca.value.dynamic,
        ),
        trigger: ['submit'],
    },
    tp: {
        validator: requiredAfterSubmit('Please add tp'),
        trigger: ['submit', 'change']
    },
    upnl_housekeeping_interval: {
        validator: requiredAfterSubmit('Please add UPNL history retention'),
        trigger: ['submit', 'change']
    },
    history_lookback_time: {
        validator: requiredAfterSubmit('Please add history lookback time'),
        trigger: ['submit', 'change']
    },
}

function handle_signal_settings_select() {
    if (signal.value.signal == "sym_signals") {
        if (dynamicSymSignalSettingsForm.value.length === 0) {
            dynamicSymSignalSettingsForm.value.push({ value: null })
        }
        if (!signal.value.symsignal_url) {
            signal.value.symsignal_url = DEFAULT_SYMSIGNAL_URL
        }
        if (!signal.value.symsignal_version) {
            signal.value.symsignal_version = DEFAULT_SYMSIGNAL_VERSION
        }
        dynamicAsapSignalSettingsForm.value = []
        dynamicCsvSignalSettingsForm.value = []
    } else if (signal.value.signal == "asap") {
        if (dynamicAsapSignalSettingsForm.value.length === 0) {
            dynamicAsapSignalSettingsForm.value.push({ value: null })
        }
        dynamicSymSignalSettingsForm.value = []
        dynamicCsvSignalSettingsForm.value = []
        if (!signal.value.asap_use_url) {
            void fetchAsapSymbolsForCurrency()
        }
    } else if (signal.value.signal == "csv_signal") {
        if (dynamicCsvSignalSettingsForm.value.length === 0) {
            dynamicCsvSignalSettingsForm.value.push({ value: null })
        }
        resetSignalStrategySelection()
        if (!signal.value.csvsignal_mode) {
            signal.value.csvsignal_mode = 'source'
        }
        dynamicSymSignalSettingsForm.value = []
        dynamicAsapSignalSettingsForm.value = []
    } else {
        dynamicSymSignalSettingsForm.value = []
        dynamicAsapSignalSettingsForm.value = []
        dynamicCsvSignalSettingsForm.value = []
    }
}

function handle_dynamic_dca_select() {
    if (dca.value.dynamic && dca.value.enabled === true) {
        // Add a new select item when activated
        dynamicDCAForm.value.push({ value: null })
    } else {
        // Remove the last select item when deactivated
        dynamicDCAForm.value.pop()
    }
}

function handle_dca_select() {
    if (dca.value.enabled === true) {
        // Add a new select item when activated
        DCAForm.value.push({ value: null })
    } else {
        // Remove the last select item when deactivated
        DCAForm.value.pop()
    }
}

function handle_ap_select() {
    if (autopilot.value.enabled === true) {
        // Add a new select item when activated
        APForm.value.push({ value: null })
    } else {
        // Remove the last select item when deactivated
        APForm.value.pop()
    }
}

function openCsvSignalFilePicker(): void {
    csvSignalFileInput.value?.click()
}

async function handleCsvSignalFileSelected(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement
    const selectedFile = input.files?.[0]
    if (!selectedFile) {
        return
    }

    try {
        const csvText = await selectedFile.text()
        signal.value.csvsignal_mode = 'inline'
        signal.value.csvsignal_inline = csvText
        signal.value.csvsignal_file_name = selectedFile.name
        message.success(`Loaded ${selectedFile.name}`)
    } catch (error) {
        console.error('Error loading CSV file:', error)
        message.error('Failed to read CSV file.')
    } finally {
        input.value = ''
    }
}

async function fetchDefaultValues() {
    try {
        const response = await axios.get(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/config/all`);
        if (response.status === 200) {
            general.value.timezone = response.data.timezone || getClientTimezone()
            general.value.debug = parseBooleanString(response.data.debug) ?? false
            general.value.ws_watchdog_enabled =
                parseBooleanString(response.data.ws_watchdog_enabled) ?? true
            general.value.ws_healthcheck_interval_ms =
                toNumberOrNull(response.data.ws_healthcheck_interval_ms) ?? ADVANCED_WS_HEALTHCHECK_INTERVAL_MS
            general.value.ws_stale_timeout_ms =
                toNumberOrNull(response.data.ws_stale_timeout_ms) ?? ADVANCED_WS_STALE_TIMEOUT_MS
            general.value.ws_reconnect_debounce_ms =
                toNumberOrNull(response.data.ws_reconnect_debounce_ms) ?? ADVANCED_WS_RECONNECT_DEBOUNCE_MS
            signal.value.signal = response.data.signal
            signal.value.strategy = response.data.signal_strategy
            signal.value.timeframe = response.data.timeframe
            const signalSettings = parseStructuredConfigValue(response.data.signal_settings)
            if (signalSettings) {
                signal.value.symsignal_url = String(signalSettings["api_url"] || DEFAULT_SYMSIGNAL_URL)
                signal.value.symsignal_key = String(signalSettings["api_key"] || "")
                signal.value.symsignal_version = String(signalSettings["api_version"] || DEFAULT_SYMSIGNAL_VERSION)
                const allowedSignals = signalSettings["allowed_signals"]
                signal.value.symsignal_allowedsignals = Array.isArray(allowedSignals) ? allowedSignals : []
                const csvSourceRaw = signalSettings["csv_source"]
                if (csvSourceRaw) {
                    const csvSource = String(csvSourceRaw)
                    const isInlineCsv = csvSource.includes('\n') && csvSource.includes(';')
                    if (isInlineCsv) {
                        signal.value.csvsignal_mode = 'inline'
                        signal.value.csvsignal_inline = csvSource
                        signal.value.csvsignal_source = null
                    } else {
                        signal.value.csvsignal_mode = 'source'
                        signal.value.csvsignal_source = csvSource
                        signal.value.csvsignal_inline = null
                    }
                } else {
                    signal.value.csvsignal_mode = 'source'
                    signal.value.csvsignal_source = null
                    signal.value.csvsignal_inline = null
                }
                signal.value.csvsignal_file_name = null
            } else {
                signal.value.csvsignal_mode = 'source'
                signal.value.csvsignal_source = null
                signal.value.csvsignal_inline = null
                signal.value.csvsignal_file_name = null
            }
            signal.value.symbol_list = response.data.symbol_list
            if (isUrlInput(response.data.symbol_list)) {
                signal.value.asap_use_url = true
                signal.value.asap_symbol_select = []
                signal.value.asap_symbol_options = []
            } else {
                signal.value.asap_use_url = false
                const configuredSymbols = parseSymbolListToArray(response.data.symbol_list)
                signal.value.asap_symbol_select = configuredSymbols
                signal.value.asap_symbol_options = configuredSymbols.map((symbol) => ({
                    label: symbol,
                    value: symbol,
                }))
            }
            const filter_indicator = parseStructuredConfigValue(response.data.filter)
            filter.value.rsi =
                toNumberOrNull(response.data.rsi_max) ??
                toNumberOrNull(filter_indicator?.rsi_max) ??
                null
            filter.value.cmc_api_key =
                response.data.marketcap_cmc_api_key ||
                String(filter_indicator?.marketcap_cmc_api_key || '') ||
                null
            filter.value.denylist = toTokenOnlyEntries(response.data.pair_denylist)
            filter.value.topcoin_limit = response.data.topcoin_limit
            filter.value.volume =
                toNumberOrNull(response.data.volume) ??
                parseVolumeLimitToNumber(response.data.volume)
            filter.value.btc_pulse = parseBooleanString(response.data.btc_pulse) ?? false
            exchange.value.name = response.data.exchange
            exchange.value.timeframe = response.data.timeframe
            exchange.value.key = response.data.key
            exchange.value.secret = response.data.secret
            exchange.value.exchange_hostname = response.data.exchange_hostname || null
            exchange.value.dry_run = parseBooleanString(response.data.dry_run) ?? true
            exchange.value.currency = response.data.currency
            exchange.value.market = response.data.market || "spot"
            exchange.value.watcher_ohlcv = parseBooleanString(response.data.watcher_ohlcv) ?? false
            dca.value.enabled = parseBooleanString(response.data.dca) ?? false
            dca.value.dynamic = parseBooleanString(response.data.dynamic_dca) ?? false
            dca.value.strategy = response.data.dca_strategy
            dca.value.timeframe = response.data.timeframe
            dca.value.trailing_tp = toNumberOrNull(response.data.trailing_tp)
            dca.value.max_bots = toNumberOrNull(response.data.max_bots)
            dca.value.bo = toNumberOrNull(response.data.bo)
            dca.value.sell_order_type = response.data.sell_order_type || 'market'
            dca.value.limit_sell_timeout_sec =
                toNumberOrNull(response.data.limit_sell_timeout_sec) ?? 60
            dca.value.limit_sell_fallback_to_market =
                parseBooleanString(response.data.limit_sell_fallback_to_market) ?? true
            dca.value.so = toNumberOrNull(response.data.so)
            dca.value.mstc = toNumberOrNull(response.data.mstc)
            dca.value.sos = toNumberOrNull(response.data.sos)
            dca.value.ss = toNumberOrNull(response.data.ss)
            dca.value.os = toNumberOrNull(response.data.os)
            dca.value.trade_safety_order_budget_ratio =
                toNumberOrNull(response.data.trade_safety_order_budget_ratio) ?? 0.95
            dca.value.tp = toNumberOrNull(response.data.tp)
            dca.value.sl = toNumberOrNull(response.data.sl)
            autopilot.value.enabled = parseBooleanString(response.data.autopilot) ?? false
            autopilot.value.max_fund = toNumberOrNull(response.data.autopilot_max_fund)
            autopilot.value.high_mad = toNumberOrNull(response.data.autopilot_high_mad)
            autopilot.value.high_tp = toNumberOrNull(response.data.autopilot_high_tp)
            autopilot.value.high_sl = toNumberOrNull(response.data.autopilot_high_sl)
            autopilot.value.high_sl_timeout = toNumberOrNull(response.data.autopilot_high_sl_timeout)
            autopilot.value.high_threshold = toNumberOrNull(response.data.autopilot_high_threshold)
            autopilot.value.medium_mad = toNumberOrNull(response.data.autopilot_medium_mad)
            autopilot.value.medium_tp = toNumberOrNull(response.data.autopilot_medium_tp)
            autopilot.value.medium_sl = toNumberOrNull(response.data.autopilot_medium_sl)
            autopilot.value.medium_sl_timeout = toNumberOrNull(response.data.autopilot_medium_sl_timeout)
            autopilot.value.medium_threshold = toNumberOrNull(response.data.autopilot_medium_threshold)
            monitoring.value.enabled = parseBooleanString(response.data.monitoring_enabled) ?? false
            monitoring.value.telegram_bot_token =
                response.data.monitoring_telegram_bot_token || null
            monitoring.value.telegram_api_id =
                toNumberOrNull(response.data.monitoring_telegram_api_id)
            monitoring.value.telegram_api_hash =
                response.data.monitoring_telegram_api_hash || null
            monitoring.value.telegram_chat_id =
                response.data.monitoring_telegram_chat_id || null
            monitoring.value.timeout_sec =
                toNumberOrNull(response.data.monitoring_timeout_sec) ?? 5
            monitoring.value.retry_count =
                toNumberOrNull(response.data.monitoring_retry_count) ?? 1
            indicator.value.upnl_housekeeping_interval = toNumberOrNull(response.data.upnl_housekeeping_interval) ?? 0
            indicator.value.history_lookback_time =
                response.data.history_lookback_time ||
                getDefaultHistoryLookbackByTimeframe(exchange.value.timeframe)

            showAdvancedGeneral.value = getStoredAdvancedGeneralPreference()
            if (!showAdvancedGeneral.value) {
                resetAdvancedGeneralSettings()
            }

            signal.value.strategy_plugins = response.data.strategies.map(v => ({
                label: v,
                value: v
            }))
            signal.value.plugins = response.data.signal_plugins.map(v => ({
                label: v,
                value: v
            }))
            exchange.value.name = response.data.exchange

            // Show hidden strategy fields if enabled
            if (signal.value.strategy) {
                signal.value.strategy_enabled = true
            }

            // Initial call for signal settings
            handle_signal_settings_select()
            handle_dca_select()
            handle_dynamic_dca_select()
            if (signal.value.signal === "asap" && !signal.value.asap_use_url) {
                await fetchAsapSymbolsForCurrency()
            }

            syncBaselineState()
            saveState.value = 'idle'
            saveErrorMessage.value = null
            lastSavedAt.value = null
            trackUiEvent('config_baseline_loaded')

        } else {
            message.error('Failed to load default values')
            setSaveError('Failed to load configuration.')
        }
    } catch (error) {
        console.error('Error fetching default values:', error);
        message.error('An unexpected error occurred while loading default values.')
        setSaveError('An unexpected error occurred while loading default values.')
    } finally {
        isLoading.value = false; // Set loading state to false after fetch
    }
}

async function submitForm() {
    if (!isDirty.value) {
        message.info('No unsaved changes to submit.')
        trackUiEvent('config_submit_skipped_no_changes')
        return
    }
    if (saveState.value === 'saving') {
        return
    }

    const submitStartedAt = performance.now()
    const dirtySectionsBeforeSubmit = changedSections.value.length
    trackUiEvent('config_submit_requested')
    saveState.value = 'saving'
    saveErrorMessage.value = null

    try {
        const quoteCurrency = String(exchange.value.currency || "USDT").toUpperCase()
        const normalizedSymbolList = signal.value.signal === "asap"
            ? normalizePairEntries(
                signal.value.asap_use_url
                    ? signal.value.symbol_list
                    : signal.value.asap_symbol_select.join(","),
                quoteCurrency,
            )
            : false
        const normalizedDenyList = normalizePairEntries(
            filter.value.denylist,
            quoteCurrency,
        )

        const formData = {
            timezone: JSON.stringify({ 'value': general.value.timezone || false, 'type': "str" }),
            debug: JSON.stringify({ 'value': general.value.debug || false, 'type': "bool" }),
            ws_watchdog_enabled: JSON.stringify({ 'value': general.value.ws_watchdog_enabled ?? true, 'type': "bool" }),
            ws_healthcheck_interval_ms: JSON.stringify({ 'value': general.value.ws_healthcheck_interval_ms ?? ADVANCED_WS_HEALTHCHECK_INTERVAL_MS, 'type': "int" }),
            ws_stale_timeout_ms: JSON.stringify({ 'value': general.value.ws_stale_timeout_ms ?? ADVANCED_WS_STALE_TIMEOUT_MS, 'type': "int" }),
            ws_reconnect_debounce_ms: JSON.stringify({ 'value': general.value.ws_reconnect_debounce_ms ?? ADVANCED_WS_RECONNECT_DEBOUNCE_MS, 'type': "int" }),
            signal: JSON.stringify({ 'value': signal.value.signal || false, 'type': "str" }),
            signal_strategy: JSON.stringify({
                'value': signal.value.signal === 'csv_signal'
                    ? false
                    : (signal.value.strategy_enabled && signal.value.strategy ? signal.value.strategy : false),
                'type': "str"
            }),
            signal_settings: JSON.stringify({
                'value': buildSignalSettingsValue({
                    signal: signal.value.signal,
                    symsignal_url: signal.value.symsignal_url,
                    symsignal_key: signal.value.symsignal_key,
                    symsignal_version: signal.value.symsignal_version,
                    symsignal_allowedsignals: signal.value.symsignal_allowedsignals,
                    csvsignal_mode: signal.value.csvsignal_mode,
                    csvsignal_source: signal.value.csvsignal_source,
                    csvsignal_inline: signal.value.csvsignal_inline,
                }),
                'type': "str",
            }),
            symbol_list: JSON.stringify({ 'value': normalizedSymbolList, 'type': "str" }),
            filter: JSON.stringify({ 'value': { 'rsi_max': filter.value.rsi || false, 'marketcap_cmc_api_key': filter.value.cmc_api_key || false }, 'type': "str" }),
            rsi_max: JSON.stringify({ 'value': filter.value.rsi ?? false, 'type': "float" }),
            marketcap_cmc_api_key: JSON.stringify({ 'value': filter.value.cmc_api_key || false, 'type': "str" }),
            volume: JSON.stringify({ 'value': buildVolumeConfig(filter.value.volume), 'type': "str" }),
            pair_denylist: JSON.stringify({ 'value': normalizedDenyList, 'type': "str" }),
            topcoin_limit: JSON.stringify({ 'value': filter.value.topcoin_limit || false, 'type': "int" }),
            btc_pulse: JSON.stringify({ 'value': filter.value.btc_pulse || false, 'type': "bool" }),
            exchange: JSON.stringify({ 'value': exchange.value.name || false, 'type': "str" }),
            timeframe: JSON.stringify({ 'value': exchange.value.timeframe || false, 'type': "str" }),
            key: JSON.stringify({ 'value': exchange.value.key || false, 'type': "str" }),
            secret: JSON.stringify({ 'value': exchange.value.secret || false, 'type': "str" }),
            exchange_hostname: JSON.stringify({ 'value': showAdvancedGeneral.value ? (exchange.value.exchange_hostname || false) : false, 'type': "str" }),
            dry_run: JSON.stringify({ 'value': exchange.value.dry_run || false, 'type': "bool" }),
            currency: JSON.stringify({ 'value': exchange.value.currency || false, 'type': "str" }),
            market: JSON.stringify({ 'value': exchange.value.market || false, 'type': "str" }),
            watcher_ohlcv: JSON.stringify({ 'value': exchange.value.watcher_ohlcv || false, 'type': "bool" }),
            dca: JSON.stringify({ 'value': dca.value.enabled || false, 'type': "bool" }),
            dynamic_dca: JSON.stringify({ 'value': dca.value.dynamic || false, 'type': "bool" }),
            dca_strategy: JSON.stringify({ 'value': dca.value.strategy || false, 'type': "str" }),
            trailing_tp: JSON.stringify({ 'value': dca.value.trailing_tp || false, 'type': "float" }),
            max_bots: JSON.stringify({ 'value': dca.value.max_bots || false, 'type': "int" }),
            bo: JSON.stringify({ 'value': dca.value.bo || false, 'type': "int" }),
            sell_order_type: JSON.stringify({ 'value': dca.value.sell_order_type || 'market', 'type': "str" }),
            limit_sell_timeout_sec: JSON.stringify({ 'value': dca.value.limit_sell_timeout_sec ?? 60, 'type': "int" }),
            limit_sell_fallback_to_market: JSON.stringify({ 'value': dca.value.limit_sell_fallback_to_market ?? true, 'type': "bool" }),
            so: JSON.stringify({ 'value': dca.value.so || false, 'type': "int" }),
            mstc: JSON.stringify({ 'value': dca.value.mstc || false, 'type': "int" }),
            sos: JSON.stringify({ 'value': dca.value.sos || false, 'type': "float" }),
            ss: JSON.stringify({ 'value': dca.value.ss || false, 'type': "float" }),
            os: JSON.stringify({ 'value': dca.value.dynamic ? false : (dca.value.os || false), 'type': "float" }),
            trade_safety_order_budget_ratio: JSON.stringify({ 'value': dca.value.trade_safety_order_budget_ratio ?? 0.95, 'type': "float" }),
            tp: JSON.stringify({ 'value': dca.value.tp || false, 'type': "float" }),
            sl: JSON.stringify({ 'value': dca.value.sl || false, 'type': "float" }),
            autopilot: JSON.stringify({ 'value': autopilot.value.enabled || false, 'type': "bool" }),
            autopilot_max_fund: JSON.stringify({ 'value': autopilot.value.max_fund || false, 'type': "int" }),
            autopilot_high_mad: JSON.stringify({ 'value': autopilot.value.high_mad || false, 'type': "int" }),
            autopilot_high_tp: JSON.stringify({ 'value': autopilot.value.high_tp || false, 'type': "float" }),
            autopilot_high_sl: JSON.stringify({ 'value': autopilot.value.high_sl || false, 'type': "float" }),
            autopilot_high_sl_timeout: JSON.stringify({ 'value': autopilot.value.high_sl_timeout || false, 'type': "int" }),
            autopilot_high_threshold: JSON.stringify({ 'value': autopilot.value.high_threshold || false, 'type': "int" }),
            autopilot_medium_mad: JSON.stringify({ 'value': autopilot.value.medium_mad || false, 'type': "int" }),
            autopilot_medium_tp: JSON.stringify({ 'value': autopilot.value.medium_tp || false, 'type': "float" }),
            autopilot_medium_sl: JSON.stringify({ 'value': autopilot.value.medium_sl || false, 'type': "float" }),
            autopilot_medium_sl_timeout: JSON.stringify({ 'value': autopilot.value.medium_sl_timeout || false, 'type': "int" }),
            autopilot_medium_threshold: JSON.stringify({ 'value': autopilot.value.medium_threshold || false, 'type': "int" }),
            monitoring_enabled: JSON.stringify({ 'value': monitoring.value.enabled || false, 'type': "bool" }),
            monitoring_telegram_api_id: JSON.stringify({ 'value': monitoring.value.telegram_api_id || false, 'type': "int" }),
            monitoring_telegram_api_hash: JSON.stringify({ 'value': monitoring.value.telegram_api_hash || false, 'type': "str" }),
            monitoring_telegram_bot_token: JSON.stringify({ 'value': monitoring.value.telegram_bot_token || false, 'type': "str" }),
            monitoring_telegram_chat_id: JSON.stringify({ 'value': monitoring.value.telegram_chat_id || false, 'type': "str" }),
            monitoring_timeout_sec: JSON.stringify({ 'value': monitoring.value.timeout_sec ?? 5, 'type': "int" }),
            monitoring_retry_count: JSON.stringify({ 'value': monitoring.value.retry_count ?? 1, 'type': "int" }),
            upnl_housekeeping_interval: JSON.stringify({ 'value': indicator.value.upnl_housekeeping_interval ?? false, 'type': "int" }),
            history_lookback_time: JSON.stringify({
                'value': indicator.value.history_lookback_time || getDefaultHistoryLookbackByTimeframe(exchange.value.timeframe),
                'type': "str"
            }),
        }

        // Assuming you have an API endpoint
        const response = await axios.post(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/config/multiple`, formData);

        if (response.status >= 200 && response.status < 300) {
            syncBaselineState()
            saveState.value = 'saved'
            saveErrorMessage.value = null
            lastSavedAt.value = new Date()
            trackUiEvent('config_submit_success', {
                status_code: response.status,
                duration_ms: Math.round(performance.now() - submitStartedAt),
                dirty_sections: dirtySectionsBeforeSubmit,
            })
            message.success('Form submitted successfully')
            setTimeout(() => {
                router.push('/')
            }, 250)
        } else {
            setSaveError('An unexpected error occurred while submitting the configuration.')
            trackUiEvent('config_submit_error', {
                status_code: response.status,
                duration_ms: Math.round(performance.now() - submitStartedAt),
                category: 'non_2xx_response',
            })
            let errorMessage = 'An unexpected error occurred'
            try {
                errorMessage = response.data.message || JSON.stringify(response.data);
            } catch (e) {
                console.error('Error parsing error message:', e)
            }
            setSaveError(errorMessage)
            message.error(errorMessage)
        }
    } catch (error) {
        if (error.response) {
            trackUiEvent('config_submit_error', {
                status_code: error.response.status || null,
                duration_ms: Math.round(performance.now() - submitStartedAt),
                category: 'exception_response',
            })
            // Server responded with a status other than 2xx
            let errorMessage = 'An unexpected error occurred'
            try {
                errorMessage = error.response.data.message || JSON.stringify(error.response.data);
            } catch (e) {
                console.error('Error parsing error message:', e)
            }
            setSaveError(errorMessage)
            message.error(errorMessage)
        } else if (error.request) {
            trackUiEvent('config_submit_error', {
                status_code: null,
                duration_ms: Math.round(performance.now() - submitStartedAt),
                category: 'no_response',
            })
            // No response was received
            setSaveError('No response from server. Please try again later.')
            message.error('No response from server. Please try again later.')
        } else {
            trackUiEvent('config_submit_error', {
                status_code: null,
                duration_ms: Math.round(performance.now() - submitStartedAt),
                category: 'request_setup',
            })
            // Something happened while setting up the request
            setSaveError(`Request failed: ${error.message}`)
            message.error(`Request failed: ${error.message}`)
        }
    }
}

function canTestMonitoringTelegram(): boolean {
    return Boolean(
        monitoring.value.telegram_api_id &&
        monitoring.value.telegram_api_hash &&
        monitoring.value.telegram_bot_token &&
        monitoring.value.telegram_chat_id
    )
}

async function testMonitoringTelegram() {
    if (!canTestMonitoringTelegram()) {
        message.error('Please add valid Telegram settings first.')
        return
    }

    monitoring_test_loading.value = true
    try {
        const response = await axios.post(
            `http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/monitoring/test`,
            {
                monitoring_telegram_api_id: monitoring.value.telegram_api_id,
                monitoring_telegram_api_hash: monitoring.value.telegram_api_hash,
                monitoring_telegram_bot_token: monitoring.value.telegram_bot_token,
                monitoring_telegram_chat_id: monitoring.value.telegram_chat_id,
                monitoring_timeout_sec: monitoring.value.timeout_sec ?? 5,
                monitoring_retry_count: monitoring.value.retry_count ?? 1,
            },
        )
        message.success(response.data?.message || 'Monitoring Telegram test sent.')
    } catch (error) {
        if (error.response) {
            message.error(error.response.data?.error || 'Monitoring Telegram test failed.')
        } else if (error.request) {
            message.error('No response from server. Please try again later.')
        } else {
            message.error(`Request failed: ${error.message}`)
        }
    } finally {
        monitoring_test_loading.value = false
    }
}

function validateAndSubmit(): void {
    submitAttempted.value = true
    const forms = [
        generalFormRef.value,
        signalFormRef.value,
        filterFormRef.value,
        exchangeFormRef.value,
        dcaFormRef.value,
        autopilotFormRef.value,
        monitoringFormRef.value,
        indicatorFormRef.value,
    ].filter((form): form is FormInst => form !== null)

    const validations = forms.map(
        (form) =>
            new Promise<boolean>((resolve) => {
                form.validate((errors) => resolve(!errors))
            }),
    )

    Promise.all(validations).then((results) => {
        if (results.every(Boolean)) {
            trackUiEvent('config_validation_success')
            submitForm()
        } else {
            setSaveError('Missing/invalid configuration input')
            trackUiEvent('config_validation_failed')
            message.error('Missing/invalid configuration input')
        }
    })
}

function handleValidateButtonClick(e: MouseEvent) {
    e.preventDefault()
    validateAndSubmit()
}

function handleGlobalKeydown(event: KeyboardEvent): void {
    const key = event.key.toLowerCase()
    if ((event.ctrlKey || event.metaKey) && key === 's') {
        event.preventDefault()
        trackUiEvent('config_submit_shortcut_used')
        validateAndSubmit()
    }
}

watch(
    () => showAdvancedGeneral.value,
    (enabled) => {
        if (isLoading.value) {
            return
        }
        localStorage.setItem(ADVANCED_GENERAL_PREFERENCE_KEY, enabled ? 'true' : 'false')
        if (!enabled) {
            resetAdvancedGeneralSettings()
        }
    },
)

watch(
    () => signal.value.asap_use_url,
    async (useUrl) => {
        if (isLoading.value) {
            return
        }
        if (signal.value.signal !== "asap") {
            return
        }
        if (useUrl) {
            signal.value.asap_symbol_select = []
            signal.value.asap_symbol_options = []
            signal.value.asap_symbol_fetch_error = null
            if (!isUrlInput(signal.value.symbol_list)) {
                signal.value.symbol_list = null
            }
            return
        }
        signal.value.asap_symbol_options = []
        signal.value.asap_symbol_fetch_error = null
    },
)

watch(
    () => [exchange.value.currency, exchange.value.name, exchange.value.key, exchange.value.secret, exchange.value.exchange_hostname],
    async () => {
        if (isLoading.value) {
            return
        }
        if (signal.value.signal === "asap" && !signal.value.asap_use_url) {
            signal.value.asap_symbol_options = []
            signal.value.asap_symbol_select = []
            signal.value.asap_symbol_fetch_error = null
        }
    },
)

watch(
    () => signal.value.asap_symbol_select,
    (selectedSymbol) => {
        if (signal.value.signal === "asap" && !signal.value.asap_use_url) {
            if (Array.isArray(selectedSymbol)) {
                signal.value.symbol_list = selectedSymbol.join(",")
            } else {
                signal.value.symbol_list = null
            }
        }
    },
)

onBeforeRouteLeave(() => confirmDiscardUnsavedChanges('route_leave'))

onMounted(() => {
    timezone.value = getAllTimeZones()
    const clientTimezone = getClientTimezone()
    if (!timezone.value.some((tz) => tz.value === clientTimezone)) {
        timezone.value.unshift({ label: clientTimezone, value: clientTimezone })
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    window.addEventListener('keydown', handleGlobalKeydown)
    void fetchDefaultValues()
})

onUnmounted(() => {
    window.removeEventListener('beforeunload', handleBeforeUnload)
    window.removeEventListener('keydown', handleGlobalKeydown)
})

</script>

<style scoped>
.config-form-shell {
    display: flex;
    flex-direction: column;
    gap: 16px;
    width: 100%;
}

@media (max-width: 768px) {
    .submit-button {
        width: 100%;
    }
}
</style>
