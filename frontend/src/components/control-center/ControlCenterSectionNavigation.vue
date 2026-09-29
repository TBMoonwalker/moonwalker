<script setup lang="ts">
import { computed } from 'vue'
import type { ControlCenterTarget } from '../../control-center/types'

interface SectionLink {
    target: ControlCenterTarget
    title: string
}

const props = defineProps<{
    ariaLabel: string
    heading: string
    selectLabel: string
    sections: SectionLink[]
    selectedTarget: ControlCenterTarget | null
}>()

const emit = defineEmits<{
    'select-target': [target: ControlCenterTarget]
}>()

const sectionOptions = computed(() =>
    props.sections.map((section) => ({ label: section.title, value: section.target })),
)
</script>

<template>
    <nav class="section-navigation" :aria-label="ariaLabel">
        <div class="section-navigation-heading">{{ heading }}</div>
        <n-select
            class="section-mobile-select"
            :value="selectedTarget"
            :options="sectionOptions"
            :aria-label="selectLabel"
            @update:value="emit('select-target', $event)"
        />
        <div class="section-navigation-list">
            <button
                v-for="section in sections"
                :key="section.target"
                type="button"
                class="section-navigation-item"
                :class="{ 'is-active': selectedTarget === section.target }"
                :aria-current="selectedTarget === section.target ? 'page' : undefined"
                @click="emit('select-target', section.target)"
            >
                {{ section.title }}
            </button>
        </div>
    </nav>
</template>

<style scoped>
.section-navigation {
    position: sticky;
    top: 20px;
    display: grid;
    gap: 12px;
    min-width: 0;
}
.section-navigation-heading {
    color: var(--mw-color-text-muted);
    font-size: 12px;
    font-weight: 600;
}
.section-navigation-list { display: grid; gap: 4px; }
.section-navigation-item {
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
.section-navigation-item:hover { background: var(--mw-color-surface-raised); }
.section-navigation-item:focus-visible { outline: var(--mw-focus-ring); outline-offset: var(--mw-focus-offset); }
.section-navigation-item.is-active {
    background: var(--mw-color-primary-soft);
    color: var(--mw-color-primary-strong);
    font-weight: 600;
}
.section-mobile-select { display: none; }
@media (max-width: 900px) {
    .section-navigation { position: static; }
    .section-navigation-list { display: none; }
    .section-mobile-select { display: block; }
}
</style>
