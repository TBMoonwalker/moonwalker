<template>
    <n-card>
        <n-form
            ref="aiFormRef"
            :model="aiTrust"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item
                label="AI Trust Cockpit enabled"
                path="ai_trust_enabled"
                label-placement="left"
            >
                <n-checkbox v-model:checked="aiTrust.ai_trust_enabled" />
            </n-form-item>
            <n-form-item
                label="Block AI warning entries"
                path="ai_trust_enforce_warnings"
                label-placement="left"
            >
                <n-switch
                    v-model:value="aiTrust.ai_trust_enforce_warnings"
                    :disabled="!aiTrust.ai_trust_enabled"
                />
            </n-form-item>
            <n-form-item
                label="Ollama base URL"
                path="ai_trust_ollama_base_url"
            >
                <n-input
                    v-model:value="aiTrust.ai_trust_ollama_base_url"
                    placeholder="http://localhost:11434"
                />
            </n-form-item>
            <n-form-item label="Ollama model" path="ai_trust_ollama_model">
                <n-input
                    v-model:value="aiTrust.ai_trust_ollama_model"
                    placeholder="qwen3:8b"
                />
            </n-form-item>
            <n-form-item label="AI timeout (ms)" path="ai_trust_timeout_ms">
                <n-input-number
                    v-model:value="aiTrust.ai_trust_timeout_ms"
                    :min="250"
                    :step="250"
                />
            </n-form-item>
            <n-form-item label="AI retry budget" path="ai_trust_max_retries">
                <n-input-number
                    v-model:value="aiTrust.ai_trust_max_retries"
                    :min="0"
                    :max="2"
                    :step="1"
                />
            </n-form-item>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { AiTrustAdvancedModel } from '../../config-editor/types'

defineProps<{
    aiTrust: AiTrustAdvancedModel
    rules: FormRules
}>()

const aiFormRef = ref<FormInst | null>(null)

async function validate(): Promise<boolean> {
    if (!aiFormRef.value) {
        return Promise.resolve(true)
      }

    return new Promise<boolean>((resolve) => {
        aiFormRef.value.validate((errors) => resolve(!errors))
      })
}

defineExpose({
    validate,
})
</script>
