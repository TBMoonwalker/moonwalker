<script setup lang="ts">
import { computed } from 'vue'
import type { SetupEntryChoice } from '../../control-center/setupEntryHistory'
import type {
    ControlCenterTarget,
    ControlCenterTaskPresentation,
} from '../../control-center/types'
import type { RestoreReviewState } from '../../composables/useConfigBackupRestore'
import ControlCenterSetupEntryGate from './ControlCenterSetupEntryGate.vue'
import ControlCenterSetupRestoreFlow from './ControlCenterSetupRestoreFlow.vue'
import ControlCenterSetupStyleSelector from './ControlCenterSetupStyleSelector.vue'
import ControlCenterSetupTaskSection from './ControlCenterSetupTaskSection.vue'
import ControlCenterSectionNavigation from './ControlCenterSectionNavigation.vue'
import type { SetupStyle } from '../../composables/useControlCenterSetupFlow'

type BackupRestoreMode = 'config' | 'full'

interface SetupTaskStatus {
    label: string
    type: 'default' | 'info' | 'warning' | 'success'
}

const props = defineProps<{
    activeTarget: ControlCenterTarget
    bindBackupFileInput: (element: Element | null) => void
    bindTargetElement: (
        target: ControlCenterTarget,
    ) => (element: Element | null) => void
    getSetupTaskStatus: (target: ControlCenterTarget) => SetupTaskStatus
    getSetupTaskSummary: (target: ControlCenterTarget) => string
    hasSelectedBackupPayload: boolean
    isSetupTaskExpanded: (target: ControlCenterTarget) => boolean
    liveActivationAvailable: boolean
    readinessComplete: boolean
    readinessFirstRun: boolean
    restoreLoading: boolean
    restoreReview: RestoreReviewState | null
    selectedBackupConfigCount: number
    selectedBackupFileName: string | null
    selectedBackupHasTradeData: boolean
    setupStyle: SetupStyle
    setupTasks: ControlCenterTaskPresentation[]
    showRestoreSetupFlow: boolean
    showSetupEntryGate: boolean
    showSetupStyleSelector: boolean
}>()

const setupSections = computed(() => [
    ...props.setupTasks,
    ...(props.liveActivationAvailable
        ? [{ target: 'live-activation' as ControlCenterTarget, title: 'Readiness review' }]
        : []),
])

function isTaskExpanded(target: ControlCenterTarget): boolean {
    return props.readinessComplete || props.isSetupTaskExpanded(target)
}

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
            :restore-review="restoreReview"
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

        <div :class="{ 'setup-layout': readinessComplete }">
            <ControlCenterSectionNavigation
                v-if="readinessComplete"
                aria-label="Setup sections"
                heading="Setup sections"
                select-label="Choose setup section"
                :sections="setupSections"
                :selected-target="activeTarget"
                @select-target="emit('select-setup-target', $event)"
            />
            <div class="setup-content">
                <ControlCenterSetupTaskSection
                    v-for="task in setupTasks"
                    v-show="!readinessComplete || activeTarget === task.target"
                    :key="task.sectionId"
                    :bind-target-element="bindTargetElement"
                    :get-setup-task-status="getSetupTaskStatus"
                    :is-setup-task-expanded="isTaskExpanded"
                    :ready-layout="readinessComplete"
                    :task="task"
                    @select-setup-target="emit('select-setup-target', $event)"
                    @setup-shell-click="(target, event) => emit('setup-shell-click', target, event)"
                >
                    <slot :name="task.target" />
                </ControlCenterSetupTaskSection>
                <slot
                    v-if="liveActivationAvailable && activeTarget === 'live-activation'"
                    name="readiness-review"
                />
            </div>
        </div>
    </template>
</template>

<style scoped>
.setup-layout {
    display: grid;
    grid-template-columns: minmax(190px, 230px) minmax(0, 1fr);
    align-items: start;
    gap: 24px;
    width: 100%;
}
.setup-content { display: grid; gap: 12px; min-width: 0; }
@media (max-width: 900px) {
    .setup-layout { grid-template-columns: 1fr; gap: 16px; }
}
</style>
