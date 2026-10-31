<script setup lang="ts">
import { computed, h, ref, type Component } from 'vue'
import axios from 'axios'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import type { MenuOption } from 'naive-ui/es/menu'
import { NIcon } from 'naive-ui/es/icon'
import { useMessage } from 'naive-ui/es/message'
import {
  AnalyticsOutline,
  BarChartOutline,
  FlaskOutline,
  GridOutline,
  MenuOutline,
  PulseOutline,
  SettingsOutline,
} from '@vicons/ionicons5'
import logoImage from '../assets/logo.png'
import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'
import { useConnectionSync } from '../composables/useConnectionSync'
import { buildMoonwalkerApiUrl } from '../helpers/configEditorDefaults'
import { extractApiErrorMessage } from '../helpers/apiErrors'
import ThemeToggle from './ThemeToggle.vue'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const mobileMenuOpen = ref(false)
const tradingPauseLoading = ref(false)
const configSnapshotStore = useSharedConfigSnapshot()
const { connection } = useConnectionSync()

const titles: Record<string, string> = {
  trades: 'Overview',
  stats: 'Statistics',
  backtest: 'Backtest',
  controlCenterAutopilot: 'Autopilot Memory',
  controlCenter: 'Configuration',
  monitoring: 'Monitoring',
}
const currentTitle = computed(() => {
  if (route.name === 'controlCenter' && route.query.mode === 'strategy-builder') return 'Strategy Builder'
  if (route.name === 'controlCenter' && route.query.mode === 'utilities') return 'Utilities'
  return titles[String(route.name)] ?? 'Overview'
})
const currentNavigationKey = computed(() => {
  if (route.name !== 'controlCenter') return String(route.name ?? 'trades')
  if (route.query.mode === 'strategy-builder') return 'strategyBuilder'
  if (route.query.mode === 'utilities') return 'utilities'
  return 'controlCenter'
})
const tradingMode = computed(() => {
  const snapshot = configSnapshotStore.snapshot.value
  if (!snapshot) return 'Checking mode'
  return snapshot.dry_run === false || snapshot.dry_run === 'false'
    ? 'Live trading'
    : 'Dry run'
})
const tradingPaused = computed(() => configSnapshotStore.snapshot.value?.trading_paused === true)
const pauseActionLabel = computed(() => tradingPaused.value ? 'Resume Moonwalker' : 'Pause Moonwalker')

async function toggleTradingPause(): Promise<void> {
  if (tradingPauseLoading.value || !configSnapshotStore.snapshot.value) return
  const action = tradingPaused.value ? 'resume' : 'pause'
  const confirmation = tradingPaused.value
    ? 'Resume Moonwalker now? New trades and re-entries will be allowed again.'
    : 'Pause Moonwalker now? Existing exits can keep running, but new trades and re-entries will stop.'
  if (!window.confirm(confirmation)) return

  tradingPauseLoading.value = true
  try {
    const response = await axios.post(buildMoonwalkerApiUrl(`/config/trading/${action}`), { confirm: true })
    await configSnapshotStore.refresh()
    configSnapshotStore.emitLocalInvalidation('trading_pause')
    message.success(response.data?.message ?? (action === 'pause' ? 'Moonwalker paused.' : 'Moonwalker resumed.'))
  } catch (error) {
    message.error(extractApiErrorMessage(error, 'Could not change Moonwalker pause state.'))
  } finally {
    tradingPauseLoading.value = false
  }
}

function icon(component: Component) {
  return () => h(NIcon, null, { default: () => h(component) })
}

const workspaceOptions = computed<MenuOption[]>(() => [
  { label: 'Overview', key: 'trades', icon: icon(GridOutline) },
  { label: 'Statistics', key: 'stats', icon: icon(BarChartOutline) },
  { label: 'Backtest', key: 'backtest', icon: icon(FlaskOutline) },
  {
    label: 'Autopilot Memory',
    key: 'controlCenterAutopilot',
    icon: icon(AnalyticsOutline),
  },
].filter(item => item.key !== 'controlCenterAutopilot' || ['dynamic_dca', 'classic_dca', 'sidestep'].includes(String(configSnapshotStore.snapshot.value?.trade_mode))))
const operationOptions: MenuOption[] = [
  { label: 'Configuration', key: 'controlCenter', icon: icon(SettingsOutline) },
  { label: 'Strategy Builder', key: 'strategyBuilder', icon: icon(AnalyticsOutline) },
  { label: 'Utilities', key: 'utilities', icon: icon(GridOutline) },
  { label: 'Monitoring', key: 'monitoring', icon: icon(PulseOutline) },
]

