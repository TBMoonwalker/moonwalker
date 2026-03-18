import type { FormItemRule, FormRules } from 'naive-ui/es/form'
import type { Ref } from 'vue'

interface DcaRulesState {
    dynamic: boolean
    enabled: boolean
}

interface SignalRulesState {
    asap_symbol_select: string[]
    asap_use_url: boolean
    csvsignal_inline: string | null
    csvsignal_mode: string | null
    csvsignal_source: string | null
    signal: string | null
    symbol_list: string | null
}

interface BuildConfigRulesOptions {
    dca: Ref<DcaRulesState>
    getAsapMissingFieldsLabel: () => string
    isAsapExchangeReady: () => boolean
    isCurrencyConfigured: () => boolean
    isUrlInput: (value: string | null) => boolean
    signal: Ref<SignalRulesState>
    submitAttempted: Ref<boolean>
}

function createDcaFieldValidator(
    dca: Ref<DcaRulesState>,
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

function createRequiredAfterSubmitValidator(
    submitAttempted: Ref<boolean>,
    messageText: string,
) {
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

export function buildConfigRules(options: BuildConfigRulesOptions): FormRules {
    const requiredAfterSubmit = (messageText: string) =>
        createRequiredAfterSubmitValidator(options.submitAttempted, messageText)
    const dcaFieldValidator = (
        fieldLabel: string,
        requiredWhen: () => boolean = () => true,
    ) => createDcaFieldValidator(options.dca, fieldLabel, requiredWhen)

    return {
        timezone: {
            validator: requiredAfterSubmit('Please select timezone'),
            trigger: ['submit', 'change'],
        },
        signal: {
            validator: requiredAfterSubmit('Please select signal plugin'),
            trigger: ['submit', 'change'],
        },
        signal_settings: {
            validator: requiredAfterSubmit('Please configure signal'),
            trigger: ['submit', 'change'],
        },
        symbol_list: {
            validator: () => {
                if (
                    !options.submitAttempted.value ||
                    options.signal.value.signal !== 'asap'
                ) {
                    return true
                }
                if (options.signal.value.asap_use_url) {
                    if (
                        options.signal.value.symbol_list === null ||
                        options.signal.value.symbol_list === undefined ||
                        String(options.signal.value.symbol_list).trim().length === 0
                    ) {
                        return new Error('Please add symbol list URL')
                    }
                    if (!options.isUrlInput(String(options.signal.value.symbol_list))) {
                        return new Error('Please provide a valid URL (http/https)')
                    }
                    return true
                }

                if (!options.isCurrencyConfigured()) {
                    return new Error(
                        'Please configure currency before selecting symbols',
                    )
                }

                if (!options.isAsapExchangeReady()) {
                    return new Error(
                        `Please configure ${options.getAsapMissingFieldsLabel()} before selecting symbols`,
                    )
                }

                if (!options.signal.value.asap_symbol_select) {
                    return new Error('Please select at least one symbol')
                }

                if (
                    Array.isArray(options.signal.value.asap_symbol_select) &&
                    options.signal.value.asap_symbol_select.length === 0
                ) {
                    return new Error('Please select at least one symbol')
                }

                return true
            },
            trigger: ['submit', 'change'],
        },
        csv_signal_source: {
            validator: () => {
                if (
                    !options.submitAttempted.value ||
                    options.signal.value.signal !== 'csv_signal' ||
                    options.signal.value.csvsignal_mode !== 'source'
                ) {
                    return true
                }
                if (
                    options.signal.value.csvsignal_source === null ||
                    options.signal.value.csvsignal_source === undefined ||
                    String(options.signal.value.csvsignal_source).trim().length === 0
                ) {
                    return new Error('Please add CSV source path or URL')
                }
                return true
            },
            trigger: ['submit', 'change'],
        },
        csv_signal_inline: {
            validator: () => {
                if (
                    !options.submitAttempted.value ||
                    options.signal.value.signal !== 'csv_signal' ||
                    options.signal.value.csvsignal_mode !== 'inline'
                ) {
                    return true
                }
                if (
                    options.signal.value.csvsignal_inline === null ||
                    options.signal.value.csvsignal_inline === undefined ||
                    String(options.signal.value.csvsignal_inline).trim().length === 0
                ) {
                    return new Error('Please paste CSV text or upload a CSV file')
                }
                return true
            },
            trigger: ['submit', 'change'],
        },
        name: {
            validator: requiredAfterSubmit('Please select exchange'),
            trigger: ['submit', 'change'],
        },
        timeframe: {
            validator: requiredAfterSubmit('Please select timeframe'),
            trigger: ['submit', 'change'],
        },
        key: {
            validator: requiredAfterSubmit('Please add key'),
            trigger: ['submit', 'change'],
        },
        secret: {
            validator: requiredAfterSubmit('Please add secret'),
            trigger: ['submit', 'change'],
        },
        currency: {
            validator: requiredAfterSubmit('Please select currency'),
            trigger: ['submit', 'change'],
        },
        max_bots: {
            validator: requiredAfterSubmit('Please add max bots'),
            trigger: ['submit', 'change'],
        },
        bo: {
            validator: requiredAfterSubmit('Please add bo'),
            trigger: ['submit', 'change'],
        },
        so: {
            validator: dcaFieldValidator(
                'safety order amount',
                () => !options.dca.value.dynamic,
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
                () => !options.dca.value.dynamic,
            ),
            trigger: ['submit'],
        },
        os: {
            validator: dcaFieldValidator(
                'volume scale',
                () => !options.dca.value.dynamic,
            ),
            trigger: ['submit'],
        },
        tp: {
            validator: requiredAfterSubmit('Please add tp'),
            trigger: ['submit', 'change'],
        },
        upnl_housekeeping_interval: {
            validator: requiredAfterSubmit('Please add UPNL history retention'),
            trigger: ['submit', 'change'],
        },
        history_lookback_time: {
            validator: requiredAfterSubmit('Please add history lookback time'),
            trigger: ['submit', 'change'],
        },
    }
}
