<script setup lang="ts">
import Config from '../components/Config.vue'
</script>

<template>
    <div class="page-shell settings-page">
        <n-flex class="page-section" vertical>
            <n-card class="settings-intro-card" content-style="padding: 18px 20px;">
                <n-flex vertical :size="6">
                    <n-text depth="3" class="settings-kicker">Settings</n-text>
                    <n-text>
                        Configure the shared Moonwalker runtime for this installation.
                    </n-text>
                </n-flex>
            </n-card>
        </n-flex>
        <n-flex class="page-section" vertical>
            <Config />
        </n-flex>
    </div>
</template>

<style scoped>
.settings-page {
    gap: 0;
}

.page-section {
    margin-inline: 10px;
    margin-bottom: 10px;
}

.page-section:last-child {
    margin-bottom: 0;
}

.settings-kicker {
    font-size: 0.82rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

@media (max-width: 768px) {
    .page-section {
        margin-inline: 6px;
    }
}
</style>
