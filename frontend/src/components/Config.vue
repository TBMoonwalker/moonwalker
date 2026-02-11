<template>
    <n-flex vertical :style="{ display: 'flex', flexDirection: 'column', gap: '16px', width: '98%' }">
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

                <!-- Dynamic check for Strategy settings -->
                <n-form-item label="Signal initial buy strategy" path="selectValue" label-placement="left">
                    <n-checkbox v-model:checked="signal.strategy_enabled" @change="handle_signal_strategy_select" />
                </n-form-item>
                <template v-for="(index) in dynamicSignalStrategyForm" :key="index">
                    <n-form-item :label="'Strategy'" :path="'strategy.' + index">
                        <n-select v-model:value="signal.strategy" placeholder="Select"
                            :options="signal.strategy_plugins" />
                    </n-form-item>
                    <n-form-item label="Timerange" :path="'timerange.' + index">
                        <n-select v-model:value="signal.timeframe" placeholder="Select" :options="timerange" />
                    </n-form-item>
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
                        <n-form-item label="Timerange" :path="'timerange.' + index">
                            <n-select v-model:value="dca.timeframe" placeholder="Select" :options="timerange" />
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
                <n-form-item v-if="dca.enabled" label="Safety order amount" path="so">
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
                <n-form-item v-if="dca.enabled && !dca.dynamic_so_volume_enabled" label="Safety order volume scale" path="os">
                    <n-input-number v-model:value="dca.os" placeholder="OS" />
                </n-form-item>
                <n-form-item label="Stop loss percentage" path="sl">
                    <n-input-number v-model:value="dca.sl" placeholder="SL" />
                </n-form-item>
                <n-form-item v-if="dca.enabled" label="Dynamic SO volume scaling" path="dynamic_so_volume_enabled" label-placement="left">
                    <n-checkbox v-model:checked="dca.dynamic_so_volume_enabled" />
                </n-form-item>
                <template v-if="dca.enabled && dca.dynamic_so_volume_enabled">
                    <n-form-item label="ATH lookback value" path="dynamic_so_ath_lookback_value">
                        <n-input-number v-model:value="dca.dynamic_so_ath_lookback_value" placeholder="1" />
                    </n-form-item>
                    <n-form-item label="ATH lookback unit" path="dynamic_so_ath_lookback_unit">
                        <n-select v-model:value="dca.dynamic_so_ath_lookback_unit" placeholder="Select" :options="dynamicSoLookbackUnitOptions" />
                    </n-form-item>
                    <n-form-item label="ATH candle timeframe" path="dynamic_so_ath_timeframe">
                        <n-select v-model:value="dca.dynamic_so_ath_timeframe" placeholder="Select" :options="dynamicSoAthTimeframeOptions" />
                    </n-form-item>
                    <n-form-item label="ATH cache TTL (sec)" path="dynamic_so_ath_cache_ttl">
                        <n-input-number v-model:value="dca.dynamic_so_ath_cache_ttl" placeholder="60" />
                    </n-form-item>
                    <n-form-item label="Loss weight" path="dynamic_so_loss_weight">
                        <n-input-number v-model:value="dca.dynamic_so_loss_weight" placeholder="0.5" />
                    </n-form-item>
                    <n-form-item label="ATH drawdown weight" path="dynamic_so_drawdown_weight">
                        <n-input-number v-model:value="dca.dynamic_so_drawdown_weight" placeholder="0.8" />
                    </n-form-item>
                    <n-form-item label="Curve exponent" path="dynamic_so_exponent">
                        <n-input-number v-model:value="dca.dynamic_so_exponent" placeholder="1.1" />
                    </n-form-item>
                    <n-form-item label="Dynamic min scale" path="dynamic_so_min_scale">
                        <n-input-number v-model:value="dca.dynamic_so_min_scale" placeholder="0.5" />
                    </n-form-item>
                    <n-form-item label="Dynamic max scale" path="dynamic_so_max_scale">
                        <n-input-number v-model:value="dca.dynamic_so_max_scale" placeholder="3.0" />
                    </n-form-item>
                </template>
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

        <n-card title="Indicator settings">
            <n-form ref="indicatorFormRef" :model="indicator" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="Housekeeping interval (in days)" path="housekeeping_interval">
                    <n-input-number v-model:value="indicator.housekeeping_interval" placeholder="Interval" />
                </n-form-item>
                <n-form-item label="UPNL history retention (days, 0 = infinite)" path="upnl_housekeeping_interval">
                    <n-input-number v-model:value="indicator.upnl_housekeeping_interval"
                        placeholder="UPNL retention" />
                </n-form-item>
                <n-form-item label="History from data (in days)" path="history_from_data">
                    <n-input-number v-model:value="indicator.history_from_data" placeholder="History" />
                </n-form-item>
            </n-form>
        </n-card>

        <n-button round type="primary" @click="handleValidateButtonClick">
            Submit
        </n-button>
    </n-flex>

