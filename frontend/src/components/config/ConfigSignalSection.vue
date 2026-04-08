<template>
    <n-card title=" Signal settings">
        <n-form
            ref="formRef"
            :model="signal"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item label="Signal Plugin" path="signal">
                <n-select
                    v-model:value="signal.signal"
                    placeholder="Select"
                    :options="signal.plugins"
                    @update:value="onSignalSettingsSelect"
                    @blur="onSignalSettingsSelect"
                />
            </n-form-item>

            <template v-if="signal.signal === 'sym_signals'">
                <n-form-item label="URL" path="url.0">
                    <n-input v-model:value="signal.symsignal_url" placeholder="URL" />
                </n-form-item>
                <n-form-item label="Key" path="key.0">
                    <n-input
                        v-model:value="signal.symsignal_key"
                        type="password"
                        show-password-on="click"
                        placeholder="Key"
                    />
                </n-form-item>
                <n-form-item label="Version" path="version.0">
                    <n-input
                        v-model:value="signal.symsignal_version"
                        placeholder="Version"
                    />
                </n-form-item>
                <n-form-item label="Allowed Signals" path="signals">
                    <n-select
                        v-model:value="signal.symsignal_allowedsignals"
                        placeholder="Select"
                        :options="symsignals"
                        multiple
                        filterable
                    />
                </n-form-item>
            </template>

            <template v-if="signal.signal === 'asap'">
                <n-form-item label="Use URL input" path="asap_use_url" label-placement="left">
                    <n-switch v-model:value="signal.asap_use_url" />
                </n-form-item>
                <n-form-item
                    v-if="signal.asap_use_url"
                    label="Token/Coin List or URL"
                    path="symbol_list"
                >
                    <n-input
                        :value="signal.symbol_list"
                        placeholder="https://example.com/symbols.txt"
                        @update:value="onAsapUrlInput"
                    />
                </n-form-item>
                <n-form-item v-else label="ASAP Symbol" path="symbol_list">
                    <n-flex vertical :style="{ width: '100%' }">
                        <n-alert v-if="!isAsapExchangeReady" type="info">
                            Please configure {{ asapMissingFieldsLabel }} in Exchange settings first.
                        </n-alert>
                        <n-alert v-else-if="signal.asap_symbol_fetch_error" type="warning">
                            {{ signal.asap_symbol_fetch_error }}
                        </n-alert>
                        <n-button
                            secondary
                            type="primary"
                            :loading="signal.asap_symbols_loading"
                            :disabled="!isAsapExchangeReady"
                            @click="onFetchAsapSymbols"
                        >
                            Load symbols from exchange
                        </n-button>
                        <n-select
                            v-model:value="signal.asap_symbol_select"
                            :options="signal.asap_symbol_options"
                            multiple
                            :loading="signal.asap_symbols_loading"
                            :disabled="!isAsapExchangeReady || signal.asap_symbol_options.length === 0"
                            placeholder="Select symbol"
                            filterable
                        />
                    </n-flex>
                </n-form-item>
            </template>

            <template v-if="signal.signal === 'csv_signal'">
                <n-form-item label="CSV input mode" path="csv_signal_mode">
                    <n-radio-group v-model:value="signal.csvsignal_mode">
                        <n-space>
                            <n-radio value="source">Path / URL</n-radio>
                            <n-radio value="inline">Paste text / Upload file</n-radio>
                        </n-space>
                    </n-radio-group>
                </n-form-item>
                <n-form-item
                    v-if="signal.csvsignal_mode === 'source'"
                    label="CSV source (path or URL)"
                    path="csv_signal_source"
                >
                    <n-input
                        v-model:value="signal.csvsignal_source"
                        placeholder="/path/to/trades.csv or https://example.com/trades.csv"
                    />
                </n-form-item>
                <template v-else>
                    <n-form-item label="Paste CSV text" path="csv_signal_inline">
                        <n-input
                            v-model:value="signal.csvsignal_inline"
                            type="textarea"
                            :autosize="{
                                minRows: 6,
                                maxRows: 16,
                            }"
                            placeholder="date;symbol;price;amount&#10;18/08/2025 19:32:00;BTC/USDC;117644.41;0.00099153"
                        />
                    </n-form-item>
                    <n-form-item label="CSV file upload">
                        <n-flex align="center" :size="10">
                            <input
                                ref="csvSignalFileInput"
                                type="file"
                                accept=".csv,text/csv"
                                style="display: none;"
                                @change="onCsvFileSelected"
                            />
                            <n-button
                                secondary
                                type="primary"
                                @click="openCsvSignalFilePicker"
                            >
                                Upload CSV file
                            </n-button>
                            <n-text v-if="signal.csvsignal_file_name" depth="3">
                                Loaded: {{ signal.csvsignal_file_name }}
                            </n-text>
                        </n-flex>
                    </n-form-item>
                </template>
            </template>

            <template v-if="signal.signal !== 'csv_signal'">
                <n-form-item
                    label="Signal initial buy strategy"
                    path="selectValue"
                    label-placement="left"
                >
                    <n-checkbox v-model:checked="signal.strategy_enabled" />
                </n-form-item>
                <template v-if="signal.strategy_enabled">
                    <n-form-item label="Strategy" path="strategy">
                        <n-select
                            v-model:value="signal.strategy"
                            placeholder="Select"
                            :options="signal.strategy_plugins"
                        />
                    </n-form-item>
                </template>
            </template>
        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type {
    MixedSelectOption,
    SignalEditorModel,
} from '../../config-editor/types'

defineProps<{
    asapMissingFieldsLabel: string
    isAsapExchangeReady: boolean
    onAsapUrlInput: (value: string) => void
    onCsvFileSelected: (event: Event) => void | Promise<void>
    onFetchAsapSymbols: () => void | Promise<void>
    onSignalSettingsSelect: () => void
    rules: FormRules
    signal: SignalEditorModel
    symsignals: MixedSelectOption[]
}>()

const formRef = ref<FormInst | null>(null)
const csvSignalFileInput = ref<HTMLInputElement | null>(null)

function openCsvSignalFilePicker(): void {
    csvSignalFileInput.value?.click()
}

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
