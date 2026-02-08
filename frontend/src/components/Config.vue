<template>
    <n-flex vertical :style="{ display: 'flex', flexDirection: 'column', gap: '16px', width: '98%' }">
        <n-card title="General settings">
            <n-form ref="formRef" :model="general" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="Timezone" path="timezone">
                    <n-select v-model:value="general.timezone" placeholder="Select" :options="timezone" />
                </n-form-item>
                <n-form-item label="Debug mode" path="debug" label-placement="left">
                    <n-checkbox v-model:checked="general.debug" />
                </n-form-item>
            </n-form>
        </n-card>

        <n-card title=" Signal settings">
            <n-form ref="formRef" :model="signal" :rules="rules" label-width="auto"
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
                        <n-input v-model:value="signal.symsignal_key" placeholder="Key" />
                    </n-form-item>
                    <n-form-item :label="'Version'" :path="'version.' + index">
                        <n-input v-model:value="signal.symsignal_version" placeholder="Version" />
                    </n-form-item>
                    <n-form-item label="Allowed Signals" path="signals">
                        <n-select v-model:value="signal.symsignal_allowedsignals" placeholder="Select"
                            :options="symsignals" multiple />
                    </n-form-item>
                </template>

                <!-- Dynamic check for ASAP Signal settings -->
                <template v-for="(index) in dynamicAsapSignalSettingsForm" :key="index">
                    <n-form-item label="Token/Coin List or URL" :path="'symbols.' + index">
                        <n-input v-model:value="signal.symbol_list" placeholder="Textarea" type="textarea" :autosize="{
                            minRows: 3,
                            maxRows: 5,
                        }" />
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
            <n-form ref="formRef" :model="filter" :rules="rules" label-width="auto"
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
                        <n-input-number v-model:value="filter.cmc_api_key" placeholder="CMC API Key" />
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
            <n-form ref="formRef" :model="exchange" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="Exchange" path="exchange">
                    <n-select v-model:value="exchange.name" placeholder="Select" :options="exchanges" />
                </n-form-item>
                <n-form-item label="Timerange" path="timerange">
                    <n-select v-model:value="exchange.timeframe" placeholder="Select" :options="timerange" />
                </n-form-item>
                <n-form-item label="Key" path="key">
                    <n-input v-model:value="exchange.key" placeholder="Exchange Key" />
                </n-form-item>
                <n-form-item label="Secret" path="secret">
                    <n-input v-model:value="exchange.secret" placeholder="Exchange Secret" />
                </n-form-item>
                <n-form-item label="Dry Run" path="dryrun" label-placement="left">
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
            <n-form ref="formRef" :model="dca" :rules="rules" label-width="auto" require-mark-placement="right-hanging"
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
                <n-form-item label="Max bots running" path="maxbots">
                    <n-input-number v-model:value="dca.max_bots" placeholder="Bot count" />
                </n-form-item>
                <n-form-item label="Base order amount" path="bo">
                    <n-input-number v-model:value="dca.bo" placeholder="BO" />
                </n-form-item>
                <n-form-item label="Safety order amount" path="so">
                    <n-input-number v-model:value="dca.so" placeholder="SO" />
                </n-form-item>
                <n-form-item label="Max safety order count" path="mstc">
                    <n-input-number v-model:value="dca.mstc" placeholder="MSTC" />
                </n-form-item>
                <n-form-item label="Price deviation for first safety order" path="sos">
                    <n-input-number v-model:value="dca.sos" placeholder="SOS" />
                </n-form-item>
                <n-form-item label="Safety order step scale" path="ss">
                    <n-input-number v-model:value="dca.ss" placeholder="SS" />
                </n-form-item>
                <n-form-item label="Safety order volume scale" path="os">
                    <n-input-number v-model:value="dca.os" placeholder="OS" />
                </n-form-item>
                <n-form-item label="Stop loss percentage" path="sl">
                    <n-input-number v-model:value="dca.sl" placeholder="SL" />
                </n-form-item>
            </n-form>
        </n-card>

        <n-card title="Autopilot settings">
            <n-form ref="formRef" :model="autopilot" :rules="rules" label-width="auto"
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
            <n-form ref="formRef" :model="indicator" :rules="rules" label-width="auto"
                require-mark-placement="right-hanging" :style="{
                    maxWidth: '640px',
                }">
                <n-form-item label="Housekeeping interval (in hours)" path="housekeeping_interval">
                    <n-input-number v-model:value="indicator.housekeeping_interval" placeholder="Interval" />
                </n-form-item>
                <n-form-item label="History from data (in days)" path="history">
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
  NButton,
  NCard,
  NCheckbox,
  NFlex,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  type FormInst,
  type FormItemRule,
  type FormRules,
  useMessage
} from 'naive-ui'
import { ref, onMounted } from 'vue'
import axios from 'axios'

interface dynamicSelectItem {
    value: string | null;
}

