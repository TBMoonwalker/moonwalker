/**
 * Delisting-schedule capability per exchange.
 *
 * Mirrors the backend routing in ``service/delisting_protection.py``
 * (``_provider_for``):
 *
 * - **Binance** uses its own authenticated delisting schedule and is
 *   *fail-closed* — an unverified schedule blocks new buys.
 * - **Bybit** and **Bybit EU** use a public, unauthenticated announcement
 *   feed that is *advisory* — a failed check degrades to CCXT market status
 *   and never blocks.
 * - Exchanges without a known source expose no delisting option at all.
 */

export type DelistingScheduleKind = 'binance' | 'bybit' | 'none'

const DELISTING_KIND_BY_EXCHANGE: Record<string, DelistingScheduleKind> = {
     binance: 'binance',
     bybit: 'bybit',
     bybiteu: 'bybit',
}

/**
 * Resolve the delisting schedule kind for a selected exchange.
 *
 * Args:
 *     name: The configured CCXT exchange id (for example
 *        ``binance``, ``bybit``, or ``bybiteu``).
 *
 * Returns:
 *     The schedule kind, or ``'none'`` when the exchange has no supported
 *     delisting source and the UI should show nothing.
 */
export function delistingScheduleKindForExchange(
     name: string | null | undefined,
): DelistingScheduleKind {
     if (!name) {
         return 'none'
      }
     return DELISTING_KIND_BY_EXCHANGE[String(name).trim().toLowerCase()] ?? 'none'
}

/**
 * Whether the selected exchange exposes a delisting protection option.
 *
 * Args:
 *     name: The configured CCXT exchange id.
 *
 * Returns:
 *     ``true`` when a delisting schedule source is available.
 */
export function exchangeSupportsDelistingProtection(
     name: string | null | undefined,
): boolean {
     return delistingScheduleKindForExchange(name) !== 'none'
}

/**
 * Operator-facing description of how delisting protection behaves for a given
 * schedule kind, shared so the UI and any future surface stay consistent.
 */
export const DELISTING_PROTECTION_DESCRIPTION: Record<
     DelistingScheduleKind,
     string
> = {
     binance:
          'Blocks base orders, safety orders, and re-entries when the exchange '
          + 'reports a scheduled delisting or an inactive market. Binance is '
          + 'fail-closed: an unverified schedule blocks new buys. Existing '
          + 'exits remain enabled.',
     bybit:
          'Blocks base orders, safety orders, and re-entries when a scheduled '
          + 'delisting or an inactive market is detected. Bybit uses a public '
          + 'announcement feed, so a feed failure only degrades to CCXT market '
          + 'status and never blocks trading. Existing exits remain enabled.',
     none: '',
}
