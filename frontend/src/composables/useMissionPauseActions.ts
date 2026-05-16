import { reactive, ref } from 'vue'

import { fetchJson } from '../api/client'
import { tradeSymbolToRouteParam } from '../helpers/openTrades'

type MissionPauseAction = 'pause' | 'resume'

type MissionPauseResponse = {
    result: string
    message?: string
    status?: string
    symbol?: string
    automation_paused?: boolean
}

interface UseMissionPauseActionsOptions {
    message: {
        error: (message: string) => void
        info: (message: string) => void
        success: (message: string) => void
    }
}

export function useMissionPauseActions(options: UseMissionPauseActionsOptions) {
    const activeSymbol = ref<string | null>(null)
    const activeAction = ref<MissionPauseAction | null>(null)
    const missionActionErrors = reactive<Record<string, string | null>>({})

    function clearMissionActionError(symbol: string): void {
        missionActionErrors[symbol] = null
    }

    function isMissionActionLoading(
        symbol: string,
        action: MissionPauseAction,
    ): boolean {
        return activeSymbol.value === symbol && activeAction.value === action
    }

    async function runMissionAction(
        symbol: string,
        action: MissionPauseAction,
    ): Promise<void> {
        const normalizedSymbol = String(symbol ?? '').trim().toUpperCase()
        if (!normalizedSymbol) {
            return
        }

        activeSymbol.value = normalizedSymbol
        activeAction.value = action
        missionActionErrors[normalizedSymbol] = null

        try {
            const response = await fetchJson<MissionPauseResponse>(
                `/trades/mission/${action}/${tradeSymbolToRouteParam(normalizedSymbol)}`,
                {
                    method: 'POST',
                },
            )
            const status = String(response.status ?? response.result ?? '').trim()
            const messageText =
                response.message ??
                (action === 'pause'
                    ? `Paused automation for ${normalizedSymbol}.`
                    : `Resumed automation for ${normalizedSymbol}.`)

            if (status === 'already_paused' || status === 'already_resumed') {
                options.message.info(messageText)
            } else {
                options.message.success(messageText)
            }
            missionActionErrors[normalizedSymbol] = null
        } catch (error) {
            const detail =
                error instanceof Error
                    ? error.message
                    : `Failed to ${action} automation.`
            missionActionErrors[normalizedSymbol] = detail
            options.message.error(detail)
        } finally {
            activeSymbol.value = null
            activeAction.value = null
        }
    }

    async function handlePauseMission(symbol: string): Promise<void> {
        await runMissionAction(symbol, 'pause')
    }

    async function handleResumeMission(symbol: string): Promise<void> {
        await runMissionAction(symbol, 'resume')
    }

    return {
        clearMissionActionError,
        handlePauseMission,
        handleResumeMission,
        isMissionActionLoading,
        missionActionErrors,
    }
}
