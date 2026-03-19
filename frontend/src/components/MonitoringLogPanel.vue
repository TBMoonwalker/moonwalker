<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { fetchJson } from '../api/client'
import {
  appendMonitoringLogLines,
  filterMonitoringLogLines,
  prependMonitoringLogLines,
  type MonitoringLogLevel,
} from '../helpers/monitoringLogs'

interface MonitoringLogSource {
  source: string
  label: string
  available: boolean
}

interface MonitoringLogSourcesResponse {
  sources: MonitoringLogSource[]
}

interface MonitoringLogBatchResponse {
  source: string
  label: string
  available: boolean
  lines: string[]
  cursor: number
  oldest_cursor: number
  has_more_before: boolean
  rotated: boolean
}

interface LogViewRef {
  scrollTo: (options: {
    silent?: boolean
    position?: 'top' | 'bottom'
    top?: number
  }) => void
}

const INITIAL_LOAD_LIMIT = 200
const POLL_LIMIT = 100
const BACKFILL_LIMIT = 100
const BUFFER_LIMIT = 1200
const POLL_INTERVAL_MS = 2500

const sourceOptions = ref<MonitoringLogSource[]>([])
const selectedSource = ref<string | null>(null)
const lines = ref<string[]>([])
const pollCursor = ref(0)
const oldestCursor = ref(0)
const hasMoreBefore = ref(false)
const sourceAvailable = ref(false)
const isLoading = ref(false)
const isLoadingOlder = ref(false)
const paused = ref(false)
const followTail = ref(true)
const errorMessage = ref<string | null>(null)
const selectedLevel = ref<MonitoringLogLevel>('all')
const logViewRef = ref<LogViewRef | null>(null)

let pollTimer: number | null = null

const levelOptions = [
  { label: 'All levels', value: 'all' },
  { label: 'Trace+', value: 'trace+' },
  { label: 'Debug+', value: 'debug+' },
  { label: 'Info+', value: 'info+' },
  { label: 'Warning+', value: 'warning+' },
  { label: 'Error+', value: 'error+' },
  { label: 'Critical only', value: 'critical' },
]

const selectedSourceMeta = computed(() =>
  sourceOptions.value.find((source) => source.source === selectedSource.value) ?? null,
)

const filteredLines = computed(() =>
  filterMonitoringLogLines(lines.value, selectedLevel.value),
)

const sourceSelectOptions = computed(() =>
  sourceOptions.value.map((source) => ({
    label: source.available ? source.label : `${source.label} (not yet available)`,
    value: source.source,
  })),
)

const statusCaption = computed(() => {
  if (errorMessage.value) {
    return errorMessage.value
  }
  if (!sourceAvailable.value) {
    return 'This log file has not been created yet.'
  }
  if (paused.value) {
    return 'Live polling paused.'
  }
  return 'Polling every few seconds for new complete log lines.'
})

async function scrollToBottomIfNeeded(): Promise<void> {
  if (!followTail.value) {
    return
  }
  await nextTick()
  logViewRef.value?.scrollTo({ position: 'bottom', silent: true })
}

async function loadSources(): Promise<void> {
  const response = await fetchJson<MonitoringLogSourcesResponse>('/monitoring/logs')
  sourceOptions.value = response.sources
  if (
    selectedSource.value !== null &&
    response.sources.some((source) => source.source === selectedSource.value)
  ) {
    return
  }

  const defaultSource =
    response.sources.find((source) => source.available) ?? response.sources[0] ?? null
  selectedSource.value = defaultSource?.source ?? null
}

async function loadLatestLines(source: string): Promise<void> {
  isLoading.value = true
  errorMessage.value = null
  lines.value = []
  pollCursor.value = 0
  oldestCursor.value = 0
  hasMoreBefore.value = false

  try {
    const response = await fetchJson<MonitoringLogBatchResponse>(
      `/monitoring/logs/${encodeURIComponent(source)}?limit=${INITIAL_LOAD_LIMIT}`,
    )
    lines.value = response.lines
    pollCursor.value = response.cursor
    oldestCursor.value = response.oldest_cursor
    hasMoreBefore.value = response.has_more_before
    sourceAvailable.value = response.available
    if (response.available) {
      await scrollToBottomIfNeeded()
    }
  } catch (error) {
    sourceAvailable.value = false
    errorMessage.value =
      error instanceof Error ? error.message : 'Failed to load monitoring logs.'
  } finally {
    isLoading.value = false
  }
}

async function pollLatestLines(): Promise<void> {
  if (paused.value || selectedSource.value === null || isLoading.value || isLoadingOlder.value) {
    return
  }

  try {
    const response = await fetchJson<MonitoringLogBatchResponse>(
      `/monitoring/logs/${encodeURIComponent(selectedSource.value)}?cursor=${pollCursor.value}&limit=${POLL_LIMIT}`,
    )

    sourceAvailable.value = response.available
    if (response.rotated) {
      lines.value = response.lines
      oldestCursor.value = response.oldest_cursor
    } else {
      lines.value = appendMonitoringLogLines(lines.value, response.lines, BUFFER_LIMIT)
    }
    pollCursor.value = response.cursor
    hasMoreBefore.value = response.has_more_before

    if (response.lines.length > 0 || response.rotated) {
      await scrollToBottomIfNeeded()
    }
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : 'Failed to poll monitoring logs.'
  }
}

