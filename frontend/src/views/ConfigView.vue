<script setup lang="ts">
import Config from '../components/Config.vue'
import { NFlex } from 'naive-ui'
</script>

<template>
    <n-flex vertical :style="{ display: 'flex', flexDirection: 'column', gap: '16px', width: '98%' }">
        <Config />
    </n-flex>
</template>
