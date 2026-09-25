<script setup lang="ts">
import type { Component } from "vue"

import {
  ContrastOutline,
  MoonOutline,
  SunnyOutline,
} from "@vicons/ionicons5"
import { storeToRefs } from "pinia"

import {
  useThemeStore,
  type ThemeMode,
} from "../theme/themeStore"

const themeStore = useThemeStore()
const { mode } = storeToRefs(themeStore)

interface ThemeOption {
  readonly value: ThemeMode
  readonly icon: Component
  readonly label: string
  readonly title: string
}

// Order is deliberate: "auto" first (the default), then the two explicit overrides.
const MODES: readonly ThemeOption[] = [
  {
    value: "auto",
    icon: ContrastOutline,
    label: "Follow system theme",
    title: "Auto — follow the system appearance",
  },
  {
    value: "light",
    icon: SunnyOutline,
    label: "Light theme",
    title: "Light theme",
  },
  {
    value: "dark",
    icon: MoonOutline,
    label: "Dark theme",
    title: "Dark theme",
  },
]

function select(next: ThemeMode): void {
  themeStore.setMode(next)
}
</script>

<template>
  <div class="theme-toggle" role="group" aria-label="Colour theme">
    <button
      v-for="option in MODES"
      :key="option.value"
      type="button"
      class="theme-toggle__button"
      :class="{ 'is-active': mode === option.value }"
      :aria-pressed="mode === option.value"
      :title="option.title"
      :aria-label="option.label"
      @click="select(option.value)"
    >
      <component
        :is="option.icon"
        class="theme-toggle__icon"
        aria-hidden="true"
      />
    </button>
  </div>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--mw-color-border);
  border-radius: var(--mw-radius-md);
  background: var(--mw-surface-card);
}

.theme-toggle__button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: none;
  border-radius: var(--mw-radius-sm);
  background: transparent;
  color: var(--mw-color-text-muted);
  cursor: pointer;
  font-size: 1.05rem;
  transition:
    background-color 140ms ease,
    color 140ms ease;
}

.theme-toggle__button:hover {
  color: var(--mw-color-text-secondary);
  background: var(--mw-surface-active);
}

.theme-toggle__button.is-active {
  color: var(--mw-color-primary);
  background: var(--mw-surface-card);
  box-shadow: inset 0 0 0 1px var(--mw-control-readonly-border);
}

.theme-toggle__button:focus-visible {
  outline: var(--mw-focus-ring);
  outline-offset: var(--mw-focus-offset);
}

.theme-toggle__icon {
  width: 1em;
  height: 1em;
}
</style>
