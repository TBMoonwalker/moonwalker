<template>
    <n-card
        v-if="!compact"
        size="small"
        role="status"
        aria-live="polite"
        aria-atomic="true"
    >
        <n-space vertical :size="8">
            <n-text depth="3">Realtime streams</n-text>
            <n-space wrap>
                <n-tag :type="getTagType(openStatus)">
                    Open stream
                </n-tag>
                <n-tag :type="getTagType(closedStatus)">
                    Closed stream
                </n-tag>
                <n-tag :type="getTagType(statisticsStatus)">
                    Statistics stream
                </n-tag>
            </n-space>
        </n-space>
    </n-card>
    <n-space
        v-else
        class="compact-streams"
        align="center"
        wrap
        role="status"
        aria-live="polite"
        aria-atomic="true"
        :size="[8, 8]"
    >
        <n-tag class="compact-stream-tag" size="medium" :type="getTagType(openStatus)">
            Open stream
        </n-tag>
        <n-tag class="compact-stream-tag" size="medium" :type="getTagType(closedStatus)">
            Closed stream
        </n-tag>
        <n-tag class="compact-stream-tag" size="medium" :type="getTagType(statisticsStatus)">
            Statistics stream
        </n-tag>
    </n-space>
</template>

<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { NCard, NSpace, NTag, NText } from 'naive-ui'
import { useWebSocketDataStore, type WebSocketStatus } from '../stores/websocket'

withDefaults(defineProps<{ compact?: boolean }>(), {
    compact: false,
})

const openTradesStore = useWebSocketDataStore('openTrades')
const closedTradesStore = useWebSocketDataStore('closedTrades')
const statisticsStore = useWebSocketDataStore('statistics')

const { status: openStatus } = storeToRefs(openTradesStore)
const { status: closedStatus } = storeToRefs(closedTradesStore)
const { status: statisticsStatus } = storeToRefs(statisticsStore)

function getTagType(status: WebSocketStatus): 'success' | 'error' {
    return status === 'OPEN' ? 'success' : 'error'
}
</script>

<style scoped>
.compact-streams {
    max-width: 100%;
}

:deep(.compact-stream-tag.n-tag) {
    min-height: 36px;
    display: inline-flex;
    align-items: center;
    font-weight: 600;
}

@media (max-width: 768px) {
    .compact-streams {
        gap: 6px;
    }

    :deep(.compact-stream-tag.n-tag) {
        min-height: 30px;
        font-size: 12px;
        padding: 0 8px;
    }
}
</style>
