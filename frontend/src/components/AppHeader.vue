<script setup lang="ts">
import { computed, h, type Component } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import type { MenuOption } from 'naive-ui/es/menu'
import { NIcon } from 'naive-ui/es/icon'
import { PulseOutline, SettingsOutline } from '@vicons/ionicons5'
import logoImage from '../assets/logo.png'

function renderMenuIcon(icon: Component) {
  return () =>
    h(NIcon, null, {
      default: () => h(icon),
    })
}

const route = useRoute()
const router = useRouter()

const menuOptions: MenuOption[] = [
  {
    label: 'Monitoring',
    key: 'monitoring',
    icon: renderMenuIcon(PulseOutline),
  },
  {
    label: 'Control Center',
    key: 'controlCenter',
    icon: renderMenuIcon(SettingsOutline),
  },
]

const activeMenuKey = computed<string | null>(() => {
  if (route.name === 'controlCenter') {
    return 'controlCenter'
  }

  if (route.name === 'monitoring') {
    return 'monitoring'
  }

  return null
})

function handleMenuSelect(key: string | number): void {
  if (key === 'controlCenter') {
    void router.push({ name: 'controlCenter' })
    return
  }

  if (key === 'monitoring') {
    void router.push({ name: 'monitoring' })
  }
}
</script>

<template>
  <header class="app-header">
    <n-card class="app-header-card" content-style="padding: 6px 4px 2px;">
      <div class="header-shell">
        <RouterLink class="brand-link" :to="{ name: 'trades' }">
          <span class="brand-mark" aria-hidden="true">
            <img class="brand-mark-image" :src="logoImage" alt="" />
          </span>
          <span class="brand-copy">
            <span class="brand-title">Moonwalker</span>
            <span class="brand-caption">Trading Bot Framework</span>
          </span>
        </RouterLink>
        <div class="header-menu-wrap">
          <n-menu
            class="header-menu"
            mode="horizontal"
            responsive
            :value="activeMenuKey"
            :options="menuOptions"
            @update:value="handleMenuSelect"
          />
        </div>
      </div>
    </n-card>
  </header>
</template>

<style scoped>
.app-header {
  width: 100%;
  max-width: var(--mw-content-width);
  margin: 0 auto;
}

.app-header-card {
  width: 100%;
  border: none;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.header-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: center;
}

.brand-link {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  text-decoration: none;
  color: inherit;
}

.brand-mark {
  display: inline-flex;
  flex: 0 0 auto;
  width: 72px;
  height: 48px;
  align-items: center;
  justify-content: center;
}

.brand-mark-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.brand-copy {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.brand-title {
  color: var(--mw-color-text-primary);
  font-family: var(--mw-font-display);
  font-size: 1.3rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.brand-caption {
  color: var(--mw-color-text-muted);
  font-size: 0.88rem;
  letter-spacing: 0.01em;
}

.header-menu-wrap {
  display: flex;
  justify-content: flex-end;
}

.header-menu {
  width: auto;
  min-width: 0;
  background: transparent;
}

:deep(.header-menu .n-menu) {
  background: transparent;
}

:deep(.header-menu .n-menu-item-content) {
  border-radius: var(--mw-radius-md);
}

:deep(.header-menu .n-menu-item-content::before) {
  border-radius: var(--mw-radius-md);
}

:deep(.header-menu .n-menu-item-content-header) {
  color: var(--mw-color-text-secondary);
  font-family: var(--mw-font-body);
  font-weight: 600;
}

:deep(.header-menu .n-menu-item-content__icon) {
  color: var(--mw-color-text-secondary);
  transition: color 120ms ease;
}

:deep(.header-menu .n-menu-item-content--selected) {
  background: rgba(29, 92, 73, 0.12);
  box-shadow: inset 0 0 0 1px rgba(29, 92, 73, 0.12);
}

:deep(.header-menu .n-menu-item-content--selected .n-menu-item-content-header) {
  color: #18413a;
  font-weight: 700;
}

:deep(.header-menu .n-menu-item-content--selected .n-menu-item-content__icon) {
  color: #18413a;
}

@media (max-width: 768px) {
  .header-shell {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 10px;
    align-items: center;
  }

  .header-menu-wrap {
    width: auto;
    justify-content: flex-end;
  }

  .brand-title {
    font-size: 1.05rem;
  }

  .brand-mark {
    width: 54px;
    height: 36px;
  }

  :deep(.header-menu .n-menu-item-content-header) {
    display: none;
  }

  :deep(.header-menu .n-menu-item-content__icon) {
    margin-right: 0;
  }

  :deep(.header-menu .n-menu-item-content) {
    padding-inline: 10px;
  }
}
</style>
