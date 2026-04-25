<script setup lang="ts">
import type { FormRules } from 'naive-ui/es/form'
import type { VNodeRef } from 'vue'

import type {
    AutopilotModel,
    CapitalModel,
    DcaAdvancedModel,
    ExchangeAdvancedModel,
    FilterModel,
    GeneralAdvancedModel,
    IndicatorModel,
    SignalEditorModel,
    StringSelectOption,
} from '../../config-editor/types'
import type { ControlCenterTarget } from '../../control-center/types'
import ControlCenterAdvancedWorkspace from './ControlCenterAdvancedWorkspace.vue'
import ConfigAutopilotSection from '../config/ConfigAutopilotSection.vue'
import ConfigCapitalSection from '../config/ConfigCapitalSection.vue'
import ConfigDcaAdvancedSection from '../config/ConfigDcaAdvancedSection.vue'
import ConfigExchangeAdvancedSection from '../config/ConfigExchangeAdvancedSection.vue'
import ConfigFilterSection from '../config/ConfigFilterSection.vue'
import ConfigGeneralAdvancedSection from '../config/ConfigGeneralAdvancedSection.vue'
import ConfigIndicatorSection from '../config/ConfigIndicatorSection.vue'

interface AdvancedSection {
    sectionId: string
    summary: string
    target: ControlCenterTarget
    title: string
}

defineProps<{
    advancedSections: AdvancedSection[]
    autopilot: AutopilotModel
    autopilotFormRef?: VNodeRef
    capital: CapitalModel
    capitalFormRef?: VNodeRef
    bindTargetElement: (
        target: ControlCenterTarget,
    ) => (element: Element | null) => void
    dca: DcaAdvancedModel
    dcaFormRef?: VNodeRef
    exchange: ExchangeAdvancedModel
    exchangeFormRef?: VNodeRef
    filter: FilterModel
    filterFormRef?: VNodeRef
    general: GeneralAdvancedModel
    generalFormRef?: VNodeRef
    historyLookbackOptions: StringSelectOption[]
    indicator: IndicatorModel
    indicatorFormRef?: VNodeRef
    rules: FormRules
    signal: SignalEditorModel
}>()
</script>

<template>
    <ControlCenterAdvancedWorkspace
        :advanced-sections="advancedSections"
        :bind-target-element="bindTargetElement"
    >
        <template #general>
            <ConfigGeneralAdvancedSection
                :ref="generalFormRef"
                :general="general"
                :rules="rules"
            />
        </template>

        <template #exchange>
            <ConfigExchangeAdvancedSection
                :ref="exchangeFormRef"
                :exchange="exchange"
                :rules="rules"
            />
        </template>

        <template #dca>
            <ConfigDcaAdvancedSection
                :ref="dcaFormRef"
                :dca="dca"
                :rules="rules"
            />
        </template>

        <template #capital>
            <ConfigCapitalSection
                :ref="capitalFormRef"
                :capital="capital"
                :card-title="null"
                :rules="rules"
            />
        </template>

        <template #filter>
            <ConfigFilterSection
                :ref="filterFormRef"
                :card-title="null"
                :filter="filter"
                :rules="rules"
                :show-asap-fields="signal.signal === 'asap'"
            />
        </template>

        <template #autopilot>
            <ConfigAutopilotSection
                :ref="autopilotFormRef"
                :autopilot="autopilot"
                :card-title="null"
                :rules="rules"
                :show-fields="autopilot.enabled"
            />
        </template>

        <template #indicator>
            <ConfigIndicatorSection
                :ref="indicatorFormRef"
                :card-title="null"
                :history-lookback-options="historyLookbackOptions"
                :indicator="indicator"
                :rules="rules"
            />
        </template>
    </ControlCenterAdvancedWorkspace>
</template>
