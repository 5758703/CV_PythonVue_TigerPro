import test from 'node:test'
import assert from 'node:assert/strict'
import { selectableAudioModels, hasSubtitleTimestamps, fmtSrtTime, fmtAssTime } from './asrModels.js'

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

const cpuLibraries = ['funasr', 'sherpa-onnx-asr', 'faster-whisper', 'moonshine-streaming']
test('registered CPU ASR options remain visible without weights or dependencies', () => {
  const rows = cpuLibraries.map((library, i) => ({ id: i + 1, library, task: 'automatic-speech-recognition', status: '0', asrCpu: true, runtimeReady: false }))
  assert.deepEqual(selectableAudioModels(rows), rows)
})

test('unregistered CPU library records cannot fall through to a different inference engine', () => {
  const rows = ['sherpa-onnx-asr', 'faster-whisper', 'moonshine-streaming'].map((library) => ({ library, task: 'automatic-speech-recognition', status: '0', filePath: 'models/custom' }))
  assert.deepEqual(selectableAudioModels(rows), [])
})

test('native subtitle fractions carry into the next second, minute and hour', () => {
  assert.equal(fmtSrtTime(1.9996), '00:00:02,000')
  assert.equal(fmtSrtTime(3599.9996), '01:00:00,000')
  assert.equal(fmtAssTime(1.9996), '0:00:02.00')
  assert.equal(fmtAssTime(59.9996), '0:01:00.00')
  assert.equal(fmtSrtTime(NaN), '00:00:00,000')
  assert.equal(fmtAssTime(-1), '0:00:00.00')
})
