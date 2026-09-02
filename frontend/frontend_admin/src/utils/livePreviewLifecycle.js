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

export function releaseOpenedStream(openedStream, currentStream, video) {
  openedStream?.getTracks?.().forEach((track) => track.stop())
  if (video?.srcObject === openedStream) video.srcObject = null
  return currentStream === openedStream ? null : currentStream
}

export function waitForImageReady(image, { timeoutMs = 15000, signal } = {}) {
  if (image.naturalWidth > 0) return Promise.resolve()
  return new Promise((resolve, reject) => {
    let settled = false
    const abortError = () => {
      const error = new Error('Image readiness aborted')
      error.name = 'AbortError'
      return error
    }
    const cleanup = () => {
      clearInterval(poll)
      clearTimeout(timer)
      image.removeEventListener('load', onLoad)
      image.removeEventListener('error', onError)
      signal?.removeEventListener('abort', onAbort)
    }
    const finish = (error) => {
      if (settled) return
      settled = true
      cleanup()
      error ? reject(error) : resolve()
    }
    const onLoad = () => finish()
    const onError = () => finish(new Error('load'))
    const onAbort = () => finish(abortError())
    const poll = setInterval(() => {
      if (image.naturalWidth > 0) finish()
    }, 200)
    const timer = setTimeout(() => finish(new Error('timeout')), timeoutMs)
    image.addEventListener('load', onLoad)
    image.addEventListener('error', onError)
    signal?.addEventListener('abort', onAbort, { once: true })
    if (signal?.aborted) onAbort()
  })
}