</template>

<script setup lang="ts">
import { MOONWALKER_API_PORT, MOONWALKER_API_HOST } from '../config'
import { getAllTimeZones } from '../helpers/timezone'
import { parseBooleanString, isJsonString, toNumberOrNull } from '../helpers/validators'
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NFlex,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSwitch,
  type FormInst,
  type FormItemRule,
  type FormRules,
  useMessage
} from 'naive-ui'
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

interface dynamicSelectItem {
    value: string | null;
}

function getClientTimezone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
}

// Signal strategy
const dynamicSignalStrategyForm = ref<dynamicSelectItem[]>([])
const dynamicSymSignalSettingsForm = ref<dynamicSelectItem[]>([])
const dynamicAsapSignalSettingsForm = ref<dynamicSelectItem[]>([])
const dynamicDCAForm = ref<dynamicSelectItem[]>([])
const DCAForm = ref<dynamicSelectItem[]>([])
const APForm = ref<dynamicSelectItem[]>([])
const generalFormRef = ref<FormInst | null>(null)
const signalFormRef = ref<FormInst | null>(null)
const filterFormRef = ref<FormInst | null>(null)
const exchangeFormRef = ref<FormInst | null>(null)
const dcaFormRef = ref<FormInst | null>(null)
const autopilotFormRef = ref<FormInst | null>(null)
const indicatorFormRef = ref<FormInst | null>(null)
const message = useMessage()
const router = useRouter()
const isLoading = ref(true)
const submitAttempted = ref(false)
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

const dynamicSoLookbackUnitOptions = [
    { label: 'Day', value: 'day' },
    { label: 'Week', value: 'week' },
    { label: 'Month', value: 'month' },
    { label: 'Year', value: 'year' },
]

