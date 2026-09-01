import test from 'node:test'
import assert from 'node:assert/strict'

import {
  pickRecommendedModel,
  recommendedModelId,
  isRecommendedModel,
} from './trackModelRecommendation.js'

const model = (id, modelKey, modelName = modelKey, extra = {}) => ({
  id,
  modelKey,
  modelName,
  status: '0',
  filePath: `${modelKey}.pt`,
  ...extra,
})

test('general tracking prefers the balanced YOLO26s model', () => {
  const models = [model(1, 'yolo11n'), model(2, 'yolo26s'), model(3, 'yolo26n')]
  assert.equal(recommendedModelId(models, 'general'), 2)
})

test('vehicle tracking prefers a vehicle-specific model over a general model', () => {
  const models = [
    model(1, 'yolo26s', '通用检测'),
    model(2, 'traffic-yolo11s', '车辆交通检测', { category: '车辆' }),
  ]
  assert.equal(pickRecommendedModel(models, 'vehicle')?.id, 2)
})

test('absence face recognition prefers Buffalo-L', () => {
  const models = [model(1, 'buffalo_s'), model(2, 'buffalo_l')]
  assert.equal(recommendedModelId(models, 'face'), 2)
  assert.equal(isRecommendedModel(models[1], models, 'face'), true)
})

test('recommendation ignores disabled models and keeps a stable fallback', () => {
  const disabled = model(1, 'yolo26s', 'YOLO26s', { status: '1' })
  const fallback = model(2, 'custom-detector')
  assert.equal(recommendedModelId([disabled, fallback], 'general'), 2)
  assert.equal(recommendedModelId([], 'general'), null)
})