function navigate(key: string | number): void {
  mobileMenuOpen.value = false
  if (key === 'strategyBuilder' || key === 'utilities') {
    void router.push({ name: 'controlCenter', query: { mode: key === 'strategyBuilder' ? 'strategy-builder' : 'utilities' } })
    return
  }
  void router.push({ name: String(key) })
}

</script>

<template>
  <div class="app-header">
    <aside class="app-sidebar" aria-label="Main navigation">
      <RouterLink class="brand-link" :to="{ name: 'trades' }" @click="mobileMenuOpen = false">
        <img class="brand-logo" :src="logoImage" alt="" />
        <span class="brand-title">Moonwalker</span>
      </RouterLink>
      <button
        type="button"
        class="mobile-menu-toggle"
        aria-label="Open navigation"
        :aria-expanded="mobileMenuOpen"
        aria-controls="mobile-navigation"
        @click.stop="mobileMenuOpen = true"
      >
        <n-icon><MenuOutline /></n-icon>
      </button>
      <div class="nav-caption">Workspace</div>
      <n-menu
        class="side-menu"
        :value="currentNavigationKey"
        :options="workspaceOptions"
        @update:value="navigate"
      />
      <div class="nav-caption operations-caption">Operations</div>
      <n-menu
        class="side-menu"
        :value="currentNavigationKey"
        :options="operationOptions"
        @update:value="navigate"
      />
    </aside>
    <n-drawer v-model:show="mobileMenuOpen" placement="left" :width="280">
      <n-drawer-content closable title="Moonwalker navigation">
        <nav id="mobile-navigation" class="mobile-navigation" aria-label="Main navigation">
          <div class="nav-caption">Workspace</div>
          <n-menu
            class="side-menu"
            :value="currentNavigationKey"
            :options="workspaceOptions"
            @update:value="navigate"
          />
          <div class="nav-caption operations-caption">Operations</div>
          <n-menu
            class="side-menu"
            :value="currentNavigationKey"
            :options="operationOptions"
            @update:value="navigate"
          />
        </nav>
      </n-drawer-content>
    </n-drawer>
    <header class="app-topbar">
      <div class="breadcrumb">
        <span>Moonwalker</span><span class="breadcrumb-divider">/</span>
        <strong>{{ currentTitle }}</strong>
      </div>
      <div class="topbar-actions">
        <n-button
          class="trading-pause-button"
          :type="tradingPaused ? 'warning' : 'default'"
          secondary
          size="small"
          :loading="tradingPauseLoading"
          :disabled="!configSnapshotStore.snapshot.value"
          :aria-label="pauseActionLabel"
          @click="toggleTradingPause"
        >
          <span class="pause-label-desktop">{{ pauseActionLabel }}</span>
          <span class="pause-label-mobile">{{ tradingPaused ? 'Resume' : 'Pause' }}</span>
        </n-button>
        <span class="mode-badge" :class="{ 'is-live': tradingMode === 'Live trading' }">
          {{ tradingMode }}
        </span>
        <span
          class="connection-badge"
          :class="{ 'is-connected-badge': connection.connected }"
          role="status"
          aria-live="polite"
        >
          <n-spin v-if="!connection.connected" size="small" class="connection-sync-spinner" aria-hidden="true" />
          <span v-else class="connection-dot is-connected" aria-hidden="true" />
          {{ connection.label }}
        </span>
        <ThemeToggle />
      </div>
      <div
        class="sync-bar"
        :class="{ 'is-active': !connection.connected }"
        aria-hidden="true"
      ></div>
    </header>
  </div>
</template>

