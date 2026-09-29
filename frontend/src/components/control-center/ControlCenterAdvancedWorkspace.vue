<script setup lang="ts">
import { computed } from 'vue'
import type { ControlCenterTarget } from '../../control-center/types'
import ControlCenterSectionNavigation from './ControlCenterSectionNavigation.vue'

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
</script>

<template>
    <div class="advanced-layout">
        <ControlCenterSectionNavigation
            aria-label="Advanced settings sections"
            heading="Expert settings"
            select-label="Choose advanced settings section"
            :sections="advancedSections"
            :selected-target="selectedTarget ?? null"
            @select-target="emit('select-target', $event)"
        />

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
}
</style>
