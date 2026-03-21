<template>
    <n-card title="General settings">
        <n-form
            ref="formRef"
            :model="general"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item label="Timezone" path="timezone">
                <n-select
                    v-model:value="general.timezone"
                    placeholder="Select"
                    :options="timezone"
                    filterable
                />
            </n-form-item>
            <n-form-item
                v-if="showDebug"
                label="Debug mode"
                path="debug"
                label-placement="left"
            >
                <n-checkbox v-model:checked="general.debug" />
            </n-form-item>
            <n-form-item
                v-if="showAdvancedToggle"
                label="Advanced configuration"
                label-placement="left"
            >
                <n-switch
                    :value="showAdvancedGeneral"
                    @update:value="emit('update:showAdvancedGeneral', $event)"
                />
            </n-form-item>
            <template v-if="showAdvancedGeneral">
                <n-form-item
                    label="WebSocket watchdog enabled"
                    path="ws_watchdog_enabled"
                    label-placement="left"
                >
                    <n-checkbox v-model:checked="general.ws_watchdog_enabled" />
                </n-form-item>
                <n-form-item
                    label="WebSocket healthcheck interval (ms)"
                    path="ws_healthcheck_interval_ms"
                >
                    <n-input-number
                        v-model:value="general.ws_healthcheck_interval_ms"
                        :min="1000"
                    />
                </n-form-item>
                <n-form-item
                    label="WebSocket stale timeout (ms)"
                    path="ws_stale_timeout_ms"
                >
                    <n-input-number
                        v-model:value="general.ws_stale_timeout_ms"
                        :min="5000"
                    />
                </n-form-item>
                <n-form-item
                    label="WebSocket reconnect debounce (ms)"
                    path="ws_reconnect_debounce_ms"
                >
                    <n-input-number
                        v-model:value="general.ws_reconnect_debounce_ms"
                        :min="500"
                    />
                </n-form-item>
            </template>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'

interface SelectOption {
    label: string
    value: string
}

interface GeneralModel {
    timezone: string | null
    debug: boolean
    ws_watchdog_enabled: boolean
    ws_healthcheck_interval_ms: number
    ws_stale_timeout_ms: number
    ws_reconnect_debounce_ms: number
}

withDefaults(
    defineProps<{
        general: GeneralModel
        rules: FormRules
        showDebug?: boolean
        showAdvancedGeneral: boolean
        showAdvancedToggle?: boolean
        timezone: SelectOption[]
    }>(),
    {
        showDebug: true,
        showAdvancedToggle: true,
    },
)

const emit = defineEmits<{
    'update:showAdvancedGeneral': [value: boolean]
}>()

const formRef = ref<FormInst | null>(null)

async function validate(): Promise<boolean> {
    if (!formRef.value) {
        return true
    }
    return await new Promise<boolean>((resolve) => {
        formRef.value?.validate((errors) => resolve(!errors))
    })
}

defineExpose({
    validate,
})
</script>
