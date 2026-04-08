import axios from 'axios'

type ResponseLike = {
    data?: unknown
}

function extractResponseData(error: unknown): unknown {
    if (axios.isAxiosError(error)) {
        return error.response?.data
    }
    if (error && typeof error === 'object' && 'response' in error) {
        return (error as { response?: ResponseLike | null }).response?.data
    }
    return null
}

function stringifyResponseData(data: unknown): string | null {
    if (data == null) {
        return null
    }
    if (typeof data === 'string') {
        return data
    }
    if (typeof data === 'number' || typeof data === 'boolean') {
        return String(data)
    }
    if (typeof data !== 'object') {
        return null
    }
    if ('message' in data && data.message != null) {
        return String(data.message)
    }
    if ('error' in data && data.error != null) {
        return String(data.error)
    }
    try {
        return JSON.stringify(data)
    } catch {
        return null
    }
}

export function extractApiErrorMessage(error: unknown, fallback: string): string {
    const responseData = stringifyResponseData(extractResponseData(error))
    if (responseData) {
        return responseData
    }
    if (axios.isAxiosError(error) && error.message) {
        return error.message
    }
    if (error instanceof Error && error.message) {
        return error.message
    }
    return fallback
}
