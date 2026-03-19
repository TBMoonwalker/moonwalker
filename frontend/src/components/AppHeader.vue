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
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 160 120" class="brand-mark-svg">
              <circle cx="52" cy="48" r="35" class="mark-moon-fill" />
              <circle cx="52" cy="48" r="35" class="mark-moon-stroke" />
              <circle cx="42" cy="36" r="3" class="mark-crater" />
              <circle cx="67" cy="55" r="4" class="mark-crater" />
              <circle cx="31" cy="59" r="2.5" class="mark-crater" />
              <path
                d="M103 28c9 0 16 11 16 25 0 3-1 7-2 10l8 10-9 4-5-9-9 1-6-2c-4 6-10 9-17 9-4 0-8-1-11-4l-8 15-10-5 7-15c-5-5-7-12-7-20 0-16 10-29 23-29 4 0 8 1 11 3 3-8 10-13 19-13z"
                class="mark-rocket-trail"
              />
              <path
                d="M114 20c10 6 14 17 12 32l16 21-9 5-8-11-7 22-7-3 4-25c-9-1-16-6-20-15-4-10-2-21 5-29 5-5 9-8 14-10z"
                class="mark-rocket-body"
              />
              <circle cx="112" cy="41" r="6.5" class="mark-rocket-window" />
              <path
                d="M61 42c0-16 11-29 24-29s24 13 24 29c0 5-1 9-3 13-4 8-12 13-21 13s-17-5-21-13c-2-4-3-8-3-13z"
                class="mark-helmet"
              />
              <circle cx="84" cy="42" r="13" class="mark-faceplate" />
              <circle cx="79" cy="41" r="2.5" class="mark-eye" />
              <circle cx="89" cy="41" r="2.5" class="mark-eye" />
              <path d="M72 58h25l7 20-11 22H76L65 78z" class="mark-suit" />
              <path d="M61 64l-10 12 7 7 11-11z" class="mark-suit" />
              <path d="M107 64l12 11-7 8-13-11z" class="mark-suit" />
              <path d="M76 98l-4 17 10 1 5-16z" class="mark-suit" />
              <path d="M95 98l4 17-10 1-4-16z" class="mark-suit" />
              <path d="M38 102c12 4 26 6 47 6 22 0 39-2 51-7" class="mark-ground" />
              <circle cx="132" cy="29" r="2" class="mark-star" />
              <circle cx="138" cy="48" r="1.7" class="mark-star" />
            </svg>
          </span>
          <span class="brand-copy">
            <span class="brand-title">Moonwalker</span>
            <span class="brand-caption">single-instance trading console</span>
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
  max-width: 1600px;
  margin: 0 auto;
  padding-inline: 10px;
}

.app-header-card {
  width: 100%;
  border: 1px solid var(--color-border-hover);
  background:
    linear-gradient(135deg, rgba(99, 226, 183, 0.12), transparent 58%),
    linear-gradient(180deg, var(--color-background-soft), var(--color-background-mute));
  box-shadow: 0 14px 32px rgba(0, 0, 0, 0.08);
}

.header-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
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
  width: 74px;
  height: 56px;
  align-items: center;
  justify-content: center;
}

.brand-mark-svg {
  width: 100%;
  height: 100%;
  color: var(--color-heading);
}

.brand-copy {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
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

.mark-moon-fill {
  fill: currentColor;
  opacity: 0.1;
}

.mark-moon-stroke,
.mark-ground {
  fill: none;
  stroke: currentColor;
  stroke-width: 2.4;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.42;
}

.mark-crater,
.mark-eye,
.mark-star {
  fill: currentColor;
  opacity: 0.45;
}

.mark-helmet,
.mark-suit,
.mark-rocket-body {
  fill: rgba(255, 255, 255, 0.88);
  stroke: currentColor;
  stroke-width: 2.4;
  stroke-linejoin: round;
}

.mark-faceplate,
.mark-rocket-window {
  fill: currentColor;
  opacity: 0.14;
  stroke: currentColor;
  stroke-width: 2;
}

.mark-rocket-trail {
  fill: currentColor;
  opacity: 0.08;
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
  border-radius: 10px;
}

:deep(.header-menu .n-menu-item-content::before) {
  border-radius: 10px;
}

:deep(.header-menu .n-menu-item-content-header) {
  font-weight: 600;
}

@media (max-width: 768px) {
  .app-header {
    padding-inline: 6px;
  }

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

  .brand-mark {
    width: 64px;
    height: 48px;
  }
}
</style>