// Signal strategy
const dynamicSignalStrategyForm = ref<dynamicSelectItem[]>([])
const dynamicSymSignalSettingsForm = ref<dynamicSelectItem[]>([])
const dynamicAsapSignalSettingsForm = ref<dynamicSelectItem[]>([])
const dynamicDCAForm = ref<dynamicSelectItem[]>([])
const DCAForm = ref<dynamicSelectItem[]>([])
const APForm = ref<dynamicSelectItem[]>([])
const formRef = ref<FormInst | null>(null)
const message = useMessage()
const isLoading = ref(true)
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

const exchanges = [{
    label: 'Binance',
    value: 'binance'
}]

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
    {
        label: "SymSync50",
        value: 66,
    },
    {
        label: "SymSync60",
        value: 65,
    },
    {
        label: "SymSync70",
        value: 64,
    },
    {
        label: "SymSync80",
        value: 63,
    },
    {
        label: "SymSync90",
        value: 62,
    },
    {
        label: "SymSync100",
        value: 61,
    }
]

const general = ref({
    timezone: null,
    debug: false,
})

const signal = ref({
    symbol_list: null,
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
    history_from_data: null,
})

const rules: FormRules = {
    timezone: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please select timezone'
    },
    signal: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please select signal plugin'
    },
    signal_settings: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please configure signal'
    },
    symbol_list: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please add symbol list or remote list url'
    },
    exchange: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please select exchange'
    },
    timerange: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please select timeframe'
    },
    key: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please add key'
    },
    secret: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please add secret'
    },
    currency: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please select currency'
    },
    max_bots: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please add max bots'
    },
    bo: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please add bo'
    },
    so: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please add so'
    },
    sos: {
        required: true,
        trigger: ['blur', 'input'],
        message: 'Please input value'
    },
    tp: {
        required: true,
        trigger: ['blur', 'change'],
        message: 'Please add tp'
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
        dynamicAsapSignalSettingsForm.value.pop()
    } else if (signal.value.signal == "asap") {
        if (dynamicAsapSignalSettingsForm.value.length === 0) {
            dynamicAsapSignalSettingsForm.value.push({ value: null })
        }
        dynamicSymSignalSettingsForm.value.pop()
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
            general.value.timezone = response.data.timezone
            general.value.debug = parseBooleanString(response.data.debug) ?? false
            signal.value.signal = response.data.signal
            signal.value.strategy = response.data.signal_strategy
            signal.value.timeframe = response.data.signal_strategy_timeframe
            var signal_settings = response.data.signal_settings
            if (signal_settings) {
                // ToDo - fix incorrect single quote JSON
                signal_settings = JSON.parse(signal_settings.replace(/'/g, '"'))
                console.log(signal_settings)
                signal.value.symsignal_url = signal_settings["api_url"]
                signal.value.symsignal_key = signal_settings["api_key"]
                signal.value.symsignal_version = signal_settings["api_version"]
                signal.value.symsignal_allowedsignals = signal_settings["allowed_signals"]
            }
            signal.value.symbol_list = response.data.symbol_list
            var filter_indicator = response.data.filter
            if (filter_indicator) {
                filter.value.rsi = response.data.filter.rsi_max
                filter.value.cmc_api_key = response.data.filter.marketcap_cmc_api_key
            }
            filter.value.denylist = response.data.pair_denylist
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

async function submitForm() {
    try {
        const formData = {
            timezone: JSON.stringify({ 'value': general.value.timezone || false, 'type': "str" }),
            debug: JSON.stringify({ 'value': general.value.debug || false, 'type': "bool" }),
            signal: JSON.stringify({ 'value': signal.value.signal || false, 'type': "str" }),
            signal_strategy: JSON.stringify({ 'value': dynamicSignalStrategyForm.value.length > 0 ? dynamicSignalStrategyForm.value.map(item => item.value).join(', ') : false, 'type': "str" }),
            signal_strategy_timeframe: JSON.stringify({ 'value': signal.value.timeframe || false, 'type': "str" }),
            signal_settings: JSON.stringify({ 'value': { 'api_url': signal.value.symsignal_url || false, 'api_key': signal.value.symsignal_key || false, 'api_version': signal.value.symsignal_version || false, 'allowed_signals': signal.value.symsignal_allowedsignals }, 'type': "str" }),
            symbol_list: JSON.stringify({ 'value': signal.value.symbol_list || false, 'type': "str" }),
            filter: JSON.stringify({ 'value': { 'rsi_max': filter.value.rsi || false, 'marketcap_cmc_api_key': filter.value.cmc_api_key || false }, 'type': "str" }),
            pair_denylist: JSON.stringify({ 'value': filter.value.denylist || false, 'type': "str" }),
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
            history_from_data: JSON.stringify({ 'value': indicator.value.history_from_data || false, 'type': "int" }),
        }
        console.log(formData)

        // Assuming you have an API endpoint
        const response = await axios.post(`http://${MOONWALKER_API_HOST}:${MOONWALKER_API_PORT}/config/multiple`, formData);

        if (response.status === 200) {
            message.success('Form submitted successfully')
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
    formRef.value?.validate((errors) => {
        if (!errors) {
            submitForm();
        }
        else {
            console.log(errors)
            message.error('Invalid')
        }
    })
}

onMounted(() => {
    fetchDefaultValues(); // Fetch default values when component is mounted
    timezone.value = getAllTimeZones()
});

</script>
