import axios from 'axios'
import { buildMoonwalkerApiUrl } from '../helpers/configEditorDefaults'
import { MOONWALKER_CLIENT_HEADER, MOONWALKER_CLIENT_HEADER_VALUE } from './client'
import type { AccumulationCommand, AccumulationCommandResult, AccumulationDetail, AccumulationPage, AccumulationStrategyPage, AccumulationParameters } from '../types/accumulation'
export async function fetchAccumulationStrategies(afterId = 0): Promise<AccumulationStrategyPage> {
  return (await axios.get<AccumulationStrategyPage>(buildMoonwalkerApiUrl('/accumulation/strategies'), {
    params: { after_id: afterId, limit: 50 },
  })).data
}

export async function saveAccumulationStrategy(payload: { operation_id: string; name: string; parameters: AccumulationParameters }): Promise<{ id: number; name: string; version: number }> {
  return (await axios.post(buildMoonwalkerApiUrl('/accumulation/strategies'), payload,
    { headers: { [MOONWALKER_CLIENT_HEADER]: MOONWALKER_CLIENT_HEADER_VALUE } },
  )).data
}

export async function fetchAccumulationPage(after?: string): Promise<AccumulationPage> {
  return (await axios.get<AccumulationPage>(buildMoonwalkerApiUrl('/accumulation/activations'), {
    params: { limit: 25, after },
  })).data
}

export async function fetchAccumulationDetail(symbol: string): Promise<AccumulationDetail> {
  return (await axios.get<AccumulationDetail>(buildMoonwalkerApiUrl('/accumulation/activation'), {
    params: { symbol },
  })).data
}

export async function sendAccumulationCommand(command: AccumulationCommand): Promise<AccumulationCommandResult> {
  const entry = ['retry_entry', 'correct_import', 'abandon_entry'].includes(command.action)
  return (await axios.post<AccumulationCommandResult>(
    buildMoonwalkerApiUrl(['repair_order', 'retire_command', 'rebind_account', 'adjust_inventory', 'declare_ownership', 'acknowledge_settlement', 'restore_inventory'].includes(command.action) ? '/accumulation/repair' : entry ? '/accumulation/entry/commands' : '/accumulation/commands'),
    command,
    { headers: { [MOONWALKER_CLIENT_HEADER]: MOONWALKER_CLIENT_HEADER_VALUE } },
  )).data
}

export function accumulationErrorStatus(error: unknown): number | undefined {
  return axios.isAxiosError(error) ? error.response?.status : undefined
}
