import { computed, h, ref, type Ref } from 'vue'
import { NDatePicker } from 'naive-ui/es/date-picker'
import { NInputNumber } from 'naive-ui/es/input-number'
import { NSlider } from 'naive-ui/es/slider'
import { useDialog } from 'naive-ui/es/dialog'
import { useMessage } from 'naive-ui/es/message'

import { fetchJson, MOONWALKER_OPERATION_HEADER } from '../api/client'
import { extractApiErrorMessage } from '../helpers/apiErrors'
import {
    calculateSoPercentage,
    clampToRange,
    floorToDecimals,
    formatOrderAmount,
    formatPrice,
    getPreviousBuyPrice,
    roundToDecimals,
    snapToMarkers,
    splitTradeSymbol,
    toFiniteNonNegative,
    type OpenTradeRow,
} from '../helpers/openTrades'
import {
    createOrderOperationRegistry,
    orderMutationApplied,
    orderMutationFailureMessage,
    orderMutationRequiresReconciliation,
    type OrderMutationResponse,
} from '../helpers/orderMutations'

interface UseOpenTradeActionsOptions {
    availableFunds: Ref<number>
    dialog: ReturnType<typeof useDialog>
    message: ReturnType<typeof useMessage>
}

export function useOpenTradeActions(options: UseOpenTradeActionsOptions) {
    const operationRegistry = createOrderOperationRegistry()

    function handleDealSell(data: OpenTradeRow): void {
        const d = options.dialog.warning({
            title: 'Selling deal',
            content: `Do you like to sell ${data.amount} ${data.symbol} ?`,
            positiveText: 'Sell',
            negativeText: 'Do not sell',
            onPositiveClick: async () => {
                d.loading = true
                const [symbol, currency] = splitTradeSymbol(
                    data.symbol.toLowerCase(),
                )
                const operationKey = `manual_sell:${data.deal_id || data.symbol}`
                const operationId = operationRegistry.acquire(
                    operationKey,
                    'manual_sell',
                )
                try {
                    const result = await fetchJson<OrderMutationResponse>(
                        `/orders/sell/${symbol}-${currency}`,
                        {
                            method: 'POST',
                            headers: {
                                [MOONWALKER_OPERATION_HEADER]: operationId,
                            },
                        },
                    )
                    const requiresReconciliation =
                        orderMutationRequiresReconciliation(result)
                    if (orderMutationApplied(result, 'sell')) {
                        operationRegistry.release(operationKey)
                        options.message.success(
                            `Sold ${data.amount} ${data.symbol}`,
                        )
                    } else {
                        if (!requiresReconciliation) {
                            operationRegistry.release(operationKey)
                        }
                        options.message.error(
                            orderMutationFailureMessage(
                                result,
                                `Failed to sell ${data.amount} ${data.symbol}`,
                            ),
                            requiresReconciliation
                                ? { duration: 0, closable: true }
                                : undefined,
                        )
                        return !requiresReconciliation
                    }
                } catch (error) {
                    d.loading = false
                    options.message.error(
                        `${extractApiErrorMessage(error, 'The sell request did not return a result.')} Do not submit a new order. Retry this action to reuse operation ID: ${operationId}`,
                        { duration: 0, closable: true },
                    )
                    return false
                }
            },
            onNegativeClick: () => {
                options.message.error('Cancelled')
            },
        })
    }

    function handleDealBuy(data: OpenTradeRow): void {
        const [symbol, currency] = splitTradeSymbol(data.symbol.toLowerCase())
        const maxAmount = floorToDecimals(
            toFiniteNonNegative(options.availableFunds.value),
            2,
        )
        if (maxAmount <= 0) {
            options.message.error(`No available ${currency.toUpperCase()} funds`)
            return
        }
        const amount = ref(maxAmount)
        const marks = {
            0: '0%',
            [roundToDecimals(maxAmount * 0.25, 2)]: '25%',
            [roundToDecimals(maxAmount * 0.5, 2)]: '50%',
            [roundToDecimals(maxAmount * 0.75, 2)]: '75%',
            [maxAmount]: '100%',
        }
        const markerValues = Object.keys(marks)
            .map((key) => Number(key))
            .filter((value) => Number.isFinite(value))
        const snapTolerance = Math.max(
            0.02,
            roundToDecimals(maxAmount * 0.015, 2),
        )
        const d = options.dialog.info({
            title: 'Adding funds',
            content: () =>
                h(
                    'div',
                    {
                        style: 'display:flex; flex-direction:column; gap:10px; min-width:260px;',
                    },
                    [
                        h(
                            'div',
                            { style: 'font-size:12px; opacity:0.75;' },
                            `Available ${currency.toUpperCase()}: ${formatOrderAmount(maxAmount)}`,
                        ),
                        h(NSlider, {
                            min: 0,
                            max: maxAmount,
                            step: 0.01,
                            marks,
                            value: amount.value,
                            'onUpdate:value': (
                                value: number | [number, number],
                            ) => {
                                const resolved = Array.isArray(value)
                                    ? Number(value[0])
                                    : Number(value)
                                const clamped = roundToDecimals(
                                    clampToRange(resolved, 0, maxAmount),
                                    2,
                                )
                                amount.value = snapToMarkers(
                                    clamped,
                                    markerValues,
                                    snapTolerance,
                                )
                            },
                        }),
                        h(NInputNumber, {
                            min: 0,
                            max: maxAmount,
                            step: 0.01,
                            precision: 2,
                            value: amount.value,
                            placeholder: `Add amount in ${currency.toUpperCase()}`,
                            'onUpdate:value': (value: number | null) => {
                                amount.value = roundToDecimals(
                                    clampToRange(
                                        Number(value ?? 0),
                                        0,
                                        maxAmount,
                                    ),
                                    2,
                                )
                            },
                        }),
                    ],
                ),
            positiveText: 'Add funds',
            negativeText: 'Cancel',
            onPositiveClick: async () => {
                d.loading = true
                const finalAmount = roundToDecimals(
                    clampToRange(amount.value, 0, maxAmount),
                    2,
                )
                if (finalAmount <= 0) {
                    d.loading = false
                    options.message.error(
                        `Amount must be greater than 0 ${currency.toUpperCase()}`,
                    )
                    return false
                }
                const orderAmount = formatOrderAmount(finalAmount)
                const operationKey = `manual_buy:${data.deal_id || data.symbol}`
                const operationId = operationRegistry.acquire(
                    operationKey,
                    'manual_buy',
                )
                try {
                    const result = await fetchJson<OrderMutationResponse>(
                        `/orders/buy/${symbol}-${currency}/${orderAmount}`,
                        {
                            method: 'POST',
                            headers: {
                                [MOONWALKER_OPERATION_HEADER]: operationId,
                            },
                        },
                    )
                    const requiresReconciliation =
                        orderMutationRequiresReconciliation(result)
                    if (orderMutationApplied(result, 'new_so')) {
                        operationRegistry.release(operationKey)
                        options.message.success(
                            `Added ${orderAmount} ${currency.toUpperCase()} for ${symbol.toUpperCase()}`,
                        )
                    } else {
                        if (!requiresReconciliation) {
                            operationRegistry.release(operationKey)
                        }
                        options.message.error(
                            orderMutationFailureMessage(
                                result,
                                `Failed to add ${orderAmount} ${currency.toUpperCase()} for ${symbol.toUpperCase()}`,
                            ),
                            requiresReconciliation
                                ? { duration: 0, closable: true }
                                : undefined,
                        )
                        return !requiresReconciliation
                    }
                } catch (error) {
                    d.loading = false
                    options.message.error(
                        `${extractApiErrorMessage(error, 'The buy request did not return a result.')} Do not submit a new order. Retry this action to reuse operation ID: ${operationId}`,
                        { duration: 0, closable: true },
                    )
                    return false
                }
            },
            onNegativeClick: () => {
                options.message.error('Cancelled')
            },
        })
    }

    function handleAddManualBuy(data: OpenTradeRow): void {
        const symbol = String(data.symbol || '').toUpperCase()
        const previousPrice = getPreviousBuyPrice(data)
        const price = ref(
            previousPrice > 0 ? previousPrice : Number(data.current_price) || 0,
        )
        const amount = ref<number | null>(null)
        const timestampMs = ref<number | null>(Date.now())

        const orderSize = computed(() => {
            const localPrice = Number(price.value ?? 0)
            const localAmount = Number(amount.value ?? 0)
            if (!Number.isFinite(localPrice) || !Number.isFinite(localAmount)) {
                return 0
            }
            return localPrice * localAmount
        })
        const soPercentage = computed(() =>
            calculateSoPercentage(Number(price.value ?? 0), previousPrice),
        )

        const d = options.dialog.info({
            title: `Add order manually for ${symbol}`,
            content: () =>
                h(
                    'div',
                    {
                        style: 'display:flex; flex-direction:column; gap:10px; min-width:300px;',
                    },
                    [
                        h(
                            'div',
                            { style: 'font-size:12px; opacity:0.75;' },
                            `Previous buy price: ${formatPrice(previousPrice)}`,
                        ),
                        h(NDatePicker, {
                            value: timestampMs.value,
                            type: 'datetime',
                            clearable: false,
                            'onUpdate:value': (value: number | null) => {
                                timestampMs.value = value
                            },
                        }),
                        h(NInputNumber, {
                            value: price.value,
                            min: 0.00000001,
                            precision: 8,
                            placeholder: 'Price',
                            'onUpdate:value': (value: number | null) => {
                                price.value = Number(value ?? 0)
                            },
                        }),
                        h(NInputNumber, {
                            value: amount.value,
                            min: 0.00000001,
                            precision: 8,
                            placeholder: 'Amount',
                            'onUpdate:value': (value: number | null) => {
                                amount.value = value
                            },
                        }),
                        h(
                            'div',
                            { style: 'font-size:12px; opacity:0.85;' },
                            `Order size: ${formatPrice(orderSize.value)}`,
                        ),
                        h(
                            'div',
                            { style: 'font-size:12px; opacity:0.85;' },
                            `SO %: ${soPercentage.value.toFixed(2)}%`,
                        ),
                    ],
                ),
            positiveText: 'Add order manually',
            negativeText: 'Cancel',
            onPositiveClick: async () => {
                d.loading = true
                const finalTimestamp = Number(timestampMs.value ?? 0)
                const finalPrice = Number(price.value ?? 0)
                const finalAmount = Number(amount.value ?? 0)
                if (!Number.isFinite(finalTimestamp) || finalTimestamp <= 0) {
                    d.loading = false
                    options.message.error('Please enter a valid date')
                    return false
                }
                if (!Number.isFinite(finalPrice) || finalPrice <= 0) {
                    d.loading = false
                    options.message.error('Please enter a valid price')
                    return false
                }
                if (!Number.isFinite(finalAmount) || finalAmount <= 0) {
                    d.loading = false
                    options.message.error('Please enter a valid amount')
                    return false
                }
                try {
                    const result = await fetchJson<{
                        result: string
                        data?: { so_percentage?: number }
                    }>('/orders/buy/manual', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            symbol,
                            date: finalTimestamp,
                            price: finalPrice,
                            amount: finalAmount,
                        }),
                    })
                    if (result.result === 'manual_so') {
                        const effectiveSo = Number(
                            result.data?.so_percentage ?? soPercentage.value,
                        )
                        options.message.success(
                            `Added manual order for ${symbol} (${formatPrice(finalAmount)} at ${formatPrice(finalPrice)}, SO ${effectiveSo.toFixed(2)}%)`,
                        )
                    } else {
                        options.message.error(
                            `Failed to add manual order for ${symbol}`,
                        )
                    }
                } catch (error) {
                    d.loading = false
                    options.message.error(String(error))
                    return false
                }
                return true
            },
            onNegativeClick: () => {
                options.message.error('Cancelled')
            },
        })
    }

    function handleDealStop(data: OpenTradeRow): void {
        const d = options.dialog.warning({
            title: 'Stopping deal',
            content: `Do you like to stop the deal for ${data.symbol} ?`,
            positiveText: 'Stop',
            negativeText: 'Do not stop',
            onPositiveClick: async () => {
                d.loading = true
                const [symbol, currency] = splitTradeSymbol(
                    data.symbol.toLowerCase(),
                )
                const result = await fetchJson<OrderMutationResponse>(
                    `/orders/stop/${symbol}-${currency}`,
                    { method: 'POST' },
                )
                if (orderMutationApplied(result, 'stop')) {
                    options.message.success(
                        `Stopped ${data.symbol} Please trade it manually on your exchange`,
                    )
                } else {
                    options.message.error(
                        orderMutationFailureMessage(
                            result,
                            `Failed to stop ${data.symbol}`,
                        ),
                    )
                }
            },
            onNegativeClick: () => {
                options.message.error('Cancelled')
            },
        })
    }

    return {
        handleAddManualBuy,
        handleDealBuy,
        handleDealSell,
        handleDealStop,
    }
}
