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
    getSetupTaskStatus: (target: ControlCenterTarget) => SetupTaskStatus
    getSetupTaskSummary: (target: ControlCenterTarget) => string
    setupTasks: ControlCenterTaskPresentation[]
}>()

const emit = defineEmits<{
    'select-setup-target': [target: ControlCenterTarget]
}>()
</script>

<template>
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
</template>

<style scoped>
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

@media (max-width: 768px) {
    .setup-progress-grid {
        grid-template-columns: 1fr;
    }
}
</style>
