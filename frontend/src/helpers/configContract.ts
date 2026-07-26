export const CONFIG_CONTRACT_VERSION = 1

type ConfigContractField = {
    default?: unknown
}

type ConfigContract = {
    version?: unknown
    fields?: Record<string, ConfigContractField>
}

export function getConfigContractDefault<T>(
    response: Record<string, unknown>,
    key: string,
    fallback: T,
): T {
    const contract = response.config_contract as ConfigContract | undefined
    if (
        contract?.version !== CONFIG_CONTRACT_VERSION ||
        !contract.fields ||
        !Object.prototype.hasOwnProperty.call(contract.fields[key] ?? {}, 'default')
    ) {
        return fallback
    }
    return contract.fields[key]?.default as T
}
