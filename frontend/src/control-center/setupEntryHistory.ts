export const CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY =
    'controlCenterSetupEntryChoice'

export type SetupEntryChoice = 'restore' | 'new'

export function parseSetupEntryChoice(value: unknown): SetupEntryChoice | null {
    return value === 'restore' || value === 'new' ? value : null
}

export function getSetupEntryChoiceFromHistoryState(
    value: unknown,
): SetupEntryChoice | null {
    if (!value || typeof value !== 'object') {
        return null
    }
    return parseSetupEntryChoice(
        (value as Record<string, unknown>)[CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY],
    )
}

export function buildSetupEntryChoiceHistoryState(
    value: unknown,
    choice: SetupEntryChoice | null,
): Record<string, unknown> {
    const currentState =
        value && typeof value === 'object' ? { ...(value as Record<string, unknown>) } : {}
    if (choice === null) {
        delete currentState[CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY]
        return currentState
    }
    currentState[CONTROL_CENTER_HISTORY_ENTRY_CHOICE_KEY] = choice
    return currentState
}
