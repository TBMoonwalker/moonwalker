<script setup lang="ts">
import type { SetupEntryChoice } from '../../control-center/setupEntryHistory'
import type {
    ControlCenterTarget,
    ControlCenterTaskPresentation,
} from '../../control-center/types'
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
    <n-card
        v-if="showSetupEntryGate"
        class="workspace-card setup-entry-card"
        content-style="padding: 20px 22px;"
    >
        <n-flex vertical :size="18">
            <div class="setup-entry-intro">
                <n-text depth="3" class="workspace-kicker">
                    Control Center
                </n-text>
                <h1 class="workspace-title">How do you want to begin?</h1>
                <n-text depth="3" class="workspace-summary">
                    Start with your intent, not with a wall of options. Operators
                    migrating an existing instance should restore first. New
                    installations should begin with a safe dry-run setup.
                </n-text>
            </div>

            <n-flex class="entry-choice-grid" :wrap="true" :size="[16, 16]">
                <n-card size="small" class="entry-choice-card">
                    <n-flex vertical :size="12">
                        <div>
                            <h3 class="entry-choice-title">
                                Restore existing installation
                            </h3>
                            <n-text depth="3">
                                Import a config-only or full backup, then review
                                readiness before anything goes live.
                            </n-text>
                        </div>
                        <n-button
                            type="primary"
                            secondary
                            @click="emit('select-entry-choice', 'restore')"
                        >
                            Restore existing installation
                        </n-button>
                    </n-flex>
                </n-card>

                <n-card size="small" class="entry-choice-card">
                    <n-flex vertical :size="12">
                        <div>
                            <h3 class="entry-choice-title">Start a new setup</h3>
                            <n-text depth="3">
                                Configure the essentials needed for a safe dry run
                                before expert tuning or utilities appear.
                            </n-text>
                        </div>
                        <n-button
                            type="primary"
                            @click="emit('select-entry-choice', 'new')"
                        >
                            Start a new setup
                        </n-button>
                    </n-flex>
                </n-card>
            </n-flex>
        </n-flex>
    </n-card>

    <template v-else-if="showRestoreSetupFlow">
        <n-card
            class="workspace-card setup-flow-card"
            content-style="padding: 20px 22px;"
        >
            <n-flex vertical :size="18">
                <n-flex justify="space-between" align="center" :wrap="true">
                    <div>
                        <h2 class="workspace-title">Restore and review</h2>
                        <n-text depth="3" class="workspace-summary">
                            Bring an existing Moonwalker installation forward first,
                            then land in a readiness review before making changes.
                        </n-text>
                    </div>
                    <n-button
                        quaternary
                        @click="emit('select-entry-choice', 'new')"
                    >
                        Start a new setup instead
                    </n-button>
                </n-flex>

                <n-alert type="info" title="Import first, review second">
                    Restoring does not skip safety review. Moonwalker will reload the
                    imported configuration and send you to a readiness check after the
                    backend completes the restore.
                </n-alert>

                <input
                    :ref="bindBackupFileInput"
                    type="file"
                    accept="application/json,.json"
                    class="backup-file-input"
                    @change="emit('backup-file-selected', $event)"
                >

                <n-flex align="center" :wrap="true" :size="[12, 12]">
                    <n-button secondary @click="emit('open-backup-file-picker')">
                        Select backup file
                    </n-button>
                    <span v-if="selectedBackupFileName" class="backup-file-name">
                        {{ selectedBackupFileName }}
                    </span>
                    <n-button
                        v-if="selectedBackupFileName"
                        quaternary
                        @click="emit('clear-selected-backup')"
                    >
                        Clear
                    </n-button>
                </n-flex>

                <n-text v-if="hasSelectedBackupPayload" depth="3">
                    Loaded backup with {{ selectedBackupConfigCount }} config keys<span v-if="selectedBackupHasTradeData"> and trade data</span>.
                </n-text>

                <n-flex align="center" :wrap="true" :size="[12, 12]">
                    <n-button
                        type="warning"
                        :loading="restoreLoading"
                        :disabled="!hasSelectedBackupPayload"
                        @click="emit('restore-backup', 'config')"
                    >
                        Restore config only
                    </n-button>
                    <n-button
                        type="error"
                        ghost
                        :loading="restoreLoading"
                        :disabled="!selectedBackupHasTradeData"
                        @click="emit('restore-backup', 'full')"
                    >
                        Restore full backup
                    </n-button>
                </n-flex>
            </n-flex>
        </n-card>
    </template>

    <template v-else>
        <n-card
            v-if="showSetupStyleSelector"
            class="workspace-card setup-style-card"
            content-style="padding: 18px 20px;"
        >
            <n-flex vertical :size="12">
                <n-flex justify="space-between" align="center" :wrap="true">
                    <div>
                        <h2 class="workspace-title">Choose your setup pace</h2>
                        <n-text depth="3" class="workspace-summary">
                            Guided setup keeps the operator focused on the essentials.
                            Full control reveals expert controls inline while you work.
                        </n-text>
                    </div>
                    <n-button
                        v-if="readinessFirstRun"
                        class="setup-style-restore-action"
                        type="warning"
                        secondary
                        @click="emit('select-entry-choice', 'restore')"
                    >
                        Restore instead
                    </n-button>
                </n-flex>

                <n-flex :wrap="true" :size="[10, 10]">
                    <n-button
                        :type="setupStyle === 'guided' ? 'primary' : 'default'"
                        secondary
                        @click="emit('select-setup-style', 'guided')"
                    >
                        Guided setup
                    </n-button>
                    <n-button
                        :type="setupStyle === 'full' ? 'primary' : 'default'"
                        secondary
                        @click="emit('select-setup-style', 'full')"
                    >
                        Full control
                    </n-button>
                </n-flex>
            </n-flex>
        </n-card>

        <div class="setup-progress-grid">
            <button
                v-for="task in setupTasks"
                :key="task.target"
                class="setup-progress-card"
                :class="{
                    'setup-progress-card-active':
                        getSetupTaskStatus(task.target).type === 'info',
                    'setup-progress-card-blocked':
                        getSetupTaskStatus(task.target).type === 'warning',
                    'setup-progress-card-ready':
                        getSetupTaskStatus(task.target).type === 'success',
                }"
                type="button"
                @click="emit('select-setup-target', task.target)"
            >
                <span class="setup-progress-status">
                    {{ getSetupTaskStatus(task.target).label }}
                </span>
                <strong>{{ task.title }}</strong>
                <span>{{ getSetupTaskSummary(task.target) }}</span>
            </button>
        </div>

        <div
            v-for="task in setupTasks"
            :key="task.sectionId"
            :ref="bindTargetElement(task.target)"
            class="task-section task-section-shell"
            :class="{ 'task-section-collapsed': !isSetupTaskExpanded(task.target) }"
            :id="task.sectionId"
            @click="emit('setup-shell-click', task.target, $event)"
        >
            <div class="task-section-heading-row">
                <div
                    class="task-section-header"
                    tabindex="-1"
                    data-control-center-anchor
                >
                    <h2>{{ task.title }}</h2>
                    <n-text depth="3">{{ task.summary }}</n-text>
                </div>
                <n-button
                    quaternary
                    @click="emit('select-setup-target', task.target)"
                >
                    {{ isSetupTaskExpanded(task.target) ? 'Current step' : 'Open' }}
                </n-button>
            </div>
            <div v-show="isSetupTaskExpanded(task.target)" class="task-section-body">
                <slot :name="task.target" />
            </div>
        </div>
    </template>