<style scoped>
.app-header { display: contents; }
.app-sidebar {
  grid-column: 1;
  grid-row: 1 / 3;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 100vh;
  padding: 18px 12px 20px;
  border-right: 1px solid var(--mw-color-border);
  background: var(--mw-color-surface-raised);
}
.brand-link {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 55px;
  padding: 0 9px;
  color: var(--mw-color-text-primary);
  text-decoration: none;
}
.brand-logo { width: 48px; height: 46px; object-fit: contain; }
.brand-title {
  font-family: var(--mw-font-display);
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.04em;
  white-space: nowrap;
}
.mobile-menu-toggle {
  display: none;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 44px;
  border: 1px solid var(--mw-color-border);
  border-radius: var(--mw-radius-sm);
  background: transparent;
  color: var(--mw-color-text-primary);
  cursor: pointer;
}
.mobile-menu-toggle:focus-visible { outline: 2px solid var(--mw-color-primary); outline-offset: 2px; }
.nav-caption {
  margin: 27px 10px 8px;
  color: var(--mw-color-text-muted);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
}
.operations-caption { margin-top: 30px; }
.side-menu { --n-item-height: 40px; }
.side-menu :deep(.n-menu-item-content) {
  border-radius: 7px;
  padding-left: 13px !important;
}
.side-menu :deep(.n-menu-item-content::before) { border-radius: 7px; }
.side-menu :deep(.n-menu-item-content--selected) {
  background: var(--mw-color-surface-panel);
}
.side-menu :deep(.n-menu-item-content--selected .n-menu-item-content__icon) {
  color: var(--mw-color-primary);
}
.side-menu :deep(.n-menu-item-content-header) { font-size: 13px; font-weight: 600; }
.app-topbar {
  position: relative;
  grid-column: 2;
  grid-row: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
  padding: 0 34px;
  border-bottom: 1px solid var(--mw-color-border);
  background: var(--mw-color-surface-base);
}
.sync-bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -3px;
  height: 3px;
  overflow: hidden;
  pointer-events: none;
  z-index: 60;
  opacity: 0;
  transition: opacity 160ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
.sync-bar.is-active {
  opacity: 1;
}
.sync-bar::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  width: 35%;
  border-radius: 999px;
  background: var(--mw-color-warning);
  transform: translateX(-140%);
  will-change: transform;
}
.sync-bar.is-active::before {
  animation: sync-bar-indeterminate 900ms cubic-bezier(0.4, 0, 0.2, 1) infinite;
}
@keyframes sync-bar-indeterminate {
  0% {
    transform: translateX(-140%);
  }
  100% {
    transform: translateX(320%);
  }
}
.connection-sync-spinner {
  vertical-align: middle;
}
@media (prefers-reduced-motion: reduce) {
  .sync-bar.is-active::before {
    animation: none;
    width: 100%;
    transform: none;
    opacity: 0.5;
  }
}
.breadcrumb, .topbar-actions { display: flex; align-items: center; gap: 12px; }
.breadcrumb { color: var(--mw-color-text-muted); font-size: 12px; white-space: nowrap; }
.breadcrumb strong { color: var(--mw-color-text-primary); }
.topbar-actions { color: var(--mw-color-text-muted); font-size: 11px; }
.trading-pause-button { min-height: 36px; }
.pause-label-mobile { display: none; }
.mode-badge, .connection-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 9px;
  border: 1px solid var(--mw-color-border);
  border-radius: 5px;
  white-space: nowrap;
}
.mode-badge.is-live { color: var(--mw-color-warning); }
.connection-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 3px;
  border-radius: 50%;
  background: var(--mw-color-warning);
}
.connection-dot.is-connected { background: var(--mw-color-success); }
@media (max-width: 820px) {
  .app-header { display: flex; flex-direction: column; }
  .app-sidebar {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    min-height: 0;
    padding: 8px 12px;
    border-right: 0;
    border-bottom: 1px solid var(--mw-color-border);
  }
  .brand-link { min-height: 42px; }
  .brand-logo { width: 40px; height: 38px; }
  .app-sidebar > .nav-caption,
  .app-sidebar > .side-menu { display: none; }
  .mobile-menu-toggle { display: inline-flex; min-width: 44px; min-height: 44px; }
  .app-topbar { min-height: 50px; padding: 0 18px; }
}
@media (max-width: 560px) {
  .pause-label-desktop { display: none; }
  .pause-label-mobile { display: inline; }
  .trading-pause-button { min-height: 44px; min-width: 64px; }
  .connection-badge { display: none; }
  .app-topbar { padding: 0 12px; gap: 8px; }
  .breadcrumb > span { display: none; }
  .topbar-actions { gap: 6px; }
}
</style>
