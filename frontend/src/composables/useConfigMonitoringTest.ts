import axios from 'axios'
import { ref, type Ref } from 'vue'

import type { OperationResult } from '../control-center/operationResults'
import type { MonitoringConfigSection } from '../helpers/configSubmitPayload'

interface MessageApiLike {
    error: (message: string) => void
    success: (message: string) => void
}

interface UseConfigMonitoringTestOptions {
    apiUrl: (path: string) => string
    message: MessageApiLike
    monitoring: Ref<MonitoringConfigSection>
    surfaceMessages?: boolean
}

export function useConfigMonitoringTest(
    options: UseConfigMonitoringTestOptions,
) {
    const monitoringTestLoading = ref(false)

    function canTestMonitoringTelegram(): boolean {
        return Boolean(
            options.monitoring.value.telegram_api_id &&
                options.monitoring.value.telegram_api_hash &&
                options.monitoring.value.telegram_bot_token &&
                options.monitoring.value.telegram_chat_id,
        )
    }

    async function testMonitoringTelegram(): Promise<OperationResult> {
        if (!canTestMonitoringTelegram()) {
            const message = 'Please add valid Telegram settings first.'
            if (options.surfaceMessages !== false) {
                options.message.error(message)
            }
            return {
                status: 'error',
                message,
            }
        }

        monitoringTestLoading.value = true
        try {
            const response = await axios.post(
                options.apiUrl('/monitoring/test'),
                {
                    monitoring_telegram_api_id:
                        options.monitoring.value.telegram_api_id,
                    monitoring_telegram_api_hash:
                        options.monitoring.value.telegram_api_hash,
                    monitoring_telegram_bot_token:
                        options.monitoring.value.telegram_bot_token,
                    monitoring_telegram_chat_id:
                        options.monitoring.value.telegram_chat_id,
                    monitoring_timeout_sec:
                        options.monitoring.value.timeout_sec ?? 5,
                    monitoring_retry_count:
                        options.monitoring.value.retry_count ?? 1,
                },
            )
            const message =
                response.data?.message || 'Monitoring Telegram test sent.'
            if (options.surfaceMessages !== false) {
                options.message.success(message)
            }
            return {
                status: 'success',
                message,
            }
        } catch (error) {
            if (axios.isAxiosError(error) && error.response) {
                const message =
                    error.response.data?.error ||
                    'Monitoring Telegram test failed.'
                if (options.surfaceMessages !== false) {
                    options.message.error(message)
                }
                return {
                    status: 'error',
                    message,
                    statusCode: error.response.status,
                }
            } else if (axios.isAxiosError(error) && error.request) {
                const message = 'No response from server. Please try again later.'
                if (options.surfaceMessages !== false) {
                    options.message.error(message)
                }
                return {
                    status: 'error',
                    message,
                }
            } else if (error instanceof Error) {
                const message = `Request failed: ${error.message}`
                if (options.surfaceMessages !== false) {
                    options.message.error(message)
                }
                return {
                    status: 'error',
                    message,
                }
            } else {
                const message = 'Monitoring Telegram test failed.'
                if (options.surfaceMessages !== false) {
                    options.message.error(message)
                }
                return {
                    status: 'error',
                    message,
                }
            }
        } finally {
            monitoringTestLoading.value = false
        }
    }

    return {
        canTestMonitoringTelegram,
        monitoringTestLoading,
        testMonitoringTelegram,
    }
}
