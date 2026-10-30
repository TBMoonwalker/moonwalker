import { expect, test, type WebSocket } from '@playwright/test'

// Run with an isolated, credential-free candidate backend on 127.0.0.1:18131,
// allowing origin http://127.0.0.1:4173. Build the frontend with
// VITE_MOONWALKER_API_ORIGIN=http://127.0.0.1:18131 and set
// MOONWALKER_NETWORK_RECOVERY_E2E=1 for Playwright.
test('a returning dashboard reconnects over the real backend without interrupting another client', async ({ browser }) => {
  test.skip(process.env.MOONWALKER_NETWORK_RECOVERY_E2E !== '1', 'Requires the isolated recovery backend')
  test.setTimeout(60_000)
  const context = await browser.newContext()
  await context.addInitScript(() => {
    let hidden = false
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    Object.assign(window, { setTestHidden(value: boolean) {
      hidden = value
      document.dispatchEvent(new Event('visibilitychange'))
    } })
  })
  const first = await context.newPage()
  const second = await context.newPage()
  const firstSockets: WebSocket[] = []
  const secondSockets: WebSocket[] = []
  const firstFrames: string[] = []
  const secondFrames: string[] = []
  const framesBySocket = new Map<WebSocket, string[]>()
  function observe(sockets: WebSocket[], frames: string[]) {
    return (socket: WebSocket) => {
      if (!socket.url().includes('/trades/open')) return
      sockets.push(socket)
      const socketFrames: string[] = []
      framesBySocket.set(socket, socketFrames)
      socket.on('framereceived', event => {
        frames.push(String(event.payload))
        socketFrames.push(String(event.payload))
      })
    }
  }
  first.on('websocket', observe(firstSockets, firstFrames))
  second.on('websocket', observe(secondSockets, secondFrames))
  try {
    await Promise.all([first.goto('/'), second.goto('/')])
    await expect.poll(() => firstFrames.length, { timeout: 15_000 }).toBeGreaterThan(0)
    await expect.poll(() => secondFrames.length, { timeout: 15_000 }).toBeGreaterThan(0)
    expect(JSON.parse(firstFrames.at(-1)!)).toEqual([])
    const secondBeforeReturn = secondFrames.length
    await first.evaluate(() => (window as unknown as { setTestHidden(value: boolean): void }).setTestHidden(true))
    await first.evaluate(() => (window as unknown as { setTestHidden(value: boolean): void }).setTestHidden(false))
    await expect.poll(() => firstSockets.length).toBe(2)
    await expect.poll(() => framesBySocket.get(firstSockets[1])?.length ?? 0, { timeout: 15_000 }).toBeGreaterThan(0)
    expect(JSON.parse(framesBySocket.get(firstSockets[1])!.at(-1)!)).toEqual([])
    expect(secondSockets).toHaveLength(1)
    await expect.poll(() => secondFrames.length, { timeout: 15_000 }).toBeGreaterThan(secondBeforeReturn)
  } finally {
    await context.close()
  }
})
