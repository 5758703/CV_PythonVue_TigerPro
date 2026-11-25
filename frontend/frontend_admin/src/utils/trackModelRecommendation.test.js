import test from 'node:test'
import assert from 'node:assert/strict'

import {
  pickRecommendedModel,
  recommendedModelId,
  isRecommendedModel,
  filterTrackDetectModels,
} from './trackModelRecommendation.js'

const model = (id, modelKey, modelName = modelKey, extra = {}) => ({
  id,
  modelKey,
  modelName,
  status: '0',
  filePath: `${modelKey}.pt`,
  ...extra,
})

test('general tracking prefers the balanced YOLO26s general model', () => {
  const models = [model(1, 'yolo11n'), model(2, 'yolo26s', 'YOLO26s 通用检测'), model(3, 'yolo26n')]
  assert.equal(recommendedModelId(models, 'general'), 2)
})

test('general tracking does not prefer smoking YOLO26s over general YOLO26s', () => {
  const models = [
    model(1, 'yolo26-smoking-detection', '吸烟行为检测（YOLO26s）', { category: '安防检测' }),
    model(2, 'yolo26s', 'YOLO26s 通用检测', { category: '通用目标检测' }),
    model(3, 'yolo11s-ball', 'YOLO11s 羽毛球检测'),
  ]
  assert.equal(pickRecommendedModel(models, 'general')?.id, 2)
})

test('vehicle tracking prefers a vehicle-specific model over a general model', () => {
  const models = [
    model(1, 'yolo26s', '通用检测'),
    model(2, 'traffic-yolo11s', '车辆交通检测', { category: '车辆' }),
  ]
  assert.equal(pickRecommendedModel(models, 'vehicle')?.id, 2)
})

test('vehicle tracking prefers general YOLO26s over smoking detection', () => {
  const models = [
    model(1, 'yolo26-smoking-detection', '吸烟行为检测（YOLO26s）', { category: '安防检测' }),
    model(2, 'yolo26s', 'YOLO26s 通用检测', { category: '通用目标检测' }),
    model(3, 'yolo26n', 'YOLO26n 通用检测'),
  ]
  assert.equal(pickRecommendedModel(models, 'vehicle')?.modelKey, 'yolo26s')
})

test('filterTrackDetectModels drops specialized fine-tunes when general models exist', () => {
  const models = [
    model(1, 'yolo26-smoking-detection', '吸烟行为检测（YOLO26s）'),
    model(2, 'yolo26s', 'YOLO26s 通用检测'),
    model(3, 'fire-smoke-detection', '烟火检测'),
  ]
  const filtered = filterTrackDetectModels(models)
  assert.deepEqual(filtered.map((m) => m.id), [2])
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
