import type { Ref } from 'vue'

import type { LoadedSignalConfigSection } from '../helpers/configLoad'
import type {
    AutopilotConfigSection,
    DcaConfigSection,
    ExchangeConfigSection,
    FilterConfigSection,
    GeneralConfigSection,
    IndicatorConfigSection,
    MonitoringConfigSection,
} from '../helpers/configSubmitPayload'
import {
    usePersistableStateTracking,
    type PersistableState,
} from './usePersistableStateTracking'

interface UseConfigPersistableStateOptions {
    autopilot: Ref<AutopilotConfigSection>
    dca: Ref<DcaConfigSection>
    exchange: Ref<ExchangeConfigSection>
    filter: Ref<FilterConfigSection>
    general: Ref<GeneralConfigSection>
    indicator: Ref<IndicatorConfigSection>
    monitoring: Ref<MonitoringConfigSection>
    signal: Ref<LoadedSignalConfigSection>
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

function buildPersistableState(
    options: UseConfigPersistableStateOptions,
): PersistableState {
    return {
        general: { ...options.general.value },
        signal: {
            symbol_list: options.signal.value.symbol_list,
            asap_use_url: options.signal.value.asap_use_url,
            asap_symbol_select: options.signal.value.asap_symbol_select,
            signal: options.signal.value.signal,
            strategy: options.signal.value.strategy,
            strategy_enabled: options.signal.value.strategy_enabled,
            symsignal_url: options.signal.value.symsignal_url,
            symsignal_key: options.signal.value.symsignal_key,
            symsignal_version: options.signal.value.symsignal_version,
            symsignal_allowedsignals: options.signal.value.symsignal_allowedsignals,
            csvsignal_mode: options.signal.value.csvsignal_mode,
            csvsignal_source: options.signal.value.csvsignal_source,
            csvsignal_inline: options.signal.value.csvsignal_inline,
        },
        filter: { ...options.filter.value },
        exchange: { ...options.exchange.value },
        dca: { ...options.dca.value },
        autopilot: { ...options.autopilot.value },
        monitoring: { ...options.monitoring.value },
        indicator: { ...options.indicator.value },
    }
}

export function useConfigPersistableState(
    options: UseConfigPersistableStateOptions,
) {
    return usePersistableStateTracking({
        buildState: () => buildPersistableState(options),
        sectionLabels: SECTION_LABELS,
    })
}
