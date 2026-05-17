<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps<{
   data: { timestamp: number; value: number }[]
}>()

const isMobile = ref(false)

function handleResize() {
   isMobile.value = window.innerWidth < 768
}

onMounted(() => {
   handleResize()
   window.addEventListener('resize', handleResize)
 })

onUnmounted(() => {
   window.removeEventListener('resize', handleResize)
 })

const heatmap = computed(() => {
   if (!props.data.length) return null

   const max = Math.max(...props.data.map((d) => d.value))
   return props.data.map((d) => {
       const date = new Date(d.timestamp)
       const intensity = max > 0 ? d.value / max : 0
       const r = Math.round(29 + intensity * (46 - 29))
       const g = Math.round(92 + intensity * (125 - 92))
       const b = Math.round(73 + intensity * (91 - 73))
       return {
          date,
          color: `rgb(${r}, ${g}, ${b})`,
          value: d.value,
         }
      })
 })
</script>

<template>
   <div v-if="!heatmap?.length" class="heatmap-empty">
     <n-empty description="No data to display" />
   </div>
   <div v-else class="heatmap-grid" :class="{ 'heatmap-grid-mobile': isMobile }">
     <div
        v-for="(cell, idx) in heatmap"
       :key="idx"
      class="heatmap-cell"
       :style="{ backgroundColor: cell.color }"
       :title="`${cell.value} trades on ${cell.date.toLocaleDateString()}`"
     >
        <span v-if="!isMobile" class="heatmap-value">{{ cell.value }}</span>
     </div>
   </div>
</template>

<style scoped>
.heatmap-empty {
   display: flex;
   align-items: center;
   justify-content: center;
   min-height: 120px;
   color: rgba(255, 255, 255, 0.5);
}

.heatmap-grid {
   display: flex;
   flex-wrap: wrap;
   gap: 3px;
   width: 100%;
}

.heatmap-grid-mobile {
   gap: 2px;
}

.heatmap-cell {
   flex: 0 0 calc(1.7% - 3px);
   min-width: 8px;
   min-height: 14px;
   border-radius: 2px;
   display: flex;
   align-items: center;
   justify-content: center;
   transition: opacity 80ms ease;
   cursor: default;
}

.heatmap-cell:hover {
   opacity: 0.85;
}

.heatmap-value {
   font-size: 9px;
   color: rgba(255, 255, 255, 0.85);
   pointer-events: none;
}

@media (max-width: 768px) {
   .heatmap-cell {
      flex: 0 0 calc(1.9% - 2px);
      min-height: 10px;
      border-radius: 1px;
   }

   .heatmap-value {
      display: none;
   }
}
</style>
