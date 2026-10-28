<script setup lang="ts">
import type { AccumulationConditionNode } from '../types/accumulation'

defineProps<{ node: AccumulationConditionNode }>()
const operators: Record<string, string> = {
  less_than: '<', less_or_equal: '≤', greater_than: '>', greater_or_equal: '≥',
  equals: '=', not_equals: '≠',
}
function number(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? 'unavailable' : value.toLocaleString(undefined, { maximumSignificantDigits: 10 })
}
</script>

<template>
  <li>
    <div class="condition-line">
      <span>{{ node.label }}</span>
      <strong>{{ node.matched === null ? 'Unavailable' : node.matched ? 'Met' : 'Not met' }}</strong>
      <span v-if="node.kind === 'all'">All required</span>
      <span v-else-if="node.kind === 'any'">At least one required</span>
    </div>
    <p v-if="node.kind === 'comparison' && node.value1 && node.value2">
      {{ node.value1.label }}: {{ number(node.value1.value) }}
      {{ operators[node.comparison ?? ''] ?? node.comparison }}
      {{ node.value2.label }}: {{ number(node.value2.value) }}
    </p>
    <ul v-if="node.children?.length">
      <AccumulationConditionTree v-for="(child, index) in node.children" :key="index" :node="child" />
    </ul>
  </li>
</template>

<style scoped>
li { min-width: 0; }
.condition-line { display: flex; flex-wrap: wrap; gap: 4px 12px; color: var(--mw-color-text-primary); }
strong { font-weight: 600; }
.condition-line > span:last-child { color: var(--mw-color-text-secondary); }
p { margin: 2px 0 0; color: var(--mw-color-text-secondary); font-variant-numeric: tabular-nums; }
ul { margin: 6px 0 0 8px; padding-left: 16px; border-left: 1px solid var(--mw-color-border); list-style: none; }
ul > li + li { margin-top: 8px; }
</style>