async function loadOlderLines(): Promise<void> {
  if (
    selectedSource.value === null ||
    isLoading.value ||
    isLoadingOlder.value ||
    !hasMoreBefore.value ||
    oldestCursor.value <= 0
  ) {
    return
  }

  isLoadingOlder.value = true
  errorMessage.value = null
  try {
    const response = await fetchJson<MonitoringLogBatchResponse>(
      `/monitoring/logs/${encodeURIComponent(selectedSource.value)}?before=${oldestCursor.value}&limit=${BACKFILL_LIMIT}`,
    )

    if (response.rotated) {
      await loadLatestLines(selectedSource.value)
      return
    }

    lines.value = prependMonitoringLogLines(lines.value, response.lines, BUFFER_LIMIT)
    oldestCursor.value = response.oldest_cursor
    hasMoreBefore.value = response.has_more_before
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : 'Failed to load older monitoring logs.'
  } finally {
    isLoadingOlder.value = false
  }
}

function startPolling(): void {
  stopPolling()
  pollTimer = window.setInterval(() => {
    void pollLatestLines()
  }, POLL_INTERVAL_MS)
}

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function handleRequireMore(from: 'top' | 'bottom'): void {
  if (from === 'top') {
    void loadOlderLines()
  }
}

watch(selectedSource, async (source) => {
  if (source === null) {
    lines.value = []
    sourceAvailable.value = false
    return
  }
  await loadLatestLines(source)
})

watch(paused, (isPaused) => {
  if (isPaused) {
    stopPolling()
    return
  }
  startPolling()
})

onMounted(async () => {
  await loadSources()
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <n-card content-style="padding: 18px 20px;">
    <n-flex vertical :size="16">
      <n-flex justify="space-between" align="start" :wrap="true" :size="[12, 12]">
        <n-flex vertical :size="4">
          <n-text depth="3" class="log-kicker">Live logs</n-text>
          <n-text strong class="log-title">Operational log stream</n-text>
          <n-text depth="3">
            Poll the backend log files for ongoing runtime activity and load older lines on demand.
          </n-text>
        </n-flex>
        <n-tag size="medium" :type="paused ? 'warning' : 'success'">
          {{ paused ? 'Paused' : 'Live polling' }}
        </n-tag>
      </n-flex>

      <n-flex class="log-controls" :size="[12, 12]" :wrap="true">
        <n-select
          v-model:value="selectedSource"
          class="log-control-source"
          placeholder="Choose log source"
          :options="sourceSelectOptions"
        />
        <n-select
          v-model:value="selectedLevel"
          class="log-control-level"
          :options="levelOptions"
        />
        <n-flex align="center" :size="8">
          <n-text depth="3">Pause</n-text>
          <n-switch v-model:value="paused" />
        </n-flex>
        <n-flex align="center" :size="8">
          <n-text depth="3">Follow tail</n-text>
          <n-switch v-model:value="followTail" />
        </n-flex>
        <n-button
          secondary
          type="primary"
          :disabled="selectedSource === null || isLoading"
          @click="selectedSource && loadLatestLines(selectedSource)"
        >
          Refresh
        </n-button>
      </n-flex>

      <n-alert v-if="errorMessage" type="error" :show-icon="false">
        {{ errorMessage }}
      </n-alert>

      <n-flex justify="space-between" align="center" :wrap="true" :size="[12, 8]">
        <n-text depth="3">
          {{ selectedSourceMeta?.label ?? 'No source selected' }}
        </n-text>
        <n-text depth="3">
          Showing {{ filteredLines.length }} line{{ filteredLines.length === 1 ? '' : 's' }}
        </n-text>
      </n-flex>

      <n-log
        ref="logViewRef"
        class="monitoring-log-view"
        :lines="filteredLines"
        :rows="20"
        :loading="isLoading || isLoadingOlder"
        trim
        @require-more="handleRequireMore"
      />

      <n-flex justify="space-between" align="center" :wrap="true" :size="[12, 8]">
        <n-text depth="3">{{ statusCaption }}</n-text>
        <n-text depth="3">
          {{ hasMoreBefore ? 'Scroll to the top of the log to load older lines.' : 'Reached the start of the available log history.' }}
        </n-text>
      </n-flex>
    </n-flex>
  </n-card>
</template>

<style scoped>
.log-kicker {
  font-size: 0.76rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.log-title {
  font-size: 1rem;
}

.log-controls {
  width: 100%;
}

.log-control-source {
  min-width: 260px;
  flex: 1 1 280px;
}

.log-control-level {
  min-width: 180px;
  flex: 0 1 220px;
}

.monitoring-log-view {
  width: 100%;
}

@media (max-width: 768px) {
  .log-control-source,
  .log-control-level {
    min-width: 0;
    width: 100%;
  }
}
</style>
