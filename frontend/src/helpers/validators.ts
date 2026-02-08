export function isJsonString(str: any) {
    try {
        JSON.parse(str);
    } catch (e) {
        return false;
    }
    return true;
}

export function isFloat(n: any) {
    return Number(n) === n && n % 1 !== 0;
}

export function createDecimal(precision: number): number {
    return 1 / Math.pow(10, precision + 2);
}

export function toNumberOrNull(value: unknown): number | null {
    if (value === null || value === undefined || value === '') {
        return null
    }
    const num = Number(value)
    return Number.isNaN(num) ? null : num
}

export function parseBooleanString(value: unknown): boolean | undefined {
    if (typeof value === 'boolean') {
        return value
    }
    if (typeof value === 'number') {
        return value !== 0
    }
    if (typeof value === 'string') {
        switch (value.toLowerCase()) {
            case 'true':
                return true
            case 'false':
                return false
            default:
                throw new Error(`Cannot convert "${value}" to boolean`)
        }
    }

    return undefined
}
