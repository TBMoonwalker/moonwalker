import { ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchJson } from '../api/client'

export interface AnalyticsOverview {
   summary: {
     total_trades: number
     profit_trades: number
     loss_trades: number
     win_rate: number
     total_profit: number
     avg_profit: number
     avg_profit_percent: number
     avg_duration_formatted: string
     total_cost: number
  }
  heatmap_daily: { timestamp: number; value: number }[]
  heatmap_weekly: { timestamp: number; value: number }[]
  per_symbol: {
     symbol: string
     trades: number
     win_rate: number
     total_profit: number
     avg_profit: number
     avg_duration_formatted: string
  }[]
  duration_extremes: {
     longest: Array<{
       symbol: string
       duration_hours: number
       duration_formatted: string
       profit: number
       profit_percent: number
       close_date: string | null
       deal_id: string | null
     }>
     shortest: Array<{
       symbol: string
       duration_hours: number
       duration_formatted: string
       profit: number
       profit_percent: number
       close_date: string | null
       deal_id: string | null
     }>
  }
  drawdown: {
     max_drawdown: number
     max_drawdown_percent: number
  }
  distribution: {
     bins: { label: string; min: number; max: number; count: number }[]
     median: number
     std_dev: number
     best: number
     worst: number
  }
  ai_trust: {
     enabled: boolean
     enforce_warnings: boolean
     configured: boolean
     provider: string
     model_name: string | null
     status: 'disabled' | 'missing_model' | 'ready' | string
     coverage: {
        total: number
        scored: number
        unscored: number
        closed: number
        coverage_rate: number
     }
     quality: {
        warning_hit_rate: number
        false_warning_rate: number
        bad_entry_capture_rate: number
        bad_entries: number
        warnings: number
     }
     provider_status_counts: Record<string, number>
     recent_predictions: AiTrustPrediction[]
     bad_entry_review: AiTrustPrediction[]
  }
}

export interface AiTrustPrediction {
   id: number
   symbol: string
   deal_id: string | null
   created_at: string | null
   source_event: string
   status: string
   provider_status: string
   risk_score: number | null
   confidence: number | null
   would_warn: boolean | null
   warning_severity: string
   reason_codes: string[]
   operator_note: string | null
   outcome_status: string
   bad_entry: boolean | null
   bad_entry_reasons: string[]
   outcome_profit: number | null
   outcome_profit_percent: number | null
   outcome_duration_hours: number | null
   outcome_so_count: number | null
}

export const useAnalyticsStore = defineStore('analytics', () => {
   const data = ref<AnalyticsOverview | null>(null)
   const loading = ref(false)
   const error = ref<string | null>(null)

   async function load() {
     loading.value = true
     error.value = null
     try {
       data.value = await fetchJson<AnalyticsOverview>('/analytics/overview')
      } catch (err: any) {
       error.value = err.message || 'Failed to load analytics'
       data.value = null
      } finally {
       loading.value = false
      }
   }

   return { data, loading, error, load }
 })
