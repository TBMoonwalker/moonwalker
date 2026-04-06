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
            <slot />
        </div>
    </div>
</template>

<style scoped>
.task-section {
    width: 100%;
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

@media (max-width: 768px) {
    .task-section-heading-row {
        flex-direction: column;
    }
}
</style>
