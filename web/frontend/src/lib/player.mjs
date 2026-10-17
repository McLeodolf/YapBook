import { SentenceQueue } from './text.mjs';
import { loadAudio } from './bridge.mjs';

export class ReaderPlayer {
  constructor(changed, position) {
    this.changed = changed; this.position = position;
    this.audio = new Audio(); this.audio.preload = 'auto';
    this.parts = []; this.index = 0; this.status = 'idle'; this.generation = 0;
    this.settings = {}; this.bytes = 0; this.error = ''; this.sleep = 'off';
    this.audio.ontimeupdate = () => {
      if (this.preview || !this.current) return;
      const cue = this.current.cues.findLast(cue => cue.time <= this.audio.currentTime) || this.current.cues[0];
      this.cue = cue; this.emit();
    };
    this.audio.onended = () => this.ended();
    this.audio.onerror = () => { if (this.audio.getAttribute('src')) this.fail(new Error('Your browser could not play this audio. Please retry.')); };
    this.clock = setInterval(() => {
      if (this.deadline && Date.now() >= this.deadline) { this.pause(); this.setSleep('off'); }
    }, 1000);
  }
  emit() { this.changed({status:this.status,index:this.index,bytes:this.bytes,error:this.error,cue:this.cue,preview:this.preview,sleep:this.sleep}); }
  configure(settings) {
    const changed = this.settings.voice !== settings.voice || this.settings.rate !== settings.rate;
    const running = ['playing','preparing'].includes(this.status) && !this.preview;
    this.settings = settings; this.audio.volume = settings.volume/100;
    if (changed) { this.stop(); if (running && this.parts.length) this.play(); }
  }
  resetQueue() {
    this.queue?.cancel();
    this.queue = new SentenceQueue((part,signal) => loadAudio(part,this.settings.voice,this.settings.rate,signal,bytes => {
      if (part === this.parts[this.index] && this.status === 'preparing') { this.bytes = bytes; this.emit(); }
    }));
  }
  setDocument(index, position) {
    this.stop(); this.parts = index.parts;
    this.index = Math.max(0,this.parts.findIndex(part => part.section === position?.section && part.end > position?.start));
    this.emit();
  }
  release() { this.audio.pause(); this.audio.removeAttribute('src'); this.audio.load(); if (this.url) URL.revokeObjectURL(this.url); this.url = null; this.current = null; }
  stop() {
    this.generation++; this.previewController?.abort(); this.preview = false;
    clearTimeout(this.transition); this.resetQueue(); this.release();
    this.status = 'idle'; this.cue = null; this.bytes = 0; this.error = ''; this.emit();
  }
  pause() {
    this.generation++; clearTimeout(this.transition); this.audio.pause();
    if (this.preview) { this.stop(); return; }
    this.status = 'paused'; this.save(); this.emit();
  }
  save() { const part = this.parts[this.index]; if (part) this.position({section:part.section,start:part.start}); }
  fail(error) {
    if (error.name === 'AbortError') return;
    this.audio.pause(); this.status = 'error'; this.error = error.message; this.emit();
  }
  async play() {
    if (this.preview && this.status === 'paused' && this.current) {
      try { await this.audio.play(); this.status = 'playing'; this.error = ''; this.emit(); }
      catch { this.error = 'Tap Preview voice to try again.'; this.emit(); }
      return;
    }
    if (!this.parts.length) return;
    if (this.preview) this.stop();
    if (this.status === 'error') this.resetQueue();
    const token = ++this.generation; this.error = ''; this.bytes = 0;
    try {
      if (!(this.status === 'paused' && this.current)) {
        this.status = 'preparing'; this.cue = null; this.emit();
        const result = await this.queue.prepare(this.parts,this.index);
        if (token !== this.generation) return;
        this.release(); this.current = result;
        this.url = URL.createObjectURL(result.blob); this.audio.src = this.url;
      }
      try { await this.audio.play(); }
      catch (error) {
        if (error.name !== 'NotAllowedError') throw error;
        this.status = 'paused'; this.error = 'Audio ready. Tap Play to listen.'; this.emit(); return;
      }
      if (token !== this.generation) { this.audio.pause(); return; }
      this.status = 'playing'; this.save(); this.emit();
    } catch (error) { if (token === this.generation) this.fail(error); }
  }
  jump(index, play = true) {
    if (!this.parts.length) return;
    this.stop(); this.index = Math.max(0,Math.min(index,this.parts.length-1)); this.save(); this.emit();
    if (play) this.play();
  }
  ended() {
    if (this.preview) { this.stop(); return; }
    if (this.index+1 >= this.parts.length) { this.status = 'finished'; this.save(); this.emit(); return; }
    const previous = this.parts[this.index++]; this.cue = null; this.current = null; this.save();
    if (this.sleep === 'section' && previous.section !== this.parts[this.index].section) {
      this.status = 'paused'; this.setSleep('off'); this.emit(); return;
    }
    // Separate paragraph/heading requests naturally leave a short breath between blocks.
    this.status = 'preparing'; this.emit();
    this.transition = setTimeout(() => this.play(),previous.section !== this.parts[this.index].section ? 250 : 80);
  }
  setSleep(value) { this.sleep = value; this.deadline = ['15','30'].includes(value) ? Date.now()+Number(value)*60000 : null; this.emit(); }
  async testVoice() {
    this.stop(); this.preview = true; this.status = 'preparing'; this.emit();
    const token = this.generation, controller = this.previewController = new AbortController();
    try {
      const result = await loadAudio({text:'Welcome to YapBook. Find your voice and enjoy your next chapter.'},this.settings.voice,this.settings.rate,controller.signal,bytes=>{this.bytes=bytes;this.emit();});
      if (token !== this.generation) return;
      this.current = result; this.url = URL.createObjectURL(result.blob); this.audio.src = this.url;
      try { await this.audio.play(); this.status = 'playing'; }
      catch (error) { if (error.name !== 'NotAllowedError') throw error; this.status = 'paused'; this.error = 'Preview ready. Tap Play to listen.'; }
      this.emit();
    } catch (error) { if (token === this.generation) this.fail(error); }
  }
  dispose() { this.stop(); this.queue.cancel(); clearInterval(this.clock); }
}
