<template>
    <n-card title="Exchange settings">
        <n-form
            ref="formRef"
            :model="exchange"
            :rules="rules"
            label-width="auto"
            require-mark-placement="right-hanging"
            :style="{
                maxWidth: '640px',
            }"
        >
            <n-form-item label="Timezone" path="timezone">
                <n-select
                    v-model:value="exchange.timezone"
                    placeholder="Select"
                     :options="timezone"
                    filterable
                />
            </n-form-item>
            <n-form-item label="Exchange" path="name">
                <n-select
                    v-model:value="exchange.name"
                    placeholder="Select"
                    :options="exchanges"
                />
            </n-form-item>
            <n-form-item label="Timerange" path="timeframe">
                <n-select
                    v-model:value="exchange.timeframe"
                    placeholder="Select"
                    :options="timerange"
                />
            </n-form-item>
            <n-form-item label="Key" path="key">
                <n-input
                    v-model:value="exchange.key"
                    type="password"
                    show-password-on="click"
                    placeholder="Exchange Key"
                />
            </n-form-item>
            <n-form-item label="Secret" path="secret">
                <n-input
                    v-model:value="exchange.secret"
                    type="password"
                    show-password-on="click"
                    placeholder="Exchange Secret"
                />
            </n-form-item>
            <n-form-item
                v-if="showAdvancedGeneral"
                label="Exchange Hostname"
                path="exchange_hostname"
            >
                <n-input
                    v-model:value="exchange.exchange_hostname"
                    placeholder="e.g. bybit.eu"
                />
            </n-form-item>
            <n-form-item label="Dry Run (Demo Trading)" path="dryrun" label-placement="left">
                <n-flex vertical :size="6">
                    <n-checkbox
                        v-model:checked="exchange.dry_run"
                        :disabled="dryRunActivationLocked"
                    />
                    <n-text v-if="dryRunActivationLocked" depth="3">
                        Activate live trading from Overview after saving the rest of
                        this configuration.
                    </n-text>
                </n-flex>
            </n-form-item>
            <n-form-item label="Currency" path="currency">
                <n-select
                    v-model:value="exchange.currency"
                    placeholder="Select"
                    :options="currency"
                />
            </n-form-item>
            <n-form-item label="Market" path="market">
                <n-select
                    v-model:value="exchange.market"
                    placeholder="Select"
                    :options="market"
                />
            </n-form-item>
            <n-form-item label="Use OHCLV" path="watcher" label-placement="left">
                <n-checkbox v-model:checked="exchange.watcher_ohlcv" />
            </n-form-item>

             <template v-if="delistingKind !== 'none'">
                  <n-form-item
                       label="Protect against delisting"
                       path="delisting_protection_enabled"
                       label-placement="left"
                  >
                       <n-flex vertical :size="4">
                           <n-switch
                               v-model:value="exchange.delisting_protection_enabled"
                               aria-label="Protect new exposure against delisting"
                           />
                           <n-text depth="3">{{ delistingDescription }}</n-text>
                       </n-flex>
                  </n-form-item>

                  <template v-if="exchange.delisting_protection_enabled">
                       <template v-if="delistingKind === 'binance'">
                           <n-alert type="info" title="Binance schedule credentials">
                               Delisting checks always use an isolated production client.
                               Dedicated read-only credentials are safer. Reused trading
                               credentials must also be valid on production Binance.
                           </n-alert>
                           <n-form-item
                               label="Use trading API credentials"
                               path="delisting_schedule_use_trading_credentials"
                               label-placement="left"
                           >
                               <n-flex vertical :size="4">
                                   <n-switch
                                       v-model:value="
                                           exchange.delisting_schedule_use_trading_credentials
                                       "
                                       aria-label="Use trading API credentials for delisting checks"
                                   />
                                   <n-text depth="3">
                                       Reuses the API key and secret from Exchange settings.
                                       No trading or withdrawal request is made by the
                                       delisting checker.
                                   </n-text>
                               </n-flex>
                           </n-form-item>
                           <template
                               v-if="
                                   !exchange.delisting_schedule_use_trading_credentials
                               "
                           >
                               <n-form-item
                                   label="Binance schedule API key"
                                   path="delisting_schedule_api_key"
                               >
                                   <n-input
                                       v-model:value="exchange.delisting_schedule_api_key"
                                       type="password"
                                       show-password-on="click"
                                       autocomplete="off"
                                       placeholder="Production read-only API key"
                                   />
                               </n-form-item>
                               <n-form-item
                                   label="Binance schedule API secret"
                                   path="delisting_schedule_api_secret"
                               >
                                   <n-input
                                       v-model:value="exchange.delisting_schedule_api_secret"
                                       type="password"
                                       show-password-on="click"
                                       autocomplete="off"
                                       placeholder="Production read-only API secret"
                                   />
                               </n-form-item>
                           </template>
                       </template>
                       <template v-if="delistingKind === 'bybit'">
                           <n-alert
                               type="info"
                               title="Bybit schedule source"
                           >
                               Bybit and Bybit EU delisting checks use a public,
                               unauthenticated announcement feed. No credentials are
                               required. If the feed cannot be verified, protection
                               degrades to CCXT market status and never blocks trading.
                           </n-alert>
                       </template>
                  </template>
             </template>

        </n-form>
    </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { FormInst, FormRules } from 'naive-ui/es/form'
import type { ExchangeModel, StringSelectOption } from '../../config-editor/types'
import {
    DELISTING_PROTECTION_DESCRIPTION,
    delistingScheduleKindForExchange,
} from '../../helpers/delistingCapability'

const { exchange } = defineProps<{
    currency: StringSelectOption[]
    timezone: StringSelectOption[]
    dryRunActivationLocked: boolean
    exchange: ExchangeModel
    exchanges: StringSelectOption[]
    market: StringSelectOption[]
    rules: FormRules
    showAdvancedGeneral: boolean
    timerange: StringSelectOption[]
}>()

const formRef = ref<FormInst | null>(null)

const delistingKind = computed(() =>
     delistingScheduleKindForExchange(exchange.name),
)

const delistingDescription = computed(
        () => DELISTING_PROTECTION_DESCRIPTION[delistingKind.value],
)

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