</template>

<style scoped>
.workspace-card,
.task-section {
    width: 100%;
}

.workspace-title {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: clamp(1.35rem, 2.4vw, 1.8rem);
    line-height: 1.2;
    font-weight: 700;
    letter-spacing: -0.02em;
}

.workspace-summary {
    display: block;
    margin-top: 6px;
    max-width: 68ch;
}

.workspace-kicker {
    color: var(--mw-color-text-muted);
    display: inline-block;
    font-family: var(--mw-font-body);
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.setup-entry-intro {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.entry-choice-grid {
    align-items: stretch;
}

.entry-choice-card {
    min-width: min(320px, 100%);
    flex: 1 1 320px;
    border: 1px solid rgba(29, 92, 73, 0.16);
    background: var(--mw-surface-card);
    box-shadow: var(--mw-shadow-card);
}

.entry-choice-title {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.12rem;
    font-weight: 700;
    letter-spacing: -0.01em;
}

.setup-entry-card,
.setup-flow-card,
.setup-style-card {
    border: 1px solid rgba(29, 92, 73, 0.14);
    background: var(--mw-surface-shell);
}

.setup-style-restore-action {
    font-weight: 600;
}

.setup-progress-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 16px;
}

.setup-progress-card {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    padding: 14px 16px;
    border: 1px solid rgba(29, 92, 73, 0.12);
    border-radius: 12px;
    background: var(--mw-surface-card-muted);
    color: inherit;
    text-align: left;
    cursor: pointer;
    transition:
        border-color 120ms ease,
        box-shadow 120ms ease,
        transform 120ms ease;
}

.setup-progress-card:hover {
    border-color: rgba(29, 92, 73, 0.28);
    box-shadow: 0 8px 18px rgba(24, 33, 29, 0.06);
    transform: translateY(-1px);
}

.setup-progress-card strong {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 0.96rem;
}

.setup-progress-card span:last-child {
    font-size: 0.88rem;
    color: var(--mw-color-text-secondary);
}

.setup-progress-status {
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: rgba(29, 92, 73, 0.78);
    font-family: var(--mw-font-mono);
}

.setup-progress-card-active {
    border-color: rgba(29, 92, 73, 0.35);
    background: var(--mw-surface-card-success);
}

.setup-progress-card-blocked {
    border-color: rgba(183, 121, 31, 0.26);
    background: var(--mw-surface-card-warning);
}

.setup-progress-card-ready {
    border-color: rgba(46, 125, 91, 0.2);
}

.task-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.task-section-shell {
    border: 1px solid rgba(29, 92, 73, 0.12);
    border-radius: var(--mw-radius-lg);
    padding: 16px 18px;
    background: var(--mw-surface-card);
}

.task-section-collapsed {
    background: var(--mw-surface-card-subtle);
    cursor: pointer;
}

.task-section-heading-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
}

.task-section-header {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.task-section-header:focus,
.task-section-header:focus-visible {
    outline: none;
    box-shadow: none;
}

.task-section-header h2 {
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.01em;
}

.task-section-body {
    margin-top: 6px;
}

.backup-file-input {
    display: none;
}

.backup-file-name {
    font-size: 14px;
}

@media (max-width: 768px) {
    .setup-progress-grid {
        grid-template-columns: 1fr;
    }

    .task-section-heading-row {
        flex-direction: column;
    }
}
</style>
