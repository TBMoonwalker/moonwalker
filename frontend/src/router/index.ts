import {
    createMemoryHistory,
    createRouter,
    createWebHistory,
    type RouterHistory,
} from 'vue-router'

import { useSharedConfigSnapshot } from '../control-center/configSnapshotStore'
import { deriveControlCenterReadiness } from '../control-center/readiness'
import { resolveControlCenterNavigation } from '../control-center/routerGuard'

export function createAppRouter(
    history: RouterHistory =
        typeof window === 'undefined'
            ? createMemoryHistory()
            : createWebHistory(),
) {
    const router = createRouter({
        history,
        routes: [
            {
                path: '/',
                name: 'trades',
                component: () => import('../views/TradesView.vue'),
            },
            {
                path: '/control-center',
                name: 'controlCenter',
                component: () => import('../views/ControlCenterView.vue'),
            },
            {
                path: '/control-center/autopilot',
                name: 'controlCenterAutopilot',
                component: () => import('../views/AutopilotMemoryView.vue'),
            },
            {
                path: '/backtest',
                name: 'backtest',
                component: () => import('../views/BacktestView.vue'),
            },
            {
                path: '/monitoring',
                name: 'monitoring',
                component: () => import('../views/MonitoringView.vue'),
            },
            {
                path: '/stats',
                name: 'stats',
                component: () => import('../views/StatisticsView.vue'),
            },
            {
                path: '/statistics',
                redirect: { name: 'stats' },
            },
            // Legacy pre-v4.0 route names: the backend used to 404 these;
            // the SPA entry is now served and they land on Configuration
            // (legacy-migration-removal wave, D16).
            {
                path: '/config',
                redirect: { name: 'controlCenter' },
            },
            {
                path: '/settings',
                redirect: { name: 'controlCenter' },
            },
            {
                path: '/:pathMatch(.*)*',
                redirect: { name: 'trades' },
            },
        ],
    })

    router.beforeEach(async (to) => {
        if (to.name === 'controlCenter' && to.query.mode === 'utilities' && to.hash === '#accumulation-controls') {
            return { name: 'trades', query: typeof to.query.symbol === 'string' ? { symbol: to.query.symbol } : {} }
        }
        const snapshotStore = useSharedConfigSnapshot()
        try {
            // Load the full config once; afterwards every navigation only
            // runs the lightweight freshness check and refetches when a
            // newer snapshot is detected (no /config/all per menu click).
            await snapshotStore.ensureFresh()
        } catch {
            return resolveControlCenterNavigation(to, {
                loadError: snapshotStore.loadError.value,
                readiness: deriveControlCenterReadiness(
                    snapshotStore.snapshot.value,
                ),
            })
        }

        const readiness = deriveControlCenterReadiness(
            snapshotStore.snapshot.value,
        )
        return resolveControlCenterNavigation(to, {
            loadError: snapshotStore.loadError.value,
            readiness,
        })
    })

    return router
}

const router = createAppRouter()

export default router