const dynamicSoAthTimeframeOptions = [
    { label: '4 hours (4h)', value: '4h' },
    { label: '1 day (1d)', value: '1d' },
    { label: '1 week (1w)', value: '1w' },
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
    so: null,
    mstc: null,
    sos: null,
    ss: null,
    os: null,
    dynamic_so_volume_enabled: false,
    dynamic_so_ath_lookback_value: 1,
    dynamic_so_ath_lookback_unit: 'month',
    dynamic_so_ath_timeframe: '4h',
    dynamic_so_ath_window: '1m',
    dynamic_so_loss_weight: 0.5,
    dynamic_so_drawdown_weight: 0.8,
    dynamic_so_exponent: 1.1,
    dynamic_so_min_scale: 0.5,
    dynamic_so_max_scale: 3.0,
    dynamic_so_ath_cache_ttl: 60,
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

const indicator = ref({
    housekeeping_interval: null,
    upnl_housekeeping_interval: 0,
    history_from_data: null,
})

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

function parseSymbolListToArray(raw: string | null): string[] {
    if (!raw) {
        return []
    }
    return raw
        .split(/[\n,]+/)
        .map((entry) => entry.trim().replace(/^['"]|['"]$/g, ""))
        .filter((entry) => entry.length > 0)
}

function parseStructuredConfigValue(raw: unknown): Record<string, unknown> | null {
    if (!raw) {
        return null
    }

    if (typeof raw === 'object') {
        return raw as Record<string, unknown>
    }

    if (typeof raw !== 'string') {
        return null
    }

    const normalized = raw
        .replace(/'/g, '"')
        .replace(/\bTrue\b/g, 'true')
        .replace(/\bFalse\b/g, 'false')
        .replace(/\bNone\b/g, 'null')

    try {
        return JSON.parse(normalized) as Record<string, unknown>
    } catch (error) {
        console.error('Failed to parse structured config value:', error, raw)
        return null
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
        validator: dcaFieldValidator('safety order amount'),
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
            () => !dca.value.dynamic_so_volume_enabled,
        ),
        trigger: ['submit'],
    },
    tp: {
        validator: requiredAfterSubmit('Please add tp'),
        trigger: ['submit', 'change']
    },
    housekeeping_interval: {
        validator: requiredAfterSubmit('Please add housekeeping interval'),
        trigger: ['submit', 'change']
    },
    upnl_housekeeping_interval: {
        validator: requiredAfterSubmit('Please add UPNL history retention'),
        trigger: ['submit', 'change']
    },
    history_from_data: {
        validator: requiredAfterSubmit('Please add history from data'),
        trigger: ['submit', 'change']
    },
}

function handle_signal_strategy_select() {
    if (signal.value.strategy && signal.value.strategy_enabled === true) {
        // Add a new select item when activated
        dynamicSignalStrategyForm.value.push({ value: null })
    } else {
        // Remove the last select item when deactivated
        dynamicSignalStrategyForm.value.pop()
    }
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
        dynamicAsapSignalSettingsForm.value.pop()
    } else if (signal.value.signal == "asap") {
        if (dynamicAsapSignalSettingsForm.value.length === 0) {
            dynamicAsapSignalSettingsForm.value.push({ value: null })
        }
        dynamicSymSignalSettingsForm.value.pop()
        if (!signal.value.asap_use_url) {
            void fetchAsapSymbolsForCurrency()
        }
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

async function fetchDefaultValues() {
    try {
        const response = await axios.get(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/config/all`);
        if (response.status === 200) {
            general.value.timezone = response.data.timezone || getClientTimezone()
            general.value.debug = parseBooleanString(response.data.debug) ?? false
            signal.value.signal = response.data.signal
            signal.value.strategy = response.data.signal_strategy
            signal.value.timeframe = response.data.signal_strategy_timeframe
            const signalSettings = parseStructuredConfigValue(response.data.signal_settings)
            if (signalSettings) {
                signal.value.symsignal_url = String(signalSettings["api_url"] || DEFAULT_SYMSIGNAL_URL)
                signal.value.symsignal_key = String(signalSettings["api_key"] || "")
                signal.value.symsignal_version = String(signalSettings["api_version"] || DEFAULT_SYMSIGNAL_VERSION)
                const allowedSignals = signalSettings["allowed_signals"]
                signal.value.symsignal_allowedsignals = Array.isArray(allowedSignals) ? allowedSignals : []
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
            var filter_indicator = response.data.filter
            if (filter_indicator) {
                filter.value.rsi = response.data.filter.rsi_max
                filter.value.cmc_api_key = response.data.filter.marketcap_cmc_api_key
            }
            filter.value.denylist = toTokenOnlyEntries(response.data.pair_denylist)
            filter.value.topcoin_limit = response.data.topcoin_limit
            filter.value.btc_pulse = parseBooleanString(response.data.btc_pulse) ?? false
            exchange.value.name = response.data.exchange
            exchange.value.timeframe = response.data.timeframe
            exchange.value.key = response.data.key
            exchange.value.secret = response.data.secret
            exchange.value.dry_run = parseBooleanString(response.data.dry_run) ?? true
            exchange.value.currency = response.data.currency
            exchange.value.market = response.data.market || "spot"
            exchange.value.watcher_ohlcv = parseBooleanString(response.data.watcher_ohlcv) ?? false
            dca.value.enabled = parseBooleanString(response.data.dca) ?? false
            dca.value.dynamic = parseBooleanString(response.data.dynamic_dca) ?? false
            dca.value.strategy = response.data.dca_strategy
            dca.value.timeframe = response.data.dca_strategy_timeframe
            dca.value.trailing_tp = toNumberOrNull(response.data.trailing_tp)
            dca.value.max_bots = toNumberOrNull(response.data.max_bots)
            dca.value.bo = toNumberOrNull(response.data.bo)
            dca.value.so = toNumberOrNull(response.data.so)
            dca.value.mstc = toNumberOrNull(response.data.mstc)
            dca.value.sos = toNumberOrNull(response.data.sos)
            dca.value.ss = toNumberOrNull(response.data.ss)
            dca.value.os = toNumberOrNull(response.data.os)
            dca.value.dynamic_so_volume_enabled =
                parseBooleanString(response.data.dynamic_so_volume_enabled) ?? false
            dca.value.dynamic_so_ath_lookback_value =
                toNumberOrNull(response.data.dynamic_so_ath_lookback_value) ?? 1
            dca.value.dynamic_so_ath_lookback_unit =
                response.data.dynamic_so_ath_lookback_unit || 'month'
            dca.value.dynamic_so_ath_timeframe =
                response.data.dynamic_so_ath_timeframe || '4h'
            dca.value.dynamic_so_ath_window = response.data.dynamic_so_ath_window || '1m'
            dca.value.dynamic_so_loss_weight =
                toNumberOrNull(response.data.dynamic_so_loss_weight) ?? 0.5
            dca.value.dynamic_so_drawdown_weight =
                toNumberOrNull(response.data.dynamic_so_drawdown_weight) ?? 0.8
            dca.value.dynamic_so_exponent =
                toNumberOrNull(response.data.dynamic_so_exponent) ?? 1.1
            dca.value.dynamic_so_min_scale =
                toNumberOrNull(response.data.dynamic_so_min_scale) ?? 0.5
            dca.value.dynamic_so_max_scale =
                toNumberOrNull(response.data.dynamic_so_max_scale) ?? 3.0
            dca.value.dynamic_so_ath_cache_ttl =
                toNumberOrNull(response.data.dynamic_so_ath_cache_ttl) ?? 60
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
            indicator.value.housekeeping_interval = toNumberOrNull(response.data.housekeeping_interval)
            indicator.value.upnl_housekeeping_interval = toNumberOrNull(response.data.upnl_housekeeping_interval) ?? 0
            indicator.value.history_from_data = toNumberOrNull(response.data.history_from_data)

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
                dynamicSignalStrategyForm.value.push({ value: signal.value.strategy })
            }

            // Initial call for signal settings
            handle_signal_settings_select()
            handle_dca_select()
            handle_dynamic_dca_select()
            if (signal.value.signal === "asap" && !signal.value.asap_use_url) {
                await fetchAsapSymbolsForCurrency()
            }

        } else {
            message.error('Failed to load default values')
        }
    } catch (error) {
        console.error('Error fetching default values:', error);
        message.error('An unexpected error occurred while loading default values.')
    } finally {
        isLoading.value = false; // Set loading state to false after fetch
    }
}

function splitEntries(raw: string): string[] {
    return raw
        .split(/[\n,]+/)
        .map((entry) => entry.trim().replace(/^['"]|['"]$/g, ""))
        .filter((entry) => entry.length > 0)
}

function toTokenOnlyEntries(raw: string | null): string | null {
    if (!raw) {
        return raw
    }

    const normalizedRaw = raw.trim()
    if (!normalizedRaw || /^https?:\/\//i.test(normalizedRaw)) {
        return raw
    }

    const entries = splitEntries(normalizedRaw)
    if (entries.length === 0) {
        return raw
    }

    const tokens = entries.map((entry) =>
        entry.toUpperCase().replace("-", "/").split("/")[0]
    )
    return tokens.join(",")
}

function normalizePairEntries(raw: string | null, quoteCurrency: string): string | false {
    if (!raw) {
        return false
    }

    const normalizedRaw = raw.trim()
    if (!normalizedRaw) {
        return false
    }

    if (/^https?:\/\//i.test(normalizedRaw)) {
        return normalizedRaw
    }

    const entries = splitEntries(normalizedRaw)
    if (entries.length === 0) {
        return false
    }

    const quote = quoteCurrency.toUpperCase()
    const pairs = entries.map((entry) => {
        const normalizedEntry = entry.toUpperCase().replace("-", "/")
        if (normalizedEntry.includes("/")) {
            const [base, q] = normalizedEntry.split("/")
            if (base && q) {
                return `${base}/${q}`
            }
            return `${base}/${quote}`
        }
        return `${normalizedEntry}/${quote}`
    })

    return pairs.join(",")
}

async function submitForm() {
    try {
        const quoteCurrency = String(exchange.value.currency || "USDT").toUpperCase()
        const asapInputValue = signal.value.asap_use_url
            ? signal.value.symbol_list
            : signal.value.asap_symbol_select.join(",")
        const normalizedSymbolList = normalizePairEntries(
            asapInputValue,
            quoteCurrency,
        )
        const normalizedDenyList = normalizePairEntries(
            filter.value.denylist,
            quoteCurrency,
        )

        const formData = {
            timezone: JSON.stringify({ 'value': general.value.timezone || false, 'type': "str" }),
            debug: JSON.stringify({ 'value': general.value.debug || false, 'type': "bool" }),
            signal: JSON.stringify({ 'value': signal.value.signal || false, 'type': "str" }),
            signal_strategy: JSON.stringify({ 'value': dynamicSignalStrategyForm.value.length > 0 ? dynamicSignalStrategyForm.value.map(item => item.value).join(', ') : false, 'type': "str" }),
            signal_strategy_timeframe: JSON.stringify({ 'value': signal.value.timeframe || false, 'type': "str" }),
            signal_settings: JSON.stringify({ 'value': { 'api_url': signal.value.symsignal_url || false, 'api_key': signal.value.symsignal_key || false, 'api_version': signal.value.symsignal_version || false, 'allowed_signals': signal.value.symsignal_allowedsignals }, 'type': "str" }),
            symbol_list: JSON.stringify({ 'value': normalizedSymbolList, 'type': "str" }),
            filter: JSON.stringify({ 'value': { 'rsi_max': filter.value.rsi || false, 'marketcap_cmc_api_key': filter.value.cmc_api_key || false }, 'type': "str" }),
            pair_denylist: JSON.stringify({ 'value': normalizedDenyList, 'type': "str" }),
            topcoin_limit: JSON.stringify({ 'value': filter.value.topcoin_limit || false, 'type': "int" }),
            btc_pulse: JSON.stringify({ 'value': filter.value.btc_pulse || false, 'type': "bool" }),
            exchange: JSON.stringify({ 'value': exchange.value.name || false, 'type': "str" }),
            timeframe: JSON.stringify({ 'value': exchange.value.timeframe || false, 'type': "str" }),
            key: JSON.stringify({ 'value': exchange.value.key || false, 'type': "str" }),
            secret: JSON.stringify({ 'value': exchange.value.secret || false, 'type': "str" }),
            dry_run: JSON.stringify({ 'value': exchange.value.dry_run || false, 'type': "bool" }),
            currency: JSON.stringify({ 'value': exchange.value.currency || false, 'type': "str" }),
            market: JSON.stringify({ 'value': exchange.value.market || false, 'type': "str" }),
            watcher_ohlcv: JSON.stringify({ 'value': exchange.value.watcher_ohlcv || false, 'type': "bool" }),
            dca: JSON.stringify({ 'value': dca.value.enabled || false, 'type': "bool" }),
            dynamic_dca: JSON.stringify({ 'value': dca.value.dynamic || false, 'type': "bool" }),
            dca_strategy: JSON.stringify({ 'value': dca.value.strategy || false, 'type': "str" }),
            dca_strategy_timeframe: JSON.stringify({ 'value': dca.value.timeframe || false, 'type': "str" }),
            trailing_tp: JSON.stringify({ 'value': dca.value.trailing_tp || false, 'type': "float" }),
            max_bots: JSON.stringify({ 'value': dca.value.max_bots || false, 'type': "int" }),
            bo: JSON.stringify({ 'value': dca.value.bo || false, 'type': "int" }),
            so: JSON.stringify({ 'value': dca.value.so || false, 'type': "int" }),
            mstc: JSON.stringify({ 'value': dca.value.mstc || false, 'type': "int" }),
            sos: JSON.stringify({ 'value': dca.value.sos || false, 'type': "float" }),
            ss: JSON.stringify({ 'value': dca.value.ss || false, 'type': "float" }),
            os: JSON.stringify({ 'value': dca.value.os || false, 'type': "float" }),
            dynamic_so_volume_enabled: JSON.stringify({ 'value': dca.value.dynamic_so_volume_enabled || false, 'type': "bool" }),
            dynamic_so_ath_lookback_value: JSON.stringify({ 'value': dca.value.dynamic_so_ath_lookback_value ?? 1, 'type': "int" }),
            dynamic_so_ath_lookback_unit: JSON.stringify({ 'value': dca.value.dynamic_so_ath_lookback_unit || 'month', 'type': "str" }),
            dynamic_so_ath_timeframe: JSON.stringify({ 'value': dca.value.dynamic_so_ath_timeframe || '4h', 'type': "str" }),
            dynamic_so_ath_window: JSON.stringify({ 'value': dca.value.dynamic_so_ath_window || '1m', 'type': "str" }),
            dynamic_so_loss_weight: JSON.stringify({ 'value': dca.value.dynamic_so_loss_weight ?? 0.5, 'type': "float" }),
            dynamic_so_drawdown_weight: JSON.stringify({ 'value': dca.value.dynamic_so_drawdown_weight ?? 0.8, 'type': "float" }),
            dynamic_so_exponent: JSON.stringify({ 'value': dca.value.dynamic_so_exponent ?? 1.1, 'type': "float" }),
            dynamic_so_min_scale: JSON.stringify({ 'value': dca.value.dynamic_so_min_scale ?? 0.5, 'type': "float" }),
            dynamic_so_max_scale: JSON.stringify({ 'value': dca.value.dynamic_so_max_scale ?? 3.0, 'type': "float" }),
            dynamic_so_ath_cache_ttl: JSON.stringify({ 'value': dca.value.dynamic_so_ath_cache_ttl ?? 60, 'type': "int" }),
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
            housekeeping_interval: JSON.stringify({ 'value': indicator.value.housekeeping_interval || false, 'type': "int" }),
            upnl_housekeeping_interval: JSON.stringify({ 'value': indicator.value.upnl_housekeeping_interval ?? false, 'type': "int" }),
            history_from_data: JSON.stringify({ 'value': indicator.value.history_from_data || false, 'type': "int" }),
        }
        console.log(formData)

        // Assuming you have an API endpoint
        const response = await axios.post(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/config/multiple`, formData);

        if (response.status === 200) {
            message.success('Form submitted successfully')
            setTimeout(() => {
                router.push('/')
            }, 250)
        } else {
            let errorMessage = 'An unexpected error occurred'
            try {
                errorMessage = response.data.message || JSON.stringify(response.data);
            } catch (e) {
                console.error('Error parsing error message:', e)
            }
            message.error(errorMessage)
        }
    } catch (error) {
        if (error.response) {
            // Server responded with a status other than 2xx
            let errorMessage = 'An unexpected error occurred'
            try {
                errorMessage = error.response.data.message || JSON.stringify(error.response.data);
            } catch (e) {
                console.error('Error parsing error message:', e)
            }
            message.error(errorMessage)
        } else if (error.request) {
            // No response was received
            message.error('No response from server. Please try again later.')
        } else {
            // Something happened while setting up the request
            message.error(`Request failed: ${error.message}`)
        }
    }
}

function handleValidateButtonClick(e: MouseEvent) {
    e.preventDefault()
    submitAttempted.value = true
    const forms = [
        generalFormRef.value,
        signalFormRef.value,
        filterFormRef.value,
        exchangeFormRef.value,
        dcaFormRef.value,
        autopilotFormRef.value,
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
            submitForm()
        } else {
            message.error('Missing/invalid configuration input')
        }
    })
}

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
    () => [exchange.value.currency, exchange.value.name, exchange.value.key, exchange.value.secret],
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

onMounted(() => {
    timezone.value = getAllTimeZones()
    const clientTimezone = getClientTimezone()
    if (!timezone.value.some((tz) => tz.value === clientTimezone)) {
        timezone.value.unshift({ label: clientTimezone, value: clientTimezone })
    }
    fetchDefaultValues(); // Fetch default values when component is mounted
});

</script>
