<script setup lang="ts">
import type { ControlCenterTarget } from '../../control-center/types'

interface AdvancedSection {
    sectionId: string
    summary: string
    target: ControlCenterTarget
    title: string
}

defineProps<{
    advancedSections: AdvancedSection[]
    bindTargetElement: (
        target: ControlCenterTarget,
    ) => (element: Element | null) => void
}>()
</script>

<template>
    <div
        v-for="section in advancedSections"
        :id="section.sectionId"
        :key="section.target"
        :ref="bindTargetElement(section.target)"
        class="task-section"
    >
        <div class="task-section-header" tabindex="-1" data-control-center-anchor>
            <h2>{{ section.title }}</h2>
            <n-text depth="3">{{ section.summary }}</n-text>
        </div>

        <slot :name="section.target" />
    </div>
</template>

<style scoped>
.task-section {
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 10px;
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
</style>
