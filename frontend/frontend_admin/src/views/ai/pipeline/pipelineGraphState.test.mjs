import assert from 'node:assert/strict'
import test from 'node:test'

import { applyNodeConfig } from './pipelineGraphState.js'

test('修改 RTSP 节点 cameraId 时同步页面级摄像头值', () => {
  const nodes = [
    { id: 'source-1', data: { nodeType: 'source.rtsp', config: { cameraId: 1 } } },
    { id: 'detect-1', data: { nodeType: 'detect.yolo', config: { conf: 0.35 } } },
  ]

  const result = applyNodeConfig(nodes, 'source-1', { cameraId: 8 }, 1)

  assert.equal(result.cameraId, 8)
  assert.equal(result.nodes[0].data.config.cameraId, 8)
  assert.equal(result.nodes[1], nodes[1])
})

test('修改非视频源节点时保留页面级摄像头值', () => {
  const nodes = [
    { id: 'source-1', data: { nodeType: 'source.rtsp', config: { cameraId: 3 } } },
    { id: 'detect-1', data: { nodeType: 'detect.yolo', config: { conf: 0.35 } } },
  ]

  const result = applyNodeConfig(nodes, 'detect-1', { conf: 0.5 }, 3)

  assert.equal(result.cameraId, 3)
  assert.equal(result.nodes[1].data.config.conf, 0.5)
})
