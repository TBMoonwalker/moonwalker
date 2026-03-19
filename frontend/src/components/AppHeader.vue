<script setup lang="ts">
import { computed, h, type Component } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import type { MenuOption } from 'naive-ui/es/menu'
import { NIcon } from 'naive-ui/es/icon'
import { PulseOutline, SettingsOutline } from '@vicons/ionicons5'

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
    label: 'Settings',
    key: 'settings',
    icon: renderMenuIcon(SettingsOutline),
  },
]

const activeMenuKey = computed<string | null>(() => {
  if (route.name === 'settings') {
    return 'settings'
  }

  if (route.name === 'monitoring') {
    return 'monitoring'
  }

  return null
})

function handleMenuSelect(key: string | number): void {
  if (key === 'settings') {
    void router.push({ name: 'settings' })
    return
  }

  if (key === 'monitoring') {
    void router.push({ name: 'monitoring' })
  }
}
</script>

<template>
  <header class="app-header">
    <n-card class="app-header-card" content-style="padding: 10px 16px;">
      <div class="header-shell">
        <RouterLink class="brand-link" :to="{ name: 'trades' }">
          <span class="brand-title">Moonwalker</span>
          <span class="brand-caption">single-instance trading console</span>
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
  max-width: 1600px;
  margin: 0 auto;
}

.app-header-card {
  width: 100%;
}

.header-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: center;
}

.brand-link {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  text-decoration: none;
  color: inherit;
}

.brand-title {
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.brand-caption {
  font-size: 0.74rem;
  letter-spacing: 0.02em;
  opacity: 0.7;
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

:deep(.header-menu .n-menu-item-content-header) {
  font-weight: 600;
}

@media (max-width: 768px) {
  .header-shell {
    grid-template-columns: 1fr;
    align-items: flex-start;
  }

  .header-menu-wrap {
    width: 100%;
    justify-content: flex-start;
  }

  .brand-title {
    font-size: 0.95rem;
  }
}
</style>
