// Playback cancellation detaches the listener; an already started request finishes once.
export class AudioCache {
  constructor(read, write) { this.read=read; this.write=write; this.entries=new Map(); this.warning=''; }
  get(text, voice, rate, load, engine = 'edge') {
    const key=JSON.stringify(engine==='edge'?[1,text,voice,rate]:[2,engine,text,voice,rate]);
    if (!this.entries.has(key)) {
      const entry={};
      entry.promise=(async()=>{
        let saved;
        try { saved=await this.read(key); } catch { this.warning='Audio is cached only for this session because browser storage is unavailable.'; }
        if (saved) { entry.saved=true;return saved; }
        const value=await load();
        // Playback must not wait for browser persistence after audio is ready.
        // Keep the in-memory entry until the write has actually succeeded.
        entry.persisted=Promise.resolve().then(()=>this.write(key,value)).then(()=>{
          entry.saved=true;this.trim();
        },()=>{this.warning='Audio is cached only for this session because browser storage is unavailable.';});
        return value;
      })().then(value=>{
        entry.done=true;
        this.trim();
        return value;
      });
      entry.promise.catch(error=>{
        entry.failed=true;
        if(error.name==='AbortError' && this.entries.get(key)===entry)this.entries.delete(key);
      });
      this.entries.set(key,entry);
    }
    return this.entries.get(key).promise;
  }
  trim() {
    for(const [key,entry] of this.entries) {
      if(this.entries.size<=32)break;
      if(entry.done&&entry.saved)this.entries.delete(key);
    }
  }
  retryFailed() { for(const [key,entry] of this.entries) if(entry.failed) this.entries.delete(key); }
}
