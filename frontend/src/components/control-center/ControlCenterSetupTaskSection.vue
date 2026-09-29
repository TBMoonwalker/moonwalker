<script setup lang="ts">
import type {
    ControlCenterTarget,
    ControlCenterTaskPresentation,
} from '../../control-center/types'

interface SetupTaskStatus {
    label: string
    type: 'default' | 'info' | 'warning' | 'success'
}

defineProps<{
    bindTargetElement: (
        target: ControlCenterTarget,
    ) => (element: Element | null) => void
    getSetupTaskStatus: (target: ControlCenterTarget) => SetupTaskStatus
    isSetupTaskExpanded: (target: ControlCenterTarget) => boolean
    task: ControlCenterTaskPresentation
}>()

const emit = defineEmits<{
    'select-setup-target': [target: ControlCenterTarget]
    'setup-shell-click': [target: ControlCenterTarget, event: MouseEvent]
}>()
</script>

<template>
    <div
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
                <n-text v-if="isSetupTaskExpanded(task.target)" depth="3">{{ task.summary }}</n-text>
            </div>
            <span v-if="isSetupTaskExpanded(task.target)" class="current-step-label">Current step</span>
            <n-button
                v-else
                quaternary
                @click="emit('select-setup-target', task.target)"
            >
                Edit
            </n-button>
        </div>
        <div v-show="isSetupTaskExpanded(task.target)" class="task-section-body">
            <slot />
        </div>
    </div>
</template>

<style scoped>
.task-section {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.task-section-shell {
    padding: 4px 0 12px;
    background: transparent;
}

.task-section-collapsed {
    padding: 10px 12px;
    border: 1px solid var(--mw-color-border);
    border-radius: var(--mw-radius-sm);
    background: var(--mw-color-surface-panel);
    cursor: pointer;
}
.task-section-collapsed:hover { background: var(--mw-color-surface-raised); }

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
    outline: var(--mw-focus-ring);
    outline-offset: var(--mw-focus-offset);
    box-shadow: none;
}

.task-section-header h2 {
    margin: 0;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.05rem;
    font-weight: 600;
    letter-spacing: 0;
}

.task-section-body {
    margin-top: 4px;
}
.current-step-label { color: var(--mw-color-primary-strong); font-size: 12px; font-weight: 600; }

@media (max-width: 767px) {
    .task-section-heading-row { align-items: center; }
}
</style>
