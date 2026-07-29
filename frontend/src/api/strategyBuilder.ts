import axios from 'axios'

import { buildMoonwalkerApiUrl } from '../helpers/configEditorDefaults'
import type {
    StrategyDetail,
    StrategyIr,
    StrategyListPayload,
    StrategyValidation,
} from '../types/strategyBuilder'

export async function fetchStrategyLibrary(): Promise<StrategyListPayload> {
    const response = await axios.get<StrategyListPayload>(
        buildMoonwalkerApiUrl('/strategies'),
    )
    return response.data
}

export async function fetchStrategyDetail(slug: string): Promise<StrategyDetail> {
    const response = await axios.get<StrategyDetail>(
        buildMoonwalkerApiUrl(`/strategies/${slug}`),
    )
    return response.data
}

export async function duplicateStrategy(
    sourceSlug: string,
    name: string,
): Promise<StrategyDetail> {
    const response = await axios.post<StrategyDetail>(
        buildMoonwalkerApiUrl('/strategies/duplicate'),
        { source_slug: sourceSlug, name },
    )
    return response.data
}

export async function createBlankStrategy(name: string): Promise<StrategyDetail> {
    const response = await axios.post<StrategyDetail>(
        buildMoonwalkerApiUrl('/strategies'),
        { name },
    )
    return response.data
}

export async function deleteStrategy(slug: string): Promise<void> {
    await axios.delete(buildMoonwalkerApiUrl(`/strategies/${slug}`))
}

export async function validateStrategy(
    ir: StrategyIr,
    signal?: AbortSignal,
): Promise<StrategyValidation> {
    const response = await axios.post<StrategyValidation>(
        buildMoonwalkerApiUrl('/strategies/validate'),
        { ir },
        { signal },
    )
    return response.data
}

export async function saveStrategyVersion(
    slug: string,
    ir: StrategyIr,
    baseLockVersion: number,
): Promise<StrategyDetail> {
    const response = await axios.put<StrategyDetail>(
        buildMoonwalkerApiUrl(`/strategies/${slug}`),
        { ir, base_lock_version: baseLockVersion },
    )
    return response.data
}

export function isStrategyConflict(error: unknown): boolean {
    return axios.isAxiosError(error) && error.response?.status === 409
}
