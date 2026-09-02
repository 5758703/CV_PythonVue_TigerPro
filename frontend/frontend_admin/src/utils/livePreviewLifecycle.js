export function createLivePreviewLifecycle({ requestFrame, cancelFrame }) {
  let generation = 0
  let frameId = null

  const stopLoop = () => {
    if (frameId != null) cancelFrame(frameId)
    frameId = null
  }

  const beginOpen = () => {
    generation += 1
    stopLoop()
    return generation
  }

  const isCurrent = (token) => token === generation

  const startLoop = (token, draw) => {
    stopLoop()
    const tick = () => {
      if (!isCurrent(token)) return
      draw()
      frameId = requestFrame(tick)
    }
    frameId = requestFrame(tick)
  }

  const invalidate = () => {
    generation += 1
    stopLoop()
  }

  return { beginOpen, isCurrent, startLoop, stopLoop, invalidate }
}
