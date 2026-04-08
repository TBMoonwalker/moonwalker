<script setup lang="ts">
import type { SetupEntryChoice } from '../../control-center/setupEntryHistory'
import type { SetupStyle } from '../../composables/useControlCenterSetupFlow'

defineProps<{
    readinessFirstRun: boolean
    setupStyle: SetupStyle
}>()

const emit = defineEmits<{
    'select-entry-choice': [choice: SetupEntryChoice]
    'select-setup-style': [style: SetupStyle]
}>()
</script>

<template>
    <n-card
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
</template>

<style scoped>
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

.setup-style-card {
    border: 1px solid rgba(29, 92, 73, 0.14);
    background: var(--mw-surface-shell);
}

.setup-style-restore-action {
    font-weight: 600;
}
</style>
