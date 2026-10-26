import test from 'node:test'
import assert from 'node:assert/strict'
import { selectableAudioModels, hasSubtitleTimestamps } from './asrModels.js'

test('music model remains selectable before weights are downloaded', () => {
  const music = { id: 21, task: 'audio-text-to-text', library: 'moss-music-gguf', status: '0', runtimeReady: false }
  assert.deepEqual(selectableAudioModels([music]), [music])
})
test('unsupported audio models and disabled models are excluded', () => {
  assert.deepEqual(selectableAudioModels([
    { library: 'transformers', task: 'audio-text-to-text', filePath: 'other', status: '0' },
    { library: 'moss-music-gguf', status: '1' },
    { library: 'funasr', status: '0' },
  ]), [])
})
test('existing ASR models and independent service remain selectable', () => {
  const rows = [
    { library: 'funasr-onnx', task: 'automatic-speech-recognition', filePath: 'sensevoice', status: '0' },
    { library: 'confucius-r2t2', task: 'automatic-speech-recognition', status: '0' },
  ]
  assert.deepEqual(selectableAudioModels(rows), rows)
})
test('music text must not enable subtitle export or fake a time range', () => {
  assert.equal(hasSubtitleTimestamps({ text: 'lyrics', timestampsAvailable: false }), false)
  assert.equal(hasSubtitleTimestamps({ segments: [{ start: 0, end: 1, text: 'hi' }] }), true)
})
