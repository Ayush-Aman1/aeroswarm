import { decodeSnapshot } from './protocol.js';

// WebSocket client: binary frames -> onSnapshot, text frames -> onMessage; commands return the ack promise.
export class Net {
  constructor({ onSnapshot, onMessage, onStatus, url } = {}) {
    this.onSnapshot = onSnapshot || (() => {});
    this.onMessage = onMessage || (() => {});
    this.onStatus = onStatus || (() => {});
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    this.url = url || `${proto}://${location.host}/ws`;
    this.nextId = 1;
    this.pending = new Map();
    this.connect();
  }

  connect() {
    this.ws = new WebSocket(this.url);
    this.ws.binaryType = 'arraybuffer';
    this.ws.onopen = () => this.onStatus('connected');
    this.ws.onclose = () => { this.onStatus('disconnected'); setTimeout(() => this.connect(), 1500); };
    this.ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'ack' && this.pending.has(msg.id)) { this.pending.get(msg.id)(msg); this.pending.delete(msg.id); }
        this.onMessage(msg);
      } else {
        try { this.onSnapshot(decodeSnapshot(ev.data)); } catch (e) { console.error('bad snapshot', e); }
      }
    };
  }

  send(cmd, fields = {}) {
    const id = this.nextId++;
    return new Promise((resolve) => {
      this.pending.set(id, resolve);
      if (this.ws.readyState !== WebSocket.OPEN) { this.pending.delete(id); resolve({ ok: false, reason: 'not connected' }); return; }
      this.ws.send(JSON.stringify({ cmd, id, ...fields }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); resolve({ ok: false, reason: 'timeout' }); } }, 10000);
    });
  }
}
