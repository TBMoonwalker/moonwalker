<script setup lang="ts">
import Config from '../components/Config.vue'
</script>

<template>
    <div class="page-shell settings-page operator-console-page">
        <n-flex class="page-section" vertical>
            <Config />
        </n-flex>
    </div>
</template>

<style scoped>
.settings-page {
    gap: 12px;
}

.page-section {
    min-width: 0;
}
</style>
