// Playback cancellation detaches the listener; an already started request finishes once.
export class AudioCache {
  constructor(read, write) { this.read=read; this.write=write; this.entries=new Map(); this.warning=''; }
  get(text, voice, rate, load) {
    const key=JSON.stringify([1,text,voice,rate]);
    if (!this.entries.has(key)) {
      const entry={};
      entry.promise=(async()=>{
        let saved;
        try { saved=await this.read(key); } catch { this.warning='Audio is cached only for this session because browser storage is unavailable.'; }
        if (saved) { entry.saved=true;return saved; }
        const value=await load();
        try { await this.write(key,value);entry.saved=true; } catch { this.warning='Audio is cached only for this session because browser storage is unavailable.'; }
        return value;
      })().then(value=>{
        entry.done=true;
        for(const [oldKey,old] of this.entries) {
          if(this.entries.size<=32)break;
          if(old.done&&old.saved)this.entries.delete(oldKey);
        }
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
  retryFailed() { for(const [key,entry] of this.entries) if(entry.failed) this.entries.delete(key); }
}
