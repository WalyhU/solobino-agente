// Buffer circular del micrófono; conserva la voz entre ventanas consecutivas.
class WakeAudioBuffer {
  constructor(sampleRate, seconds = 2) {
    this.sampleRate = sampleRate;
    this.data = new Float32Array(Math.ceil(sampleRate * seconds));
    this.write = 0;
    this.length = 0;
  }

  append(samples) {
    for (const sample of samples) {
      this.data[this.write] = sample;
      this.write = (this.write + 1) % this.data.length;
      this.length = Math.min(this.length + 1, this.data.length);
    }
  }

  recent(seconds) {
    const count = Math.round(seconds * this.sampleRate);
    if (count > this.length) return null;
    const out = new Float32Array(count);
    let offset = (this.write - count + this.data.length) % this.data.length;
    for (let i = 0; i < count; i++) {
      out[i] = this.data[offset];
      offset = (offset + 1) % this.data.length;
    }
    return out;
  }
}

function resampleWake(samples, outputLength) {
  const out = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i++) {
    const at = i * (samples.length - 1) / Math.max(outputLength - 1, 1);
    const left = Math.floor(at);
    const mix = at - left;
    out[i] = samples[left] * (1 - mix) + samples[Math.min(left + 1, samples.length - 1)] * mix;
  }
  return out;
}

function wakePcmBase64(samples) {
  const bytes = new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 4096) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 4096));
  }
  return btoa(binary);
}

function wakeWavBase64(samples) {
  const bytes = new Uint8Array(44 + samples.length * 2);
  const view = new DataView(bytes.buffer);
  const label = (offset, value) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  label(0, 'RIFF'); view.setUint32(4, bytes.length - 8, true);
  label(8, 'WAVE'); label(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, 16000, true);
  view.setUint32(28, 32000, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); label(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const value = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true);
  }
  let binary = '';
  for (let i = 0; i < bytes.length; i += 4096) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 4096));
  }
  return btoa(binary);
}

if (typeof module !== 'undefined') {
  module.exports = { WakeAudioBuffer, resampleWake, wakePcmBase64, wakeWavBase64 };
}
