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
                path: '/monitoring',
                name: 'monitoring',
                component: () => import('../views/MonitoringView.vue'),
            },
        ],
    })

    router.beforeEach(async (to) => {
        const snapshotStore = useSharedConfigSnapshot()
        try {
            await snapshotStore.ensureLoaded(false)
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
