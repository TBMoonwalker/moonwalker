import axios from 'axios'
import { watch, type Ref } from 'vue'

import { parseSymbolListToArray } from '../helpers/configForm'

type ConfigOption = {
    label: string
    value: string
}

interface SignalState {
    symbol_list: string | null
    asap_use_url: boolean
    asap_symbol_select: string[]
    asap_symbol_options: ConfigOption[]
    asap_symbols_loading: boolean
    asap_symbol_fetch_error: string | null
    signal: string | null
    strategy_enabled: boolean
    strategy: string | null
    symsignal_url: string | null
    symsignal_version: string | null
    csvsignal_mode: string | null
    csvsignal_source: string | null
    csvsignal_inline: string | null
    csvsignal_file_name: string | null
}

interface ExchangeState {
    name: string | null
    key: string | null
    secret: string | null
    exchange_hostname: string | null
    dry_run: boolean | null
    currency: string | null
    market: string | null
}

interface MessageApiLike {
    error: (message: string) => void
    success: (message: string) => void
}

interface UseConfigSignalFlowOptions {
    apiUrl: (path: string) => string
    defaultSymSignalUrl: string
    defaultSymSignalVersion: string
    exchange: Ref<ExchangeState>
    isLoading: Ref<boolean>
    message: MessageApiLike
    resetSignalStrategySelection: () => void
    signal: Ref<SignalState>
}

interface ApplySignalSelectionOptions {
    awaitAsapFetch?: boolean
}

const ASAP_URL_PARTIAL_PATTERN =
    /^(?:|h|ht|htt|http|https|http:|https:|http:\/|https:\/|https?:\/\/[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]*)$/

