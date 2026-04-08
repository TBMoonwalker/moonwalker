<script setup lang="ts">
import type { SetupEntryChoice } from '../../control-center/setupEntryHistory'

const emit = defineEmits<{
    'select-entry-choice': [choice: SetupEntryChoice]
}>()
</script>

<template>
    <n-card
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

.setup-entry-card {
    border: 1px solid rgba(29, 92, 73, 0.14);
    background: var(--mw-surface-shell);
}
</style>
