<script setup lang="ts">
import Config from '../components/Config.vue'
import { ArrowBackCircleOutline } from '@vicons/ionicons5'
import { NButton, NFlex, NIcon } from 'naive-ui'
import { useRouter } from 'vue-router'

const router = useRouter()

function backButtonClicked() {
    router.push('/')
}
</script>

<template>
    <n-flex justify="space-between" :style="{ width: '92%' }" align="center">
        <n-button strong secondary circle type="primary" size="large" @click="backButtonClicked">
            <template #icon>
                <n-icon>
                    <ArrowBackCircleOutline />
                </n-icon>
            </template>
        </n-button>
    </n-flex>
    <n-flex vertical :style="{ display: 'flex', flexDirection: 'column', gap: '16px', width: '98%' }">
        <Config />
    </n-flex>
</template>