export function useConfigSignalFlow(options: UseConfigSignalFlowOptions) {
    function isCurrencyConfigured(): boolean {
        const configuredCurrency = options.exchange.value.currency
        if (!configuredCurrency) {
            return false
        }
        return String(configuredCurrency).trim().length > 0
    }

    function getAsapExchangeMissingFields(): string[] {
        const missing: string[] = []
        if (!options.exchange.value.name) {
            missing.push('exchange')
        }
        if (!options.exchange.value.key) {
            missing.push('key')
        }
        if (!options.exchange.value.secret) {
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

    function handleAsapUrlInput(value: string): void {
        if (ASAP_URL_PARTIAL_PATTERN.test(value)) {
            options.signal.value.symbol_list = value
        }
    }

    async function fetchAsapSymbolsForCurrency(): Promise<void> {
        options.signal.value.asap_symbol_options = []
        options.signal.value.asap_symbol_fetch_error = null
        options.signal.value.asap_symbols_loading = true

        if (!isAsapExchangeReady()) {
            options.signal.value.asap_symbol_fetch_error =
                `Missing exchange configuration: ${getAsapMissingFieldsLabel()}`
            options.signal.value.asap_symbols_loading = false
            return
        }

        try {
            const quoteCurrency = String(options.exchange.value.currency).toUpperCase()
            const response = await axios.post(options.apiUrl('/data/exchange/symbols'), {
                currency: quoteCurrency,
                exchange_config: {
                    exchange: options.exchange.value.name,
                    key: options.exchange.value.key,
                    secret: options.exchange.value.secret,
                    exchange_hostname:
                        options.exchange.value.exchange_hostname || undefined,
                    market: options.exchange.value.market || 'spot',
                    dry_run: options.exchange.value.dry_run ?? true,
                },
            })
            const symbols = Array.isArray(response.data?.symbols)
                ? response.data.symbols
                : []
            const missing = Array.isArray(response.data?.missing)
                ? response.data.missing
                : []
            if (missing.length > 0) {
                options.signal.value.asap_symbol_fetch_error =
                    `Missing exchange configuration: ${missing.join(', ')}`
                options.signal.value.asap_symbol_options = []
                return
            }
            options.signal.value.asap_symbol_options = symbols.map((symbol: string) => ({
                label: symbol,
                value: symbol,
            }))

            if (
                typeof options.signal.value.symbol_list === 'string' &&
                options.signal.value.symbol_list.length > 0
            ) {
                const configuredSymbols = parseSymbolListToArray(
                    options.signal.value.symbol_list,
                )
                const optionValues = new Set(
                    options.signal.value.asap_symbol_options.map(
                        (option) => option.value,
                    ),
                )
                options.signal.value.asap_symbol_select = configuredSymbols.filter(
                    (symbol) => optionValues.has(symbol),
                )
            }
        } catch (error) {
            console.error('Error fetching ASAP symbols:', error)
            options.signal.value.asap_symbol_fetch_error =
                'Failed to fetch symbols from exchange.'
        } finally {
            options.signal.value.asap_symbols_loading = false
        }
    }

    async function applySignalSettingsSelection(
        applyOptions: ApplySignalSelectionOptions = {},
    ): Promise<void> {
        if (options.signal.value.signal === 'sym_signals') {
            if (!options.signal.value.symsignal_url) {
                options.signal.value.symsignal_url = options.defaultSymSignalUrl
            }
            if (!options.signal.value.symsignal_version) {
                options.signal.value.symsignal_version =
                    options.defaultSymSignalVersion
            }
            return
        }

        if (options.signal.value.signal === 'asap') {
            if (!options.signal.value.asap_use_url) {
                if (applyOptions.awaitAsapFetch) {
                    await fetchAsapSymbolsForCurrency()
                } else {
                    void fetchAsapSymbolsForCurrency()
                }
            }
            return
        }

        if (options.signal.value.signal === 'csv_signal') {
            options.resetSignalStrategySelection()
            if (!options.signal.value.csvsignal_mode) {
                options.signal.value.csvsignal_mode = 'source'
            }
        }
    }

    function handleSignalSettingsSelect(): void {
        void applySignalSettingsSelection()
    }

    async function handleCsvSignalFileSelected(event: Event): Promise<void> {
        const input = event.target as HTMLInputElement
        const selectedFile = input.files?.[0]
        if (!selectedFile) {
            return
        }

        try {
            const csvText = await selectedFile.text()
            options.signal.value.csvsignal_mode = 'inline'
            options.signal.value.csvsignal_inline = csvText
            options.signal.value.csvsignal_file_name = selectedFile.name
            options.message.success(`Loaded ${selectedFile.name}`)
        } catch (error) {
            console.error('Error loading CSV file:', error)
            options.message.error('Failed to read CSV file.')
        } finally {
            input.value = ''
        }
    }

    watch(
        () => options.signal.value.asap_use_url,
        (useUrl) => {
            if (options.isLoading.value) {
                return
            }
            if (options.signal.value.signal !== 'asap') {
                return
            }
            if (useUrl) {
                options.signal.value.asap_symbol_select = []
                options.signal.value.asap_symbol_options = []
                options.signal.value.asap_symbol_fetch_error = null
                if (!isUrlInput(options.signal.value.symbol_list)) {
                    options.signal.value.symbol_list = null
                }
                return
            }
            options.signal.value.asap_symbol_options = []
            options.signal.value.asap_symbol_fetch_error = null
        },
    )

    watch(
        () => [
            options.exchange.value.currency,
            options.exchange.value.name,
            options.exchange.value.key,
            options.exchange.value.secret,
            options.exchange.value.exchange_hostname,
        ],
        () => {
            if (options.isLoading.value) {
                return
            }
            if (
                options.signal.value.signal === 'asap' &&
                !options.signal.value.asap_use_url
            ) {
                options.signal.value.asap_symbol_options = []
                options.signal.value.asap_symbol_select = []
                options.signal.value.asap_symbol_fetch_error = null
            }
        },
    )

    watch(
        () => options.signal.value.asap_symbol_select,
        (selectedSymbol) => {
            if (
                options.signal.value.signal === 'asap' &&
                !options.signal.value.asap_use_url
            ) {
                options.signal.value.symbol_list = Array.isArray(selectedSymbol)
                    ? selectedSymbol.join(',')
                    : null
            }
        },
    )

    return {
        applySignalSettingsSelection,
        fetchAsapSymbolsForCurrency,
        getAsapMissingFieldsLabel,
        handleAsapUrlInput,
        handleCsvSignalFileSelected,
        handleSignalSettingsSelect,
        isAsapExchangeReady,
        isCurrencyConfigured,
        isUrlInput,
    }
}
