import type { LoadedSignalConfigSection } from '../helpers/configLoad'
import type {
    AutopilotConfigSection,
    CapitalConfigSection,
    DcaConfigSection,
    ExchangeConfigSection,
    FilterConfigSection,
    GeneralConfigSection,
    IndicatorConfigSection,
    MonitoringConfigSection,
} from '../helpers/configSubmitPayload'

export interface StringSelectOption {
    label: string
    value: string
}

export interface MixedSelectOption {
    label: string
    value: string | number
}

export type GeneralModel = GeneralConfigSection
export type ExchangeModel = ExchangeConfigSection
export type DcaModel = DcaConfigSection
export type CapitalModel = CapitalConfigSection
export type AutopilotModel = AutopilotConfigSection
export type MonitoringModel = MonitoringConfigSection
export type FilterModel = FilterConfigSection
export type IndicatorModel = IndicatorConfigSection

export type GeneralAdvancedModel = GeneralConfigSection
export type ExchangeAdvancedModel = ExchangeConfigSection
export type DcaAdvancedModel = DcaConfigSection

export interface SignalEditorModel
    extends Omit<
        LoadedSignalConfigSection,
        | 'asap_symbol_options'
        | 'plugins'
        | 'strategy_plugins'
        | 'symsignal_allowedsignals'
    > {
    asap_symbol_options: StringSelectOption[]
    asap_symbols_loading: boolean
    plugins: StringSelectOption[]
    strategy_plugins: StringSelectOption[]
    symsignal_allowedsignals: Array<string | number>
}
