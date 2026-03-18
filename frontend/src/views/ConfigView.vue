<script setup lang="ts">
import Config from '../components/Config.vue'
import { ArrowBackCircleOutline } from '@vicons/ionicons5'
import { useRouter } from 'vue-router'

const router = useRouter()

function backButtonClicked() {
    router.push('/')
}
</script>

<template>
    <div class="page-shell config-page">
        <n-flex class="page-header config-header" justify="space-between" align="center">
            <n-button
                strong
                secondary
                circle
                type="primary"
                size="large"
                aria-label="Back to dashboard"
                title="Back to dashboard"
                @click="backButtonClicked"
            >
                <template #icon>
                    <n-icon>
                        <ArrowBackCircleOutline />
                    </n-icon>
                </template>
            </n-button>
            <n-text depth="3" class="config-title">Configuration</n-text>
        </n-flex>
        <n-flex class="page-section" vertical>
            <Config />
        </n-flex>
    </div>
</template>

<style scoped>
.config-page {
    gap: 16px;
}

.config-title {
    font-size: 0.95rem;
    letter-spacing: 0.02em;
}
</style>
