<script setup lang="ts">
import { computed } from 'vue'
import type { ControlCenterTarget } from '../../control-center/types'

interface AdvancedSection {
    sectionId: string
    summary: string
    target: ControlCenterTarget
    title: string
}

const props = defineProps<{
    activeTarget: ControlCenterTarget | null
    advancedSections: AdvancedSection[]
    bindTargetElement: (target: ControlCenterTarget) => (element: Element | null) => void
}>()

const emit = defineEmits<{
    'select-target': [target: ControlCenterTarget]
}>()

const selectedTarget = computed(() =>
    props.advancedSections.some((section) => section.target === props.activeTarget)
        ? props.activeTarget
        : props.advancedSections[0]?.target,
)
const sectionOptions = computed(() =>
    props.advancedSections.map((section) => ({ label: section.title, value: section.target })),
)
</script>

<template>
    <div class="advanced-layout">
        <nav class="advanced-navigation" aria-label="Advanced settings sections">
            <div class="advanced-navigation-heading">Expert settings</div>
            <n-select
                class="advanced-mobile-select"
                :value="selectedTarget"
                :options="sectionOptions"
                aria-label="Choose advanced settings section"
                @update:value="emit('select-target', $event)"
            />
            <div class="advanced-navigation-list">
                <button
                    v-for="section in advancedSections"
                    :key="section.target"
                    type="button"
                    class="advanced-navigation-item"
                    :class="{ 'is-active': selectedTarget === section.target }"
                    :aria-current="selectedTarget === section.target ? 'page' : undefined"
                    @click="emit('select-target', section.target)"
                >
                    {{ section.title }}
                </button>
            </div>
        </nav>

        <div class="advanced-content">
            <div
                v-for="section in advancedSections"
                v-show="selectedTarget === section.target"
                :id="section.sectionId"
                :key="section.target"
                :ref="bindTargetElement(section.target)"
                class="task-section"
            >
                <header class="task-section-header" tabindex="-1" data-control-center-anchor>
                    <h2>{{ section.title }}</h2>
                    <p>{{ section.summary }}</p>
                </header>
                <slot :name="section.target" />
            </div>
        </div>
    </div>
</template>

<style scoped>
.advanced-layout {
    display: grid;
    grid-template-columns: minmax(190px, 230px) minmax(0, 1fr);
    align-items: start;
    gap: 24px;
    width: 100%;
}
.advanced-navigation {
    position: sticky;
    top: 20px;
    display: grid;
    gap: 12px;
    min-width: 0;
}
.advanced-navigation-heading {
    color: var(--mw-color-text-muted);
    font-size: 12px;
    font-weight: 600;
}
.advanced-navigation-list { display: grid; gap: 4px; }
.advanced-navigation-item {
    min-height: 42px;
    padding: 10px 12px;
    border: 0;
    border-radius: var(--mw-radius-sm);
    background: transparent;
    color: var(--mw-color-text-secondary);
    font: inherit;
    font-size: 14px;
    text-align: left;
    cursor: pointer;
}
.advanced-navigation-item:hover { background: var(--mw-color-surface-raised); }
.advanced-navigation-item:focus-visible { outline: var(--mw-focus-ring); outline-offset: var(--mw-focus-offset); }
.advanced-navigation-item.is-active {
    background: var(--mw-color-primary-soft);
    color: var(--mw-color-primary-strong);
    font-weight: 600;
}
.advanced-mobile-select { display: none; }
.advanced-content { min-width: 0; }
.task-section { display: flex; flex-direction: column; gap: 12px; }
.task-section-header { display: grid; gap: 4px; }
.task-section-header:focus { outline: none; }
.task-section-header h2 {
    margin: 0;
    color: var(--mw-color-text-primary);
    font-family: var(--mw-font-display);
    font-size: 1.25rem;
    font-weight: 600;
}
.task-section-header p { margin: 0; color: var(--mw-color-text-secondary); font-size: 14px; }
@media (max-width: 900px) {
    .advanced-layout { grid-template-columns: 1fr; gap: 16px; }
    .advanced-navigation { position: static; }
    .advanced-navigation-list { display: none; }
    .advanced-mobile-select { display: block; }
}
</style>
