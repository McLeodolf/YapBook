import { SentenceQueue, sentenceParts } from './text.mjs';
import { loadAudio, speechCache, disposeLocalSpeech } from './bridge.mjs';
import { speechProjection } from './reader-text.mjs';

export const SLEEP_MINUTES = [5,10,15,20,30,45,60,90,120];

export class ReaderPlayer {
  constructor(changed, position) {
    this.changed = changed; this.position = position;
    this.audio = new Audio(); this.audio.preload = 'auto';
    this.parts = []; this.index = 0; this.status = 'idle'; this.generation = 0;
    this.settings = {}; this.bytes = 0; this.error = ''; this.sleep = 'off';
    this.audio.ontimeupdate = () => {
      if (this.preview || this.link || !this.current) return;
      const cue = this.current.cues.findLast(cue => cue.time <= this.audio.currentTime) || this.current.cues[0];
      this.cue = cue; this.emit();
    };
    this.audio.onended = () => this.ended();
    this.audio.onerror = () => { if (this.audio.getAttribute('src')) this.fail(new Error('Your browser could not play this audio. Please retry.')); };
    this.clock = setInterval(() => {
      if (this.deadline && Date.now() >= this.deadline) { this.pause(); this.setSleep('off'); }
    }, 1000);
  }
  emit() { this.changed({status:this.status,index:this.index,bytes:this.bytes,error:this.error,cue:this.cue,preview:this.preview,link:this.link?.span,sleep:this.sleep,cacheWarning:speechCache.warning,detail:this.detail}); }
  configure(settings) {
    const changed = this.settings.engine !== settings.engine || this.settings.voice !== settings.voice || this.settings.rate !== settings.rate || this.settings.readCitations !== settings.readCitations;
    const running = ['playing','preparing'].includes(this.status) && !this.preview;
    this.settings = settings; this.audio.volume = settings.volume/100;
    if (changed) { this.projectParts(); this.stop(); if (running && this.parts.length) this.play(); }
  }
  projectParts() {
    this.parts=(this.sourceParts || []).map(part=>({...part,speech:speechProjection(part.text,this.settings.readCitations,part.citations)}));
  }
  resetQueue() {
    this.queue?.cancel();
    this.queue = new SentenceQueue((part,signal) => loadAudio(part,this.settings.voice,this.settings.rate,signal,bytes => {
      if (part === (this.link ? this.link.parts[this.link.index] : this.parts[this.index]) && this.status === 'preparing') { this.bytes = typeof bytes==='number'?bytes:0; this.detail=typeof bytes==='object'?bytes.message:''; this.emit(); }
    },this.settings.engine));
  }
  setDocument(index, position) {
    this.stop(); this.sourceParts = index.parts; this.projectParts();
    this.index = Math.max(0,this.parts.findIndex(part => part.section === position?.section && part.end > position?.start));
    this.emit();
  }
  release() { this.audio.pause(); this.audio.removeAttribute('src'); this.audio.load(); if (this.url) URL.revokeObjectURL(this.url); this.url = null; this.current = null; }
  stop(preserveQueue = false) {
    this.generation++; this.previewController?.abort(); this.preview = false;
    this.link = null;
    clearTimeout(this.transition); if (!preserveQueue) this.resetQueue(); this.release();
    this.status = 'idle'; this.cue = null; this.bytes = 0; this.detail=''; this.error = ''; this.emit();
  }
  pause() {
    this.generation++; clearTimeout(this.transition); this.audio.pause();
    if (this.preview) { this.stop(); return; }
    this.status = 'paused'; this.save(); this.emit();
  }
  save() { const part = this.parts[this.index]; if (part && !this.link) this.position({section:part.section,start:part.start}); }
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
    if (['idle','error'].includes(this.status)) speechCache.retryFailed();
    if (this.status === 'error') this.resetQueue();
    while (!this.link && this.index<this.parts.length && !this.parts[this.index].speech.text) this.index++;
    if (this.index>=this.parts.length) { this.index=Math.max(0,this.parts.length-1);this.status='finished';this.save();this.emit();return; }
    const token = ++this.generation; this.error = ''; this.bytes = 0;
    try {
      if (!(this.status === 'paused' && this.current)) {
        const all=this.link?.parts || this.parts;
        const current=all[this.link?.index ?? this.index];
        const audible=all.filter(part=>!part.speech || part.speech.text);
        const ready=this.queue.ready.get(current.key);
        this.cue = null;
        if (!ready) { this.status = 'preparing'; this.emit(); }
        const result = await this.queue.prepare(audible,audible.indexOf(current));
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
    this.stop(true); this.index = Math.max(0,Math.min(index,this.parts.length-1));
    const audible=this.parts.filter(part=>!part.speech || part.speech.text);
    const target=audible.findIndex(part=>part===this.parts[this.index]);
    if (target>=0) this.queue.retain(audible,target);
    this.save(); this.emit();
    if (play) this.play();
  }
  readLink(text, complete, span) {
    this.stop();
    const marked=span ? (this.sourceParts || []).flatMap(part=>part.section===span.section ? (part.citations || []).map(([a,b])=>[part.start+a-span.start,part.start+b-span.start]) : []) : [];
    const parts = sentenceParts(text).map((part,index) => ({...part,key:`link:${index}`,
      speech:speechProjection(part.text,this.settings.readCitations,marked.map(([a,b])=>[a-part.start,b-part.start]))})).filter(part=>part.speech.text);
    if (!parts.length) { complete(); return; }
    if (span) {
      const source = this.parts.findIndex(part => part.section === span.section && part.end > span.start);
      if (source >= 0) { this.index = source; this.save(); }
    }
    this.link = {parts,index:0,complete,span};
    this.play();
  }
  ended() {
    if (this.status !== 'playing') return;
    if (this.link) {
      if (++this.link.index < this.link.parts.length) {
        this.current = null; this.emit();
        this.transition = setTimeout(() => this.play(),80);
      } else {
        const complete = this.link.complete;
        this.stop(); complete();
      }
      return;
    }
    if (this.preview) { this.stop(); return; }
    if (this.index+1 >= this.parts.length) { this.status = 'finished'; this.save(); this.emit(); return; }
    const previous = this.parts[this.index++]; this.cue = null; this.current = null; this.save();
    if (this.sleep === 'section' && previous.section !== this.parts[this.index].section) {
      this.status = 'paused'; this.setSleep('off'); this.emit(); return;
    }
    // Separate paragraph/heading requests naturally leave a short breath between blocks.
    this.emit();
    this.transition = setTimeout(() => this.play(),previous.section !== this.parts[this.index].section ? 250 : 80);
  }
  setSleep(value) { this.sleep = value; this.deadline = SLEEP_MINUTES.includes(Number(value)) ? Date.now()+Number(value)*60000 : null; this.emit(); }
  async testVoice() {
    speechCache.retryFailed();
    this.stop(); this.preview = true; this.status = 'preparing'; this.emit();
    const token = this.generation, controller = this.previewController = new AbortController();
    try {
      const result = await loadAudio({text:'Welcome to YapBook. Find your voice and enjoy your next chapter.'},this.settings.voice,this.settings.rate,controller.signal,bytes=>{this.bytes=typeof bytes==='number'?bytes:0;this.detail=typeof bytes==='object'?bytes.message:'';this.emit();},this.settings.engine);
      if (token !== this.generation) return;
      this.current = result; this.url = URL.createObjectURL(result.blob); this.audio.src = this.url;
      try { await this.audio.play(); this.status = 'playing'; }
      catch (error) { if (error.name !== 'NotAllowedError') throw error; this.status = 'paused'; this.error = 'Preview ready. Tap Play to listen.'; }
      this.emit();
    } catch (error) { if (token === this.generation) this.fail(error); }
  }
  dispose() { this.stop(); this.queue.cancel(); disposeLocalSpeech(); clearInterval(this.clock); }
}
