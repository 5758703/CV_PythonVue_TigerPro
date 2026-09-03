export function applyNodeConfig(nodes, selectedId, config, currentCameraId) {
  const selected = nodes.find((node) => node.id === selectedId)
  const nextCameraId = selected?.data?.nodeType === 'source.rtsp'
    ? Number(config.cameraId)
    : currentCameraId

  return {
    nodes: nodes.map((node) => (
      node.id === selectedId
        ? { ...node, data: { ...node.data, config: { ...config } } }
        : node
    )),
    cameraId: nextCameraId,
  }
}
