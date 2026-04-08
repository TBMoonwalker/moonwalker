<script setup lang="ts">
import type { SetupEntryChoice } from '../../control-center/setupEntryHistory'
import type {
    ControlCenterTarget,
    ControlCenterTaskPresentation,
} from '../../control-center/types'
import ControlCenterSetupEntryGate from './ControlCenterSetupEntryGate.vue'
import ControlCenterSetupProgressGrid from './ControlCenterSetupProgressGrid.vue'
import ControlCenterSetupRestoreFlow from './ControlCenterSetupRestoreFlow.vue'
import ControlCenterSetupStyleSelector from './ControlCenterSetupStyleSelector.vue'
import ControlCenterSetupTaskSection from './ControlCenterSetupTaskSection.vue'
import type { SetupStyle } from '../../composables/useControlCenterSetupFlow'

type BackupRestoreMode = 'config' | 'full'

interface SetupTaskStatus {
    label: string
    type: 'default' | 'info' | 'warning' | 'success'
}

defineProps<{
    bindBackupFileInput: (element: Element | null) => void
    bindTargetElement: (
        target: ControlCenterTarget,
    ) => (element: Element | null) => void
    getSetupTaskStatus: (target: ControlCenterTarget) => SetupTaskStatus
    getSetupTaskSummary: (target: ControlCenterTarget) => string
    hasSelectedBackupPayload: boolean
    isSetupTaskExpanded: (target: ControlCenterTarget) => boolean
    readinessFirstRun: boolean
    restoreLoading: boolean
    selectedBackupConfigCount: number
    selectedBackupFileName: string | null
    selectedBackupHasTradeData: boolean
    setupStyle: SetupStyle
    setupTasks: ControlCenterTaskPresentation[]
    showRestoreSetupFlow: boolean
    showSetupEntryGate: boolean
    showSetupStyleSelector: boolean
}>()

const emit = defineEmits<{
    'backup-file-selected': [event: Event]
    'clear-selected-backup': []
    'open-backup-file-picker': []
    'restore-backup': [mode: BackupRestoreMode]
    'select-entry-choice': [choice: SetupEntryChoice]
    'select-setup-style': [style: SetupStyle]
    'select-setup-target': [target: ControlCenterTarget]
    'setup-shell-click': [target: ControlCenterTarget, event: MouseEvent]
}>()
</script>

<template>
    <ControlCenterSetupEntryGate
        v-if="showSetupEntryGate"
        @select-entry-choice="emit('select-entry-choice', $event)"
    />

    <template v-else-if="showRestoreSetupFlow">
        <ControlCenterSetupRestoreFlow
            :bind-backup-file-input="bindBackupFileInput"
            :has-selected-backup-payload="hasSelectedBackupPayload"
            :restore-loading="restoreLoading"
            :selected-backup-config-count="selectedBackupConfigCount"
            :selected-backup-file-name="selectedBackupFileName"
            :selected-backup-has-trade-data="selectedBackupHasTradeData"
            @backup-file-selected="emit('backup-file-selected', $event)"
            @clear-selected-backup="emit('clear-selected-backup')"
            @open-backup-file-picker="emit('open-backup-file-picker')"
            @restore-backup="emit('restore-backup', $event)"
            @select-entry-choice="emit('select-entry-choice', $event)"
        />
    </template>

    <template v-else>
        <ControlCenterSetupStyleSelector
            v-if="showSetupStyleSelector"
            :readiness-first-run="readinessFirstRun"
            :setup-style="setupStyle"
            @select-entry-choice="emit('select-entry-choice', $event)"
            @select-setup-style="emit('select-setup-style', $event)"
        />

        <ControlCenterSetupProgressGrid
            :get-setup-task-status="getSetupTaskStatus"
            :get-setup-task-summary="getSetupTaskSummary"
            :setup-tasks="setupTasks"
            @select-setup-target="emit('select-setup-target', $event)"
        />

        <ControlCenterSetupTaskSection
            v-for="task in setupTasks"
            :key="task.sectionId"
            :bind-target-element="bindTargetElement"
            :get-setup-task-status="getSetupTaskStatus"
            :is-setup-task-expanded="isSetupTaskExpanded"
            :task="task"
            @select-setup-target="emit('select-setup-target', $event)"
            @setup-shell-click="(target, event) => emit('setup-shell-click', target, event)"
        >
            <slot :name="task.target" />
        </ControlCenterSetupTaskSection>
    </template>
</template>
