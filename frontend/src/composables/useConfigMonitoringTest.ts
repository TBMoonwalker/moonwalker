import axios from 'axios'
import { ref, type Ref } from 'vue'

import type { MonitoringConfigSection } from '../helpers/configSubmitPayload'

interface MessageApiLike {
    error: (message: string) => void
    success: (message: string) => void
}

interface UseConfigMonitoringTestOptions {
    apiUrl: (path: string) => string
    message: MessageApiLike
    monitoring: Ref<MonitoringConfigSection>
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

    async function testMonitoringTelegram(): Promise<void> {
        if (!canTestMonitoringTelegram()) {
            options.message.error('Please add valid Telegram settings first.')
            return
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
            options.message.success(
                response.data?.message || 'Monitoring Telegram test sent.',
            )
        } catch (error) {
            if (axios.isAxiosError(error) && error.response) {
                options.message.error(
                    error.response.data?.error ||
                        'Monitoring Telegram test failed.',
                )
            } else if (axios.isAxiosError(error) && error.request) {
                options.message.error('No response from server. Please try again later.')
            } else if (error instanceof Error) {
                options.message.error(`Request failed: ${error.message}`)
            } else {
                options.message.error('Monitoring Telegram test failed.')
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
