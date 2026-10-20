import React, {useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BookOpen,FolderOpen,Library,Play,Pause,Square,SkipBack,SkipForward,Volume2,Gauge,Star,Headphones,RefreshCw,Bookmark,AlignCenter,Minus,Plus,Moon,Sun,X,Trash2,ChevronDown,Check,LoaderCircle,ArrowRight,Search,BrainCircuit} from 'lucide-react';
import {openEpub,indexDocument,textRange,clickedPart,followBookLink} from './lib/epub.mjs';
import {readSettings,saveSettings,listBooks,getBook,putBook,updateBook,deleteBook} from './lib/storage.mjs';
import {request,resizeFrame} from './lib/bridge.mjs';
import {ReaderPlayer,SLEEP_MINUTES} from './lib/player.mjs';
import {KOKORO_VOICES,selectEngine} from './lib/kokoro-config.mjs';
import {searchBook} from './lib/reader-text.mjs';
import './style.css';
import './dark.css';

function IconButton({label,icon:Icon,active=false,...props}) {
  return <button type="button" title={label} aria-label={label} aria-pressed={active || undefined} className={'icon-button'+(active?' active':'')} {...props}><Icon size={19}/></button>;
}
const fallbackVoices = ['en-US-BrianMultilingualNeural','en-US-AndrewMultilingualNeural','en-US-AvaMultilingualNeural','en-US-EmmaMultilingualNeural','de-DE-ConradNeural','de-DE-KatjaNeural'].map(name=>({name,locale:name.slice(0,5)}));
function voiceName(name) { const local=KOKORO_VOICES.find(voice=>voice.name===name);if(local)return local.label+' · Kokoro';return name.replace(/^[a-z]{2,3}-[A-Z]{2}-/,'').replace(/Neural$/,'').replace(/Multilingual/,' · Multilingual'); }

function App() {
  const [settings,setSettings] = useState(readSettings), settingsRef = useRef(settings);
  const [playback,setPlayback] = useState({status:'idle',index:0,bytes:0});
  const [book,setBook] = useState(null), bookRef = useRef(null), [indexed,setIndexed] = useState(null), indexRef = useRef(null);
  const [recent,setRecent] = useState([]), [marks,setMarks] = useState([]), [panel,setPanel] = useState('');
  const [onlineVoices,setVoices] = useState(fallbackVoices), [voiceOpen,setVoiceOpen] = useState(false), [query,setQuery] = useState(''), [language,setLanguage] = useState('all');
  const [loadingVoices,setLoadingVoices] = useState(false), [opening,setOpening] = useState(false), [notice,setNotice] = useState('');
  const [elapsed,setElapsed] = useState(0), [markName,setMarkName] = useState('');
  const [viewportRevision,setViewportRevision] = useState(0);
  const [searchText,setSearchText] = useState(''), [searchTerm,setSearchTerm] = useState(''), [searchPage,setSearchPage] = useState(0);
  const searchInput = useRef();
  const searchHits = useMemo(()=>searchBook(indexed?.sections || [],searchTerm),[indexed,searchTerm]);
  useEffect(()=>{const timer=setTimeout(()=>{setSearchTerm(searchText);setSearchPage(0);},180);return()=>clearTimeout(timer);},[searchText]);
  useEffect(()=>{if(panel==='search')searchInput.current?.focus();},[panel]);
  useEffect(()=>{highlightKey.current='';setViewportRevision(v=>v+1);},[panel,settings.fontSize]);
  useEffect(()=>{
    const key=event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='f'&&bookRef.current){event.preventDefault();setPanel('search');searchInput.current?.focus();}};
    window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);
  },[]);
  const file = useRef(), frame = useRef(), restored = useRef(), openGeneration = useRef(0), highlightKey = useRef('');
  const engine = useRef();
  if (!engine.current) engine.current = new ReaderPlayer(setPlayback,position => {
    if (bookRef.current) updateBook(bookRef.current.id,{position,opened:Date.now()}).catch(error=>setNotice(error.message));
  });
  const player = engine.current;
  const part = indexed?.parts[playback.index];
  const playing = ['playing','preparing'].includes(playback.status);
  const change = patch => setSettings(current=>({...current,...patch}));
  const refreshLibrary = () => listBooks().then(setRecent).catch(error=>setNotice(error.message));
  useEffect(()=>{if(playback.cacheWarning)setNotice(playback.cacheWarning);},[playback.cacheWarning]);

  async function fetchVoices() {
    setLoadingVoices(true);
    try { const result = await request('voices'); setVoices(result.voices); }
    catch (error) { if (error.name !== 'AbortError') setNotice(error.message); }
    finally { setLoadingVoices(false); }
  }
  useEffect(()=>{refreshLibrary(); fetchVoices(); resizeFrame();
    const save = ()=>player.save(); const resize = ()=>{resizeFrame();highlightKey.current='';setViewportRevision(v=>v+1);};
    window.addEventListener('pagehide',save); window.addEventListener('resize',resize); document.addEventListener('visibilitychange',save);
    return ()=>{player.dispose();bookRef.current?.dispose();window.removeEventListener('pagehide',save);window.removeEventListener('resize',resize);document.removeEventListener('visibilitychange',save);};
  },[]);
  useEffect(()=>{settingsRef.current=settings;player.configure(settings);try{saveSettings(settings);}catch{setNotice('Your browser could not save preferences.');}
    document.documentElement.dataset.theme=settings.theme;
    if(frame.current?.contentDocument) {frame.current.contentDocument.documentElement.style.fontSize=settings.fontSize+'px';frame.current.contentDocument.documentElement.dataset.theme=settings.theme;}
  },[settings]);
  useEffect(()=>{if(playback.status!=='preparing'){setElapsed(0);return;}const started=Date.now();const timer=setInterval(()=>setElapsed(Math.floor((Date.now()-started)/1000)),1000);return()=>clearInterval(timer);},[playback.status,playback.index]);
  useEffect(()=>{
    if(!part||!frame.current?.contentDocument||playback.preview)return;
    const doc=frame.current.contentDocument,cue=playback.link?null:playback.cue,shown=playback.link||part;
    const start=shown.start+(cue?.start||0),end=cue?shown.start+cue.end:shown.end,key=`${shown.section}:${start}:${end}`;
    const range=textRange(doc,indexed.sections[shown.section],start,end); if(!range)return;
    if(doc.defaultView.CSS.highlights) doc.defaultView.CSS.highlights.set('spoken',new doc.defaultView.Highlight(range));
    else {const selection=doc.getSelection();selection.removeAllRanges();selection.addRange(range);}
    if(key!==highlightKey.current&&settings.follow){const rect=range.getBoundingClientRect();if(rect.top<70||rect.bottom>doc.defaultView.innerHeight-70)doc.defaultView.scrollBy({top:rect.top-doc.defaultView.innerHeight*0.32,behavior:playing?'smooth':'auto'});}
    highlightKey.current=key;
  },[indexed,part,playback.cue,playback.preview,playback.link,settings.follow,viewportRevision]);

  async function openFile(blob) {
    const token=++openGeneration.current;player.stop();setOpening(true);setNotice('');setPanel('');setSearchText('');
    try {
      const parsed=await openEpub(blob);
      if(token!==openGeneration.current){parsed.dispose();return;}
      let saved;try{saved=await getBook(parsed.id);await putBook({...saved,id:parsed.id,title:parsed.title,blob,opened:Date.now(),bookmarks:saved?.bookmarks||[]});}catch(error){setNotice(error.message);}
      restored.current=saved?.position;setMarks(saved?.bookmarks||[]);indexRef.current=null;setIndexed(null);
      bookRef.current?.dispose();bookRef.current=parsed;setBook(parsed);refreshLibrary();
    }catch(error){setNotice(error.message);}finally{if(token===openGeneration.current)setOpening(false);}
  }
  function ready() {
    if(!bookRef.current||!frame.current?.contentDocument?.querySelector('.book-section'))return;
    try {
      const doc=frame.current.contentDocument, index=indexDocument(doc,bookRef.current);
      doc.documentElement.style.fontSize=settingsRef.current.fontSize+'px';
      doc.documentElement.dataset.theme=settingsRef.current.theme;
      indexRef.current=index;setIndexed(index);player.setDocument(index,restored.current);highlightKey.current='';
      doc.addEventListener('click',event=>{
        if (followBookLink(event,index,(text,complete,span)=>player.readLink(text,complete,span),i=>player.jump(i),setNotice)) return;
        const i=clickedPart(event,index);if(i!==null&&i>=0)player.jump(i);
      });
      doc.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='f'){event.preventDefault();setPanel('search');searchInput.current?.focus();return;}if(event.code==='Space'){event.preventDefault();['playing','preparing'].includes(player.status)?player.pause():player.play();}});
    }catch(error){setNotice(error.message);}
  }
  function openSearchResult(hit) {
    const target=indexed.parts.findIndex(p=>p.section===hit.section&&p.end>hit.start);
    if(target<0)return;
    player.jump(target,playing);
    requestAnimationFrame(()=>{
      const doc=frame.current?.contentDocument;
      if(!doc)return;
      const range=textRange(doc,indexed.sections[hit.section],hit.start,hit.end);
      if(!range)return;
      if(doc.defaultView.CSS.highlights)doc.defaultView.CSS.highlights.set('search',new doc.defaultView.Highlight(range));
      const rect=range.getBoundingClientRect();doc.defaultView.scrollBy({top:rect.top-doc.defaultView.innerHeight*0.3});
    });
  }
  function bookmark() {
    if(!part)return;
    const name=markName.trim()||book.sections[part.section].title;
    const updated=[...marks,{id:crypto.randomUUID(),name,section:part.section,start:part.start}];
    setMarks(updated);setMarkName('');updateBook(book.id,{bookmarks:updated}).catch(error=>setNotice(error.message));
  }
  function removeMark(id) { const updated=marks.filter(mark=>mark.id!==id);setMarks(updated);updateBook(book.id,{bookmarks:updated}).catch(error=>setNotice(error.message)); }
  const local=settings.engine==='kokoro';
  const voices=local?KOKORO_VOICES:onlineVoices;
  function switchEngine() {
    player.stop();setLanguage('all');setVoiceOpen(false);setQuery('');
    setSettings(current=>selectEngine(current,current.engine==='kokoro'?'edge':'kokoro'));
    setNotice(local?'':'Kokoro runs on your GPU and supports English. The first Play or Preview downloads about 350 MB. Use Chrome or Edge with graphics acceleration enabled.');
  }
  const filtered=useMemo(()=>voices.filter(v=>(language==='favorites'?settings.favorites.includes(v.name):language==='all'||v.locale.startsWith(language))&&v.name.toLowerCase().includes(query.toLowerCase())).sort((a,b)=>Number(settings.favorites.includes(b.name))-Number(settings.favorites.includes(a.name))||a.name.localeCompare(b.name)),[voices,language,query,settings.favorites]);
  const languages=[...new Set(voices.map(v=>v.locale.split('-')[0]))].sort();
  const languageName=code=>{try{return new Intl.DisplayNames(['en'],{type:'language'}).of(code);}catch{return code;}};
  const sectionParts=indexed?.parts.filter(p=>p.section===part?.section)||[];
  const percent=part?Math.round(100*(part.start/(indexed.sections[part.section].text.length||1))):0;
  return <main className="app">
    <input ref={file} type="file" accept=".epub,application/epub+zip" hidden onChange={event=>{const blob=event.target.files[0];if(blob)openFile(blob);event.target.value='';}}/>
    <header className="header"><div className="brand"><img src="./yapbook.png" alt=""/><div><h1>YapBook<span className="beta">WEB</span></h1><p>A good book. Your favorite voice.</p></div></div><div className="header-actions"><IconButton label={settings.theme==='dark'?'Switch to light mode':'Switch to dark mode'} icon={settings.theme==='dark'?Sun:Moon} onClick={()=>change({theme:settings.theme==='dark'?'light':'dark'})}/><IconButton label={local?'Kokoro GPU active — switch to online voices':'Switch to Kokoro on your GPU'} icon={BrainCircuit} active={local} onClick={switchEngine}/><IconButton label="Your library" icon={Library} active={panel==='library'} onClick={()=>{refreshLibrary();setPanel(panel==='library'?'':'library');}}/><button className="open-button" onClick={()=>file.current.click()} disabled={opening}><FolderOpen size={18}/><span>Open EPUB</span></button></div></header>
    <section className="controls" aria-label="Reading controls">
      <div className="voice-row"><label className="language-field"><span>Language</span><select value={language} onChange={event=>setLanguage(event.target.value)}><option value="favorites">Favorites</option><option value="all">All languages</option>{languages.map(l=><option key={l} value={l}>{languageName(l)}</option>)}</select></label>
        <div className="voice-field"><label htmlFor="voice-input">Reading voice</label><div className="voice-combo"><input id="voice-input" role="combobox" aria-expanded={voiceOpen} aria-controls="voice-list" autoComplete="off" value={voiceOpen?query:voiceName(settings.voice)} onFocus={()=>{setVoiceOpen(true);setQuery('');}} onChange={event=>{setVoiceOpen(true);setQuery(event.target.value);}} onKeyDown={event=>{if(event.key==='Escape')setVoiceOpen(false);if(event.key==='Enter'&&filtered[0]){change({voice:filtered[0].name});setVoiceOpen(false);}}} placeholder="Search voices…"/><button aria-label="Show voices" onClick={()=>{setVoiceOpen(!voiceOpen);setQuery('');}}><ChevronDown size={17}/></button></div>
        {voiceOpen&&<><button className="dismiss-voices" tabIndex={-1} aria-label="Close voice list" onClick={()=>setVoiceOpen(false)}/><div className="voice-list" id="voice-list" role="listbox">{filtered.map(v=><button key={v.name} role="option" aria-selected={v.name===settings.voice} onClick={()=>{change({voice:v.name});setVoiceOpen(false);}}><span>{voiceName(v.name)}<small>{v.locale} · {v.gender||'Neural voice'}</small></span>{settings.favorites.includes(v.name)?<Star size={14}/>:v.name===settings.voice?<Check size={15}/>:null}</button>)}{!filtered.length&&<p>{language==='favorites'&&!settings.favorites.length?'No favorite voices yet. Use the star to add one.':'No matching voices.'}</p>}</div></>}
        </div><div className="voice-actions"><IconButton label="Favorite voice" icon={Star} active={settings.favorites.includes(settings.voice)} onClick={()=>change({favorites:settings.favorites.includes(settings.voice)?settings.favorites.filter(v=>v!==settings.voice):[...settings.favorites,settings.voice]})}/><IconButton label="Preview voice" icon={Headphones} active={playback.preview} onClick={()=>player.testVoice()}/><IconButton label="Refresh voices" icon={loadingVoices?LoaderCircle:RefreshCw} disabled={local||loadingVoices||playing} onClick={fetchVoices}/></div>
      </div>
      <div className="transport-row"><div className="transport"><IconButton label="Previous sentence" icon={SkipBack} disabled={!part} onClick={()=>player.jump(playback.index-1)}/><button className="play-button" aria-label={playing?'Pause':'Play'} title={playing?'Pause':'Play'} disabled={!part&&!playback.preview} onClick={()=>playing?player.pause():player.play()}>{playing?<Pause size={22} fill="currentColor"/>:<Play size={22} fill="currentColor"/>}</button><IconButton label="Stop" icon={Square} disabled={!part&&!playback.preview} onClick={()=>player.stop()}/><IconButton label="Next sentence" icon={SkipForward} disabled={!part} onClick={()=>player.jump(playback.index+1)}/></div>
        <div className="sliders"><label><span><Gauge size={14}/>Speed <b>{settings.rate>0?'+':''}{settings.rate}%</b></span><input aria-label="Speed" type="range" min="-50" max="100" step="5" value={settings.rate} onChange={event=>change({rate:Number(event.target.value)})}/></label><label><span><Volume2 size={14}/>Volume <b>{settings.volume}%</b></span><input aria-label="Volume" type="range" min="0" max="100" value={settings.volume} onChange={event=>change({volume:Number(event.target.value)})}/></label></div>
        <div className="reader-actions"><label className="citation-option" title="Read author–year references, numbered citations and footnote markers aloud"><input type="checkbox" checked={settings.readCitations} onChange={event=>change({readCitations:event.target.checked})}/>Read citations</label><IconButton label="Follow current sentence" icon={AlignCenter} active={settings.follow} onClick={()=>change({follow:!settings.follow})}/><IconButton label="Smaller text" icon={Minus} disabled={settings.fontSize<=14} onClick={()=>change({fontSize:settings.fontSize-1})}/><span className="font-size">Aa</span><IconButton label="Larger text" icon={Plus} disabled={settings.fontSize>=36} onClick={()=>change({fontSize:settings.fontSize+1})}/><IconButton label="Bookmarks" icon={Bookmark} disabled={!book} active={panel==='marks'} onClick={()=>setPanel(panel==='marks'?'':'marks')}/><div className="sleep-controls"><label className="sleep" title="Sleep timer"><Moon size={17}/><select aria-label="Sleep timer" value={playback.sleep||'off'} onChange={event=>player.setSleep(event.target.value)}><option value="off">Off</option>{SLEEP_MINUTES.map(minutes=><option key={minutes} value={String(minutes)}>{minutes} min</option>)}<option value="section">End of section</option></select></label><IconButton label="Search book (Ctrl+F)" icon={Search} disabled={!book} active={panel==='search'} onClick={()=>setPanel(panel==='search'?'':'search')}/></div></div>
      </div>
    </section>
    {(notice||playback.error)&&<div className="notice" role="alert"><span>{notice||playback.error}</span><button aria-label="Dismiss message" onClick={()=>{setNotice('');player.error='';player.emit();}}><X size={16}/></button></div>}
    <div className="workspace">
      {panel&&<aside className="side-panel"><div className="panel-heading"><h2>{panel==='library'?'Your library':panel==='search'?'Search book':'Bookmarks'}</h2><IconButton label="Close panel" icon={X} onClick={()=>setPanel('')}/></div>
        {panel==='search'?<>
          <input ref={searchInput} className="book-search" aria-label="Search book" placeholder="Search this EPUB…" value={searchText} onChange={event=>setSearchText(event.target.value)} onKeyDown={event=>{if(event.key==='Escape')setPanel('');}}/>
          <p className="hint" role="status">{searchTerm?`${searchHits.length} matches in this book`:'Search all sections. Select a result to go there.'}</p>
          {searchHits.slice(searchPage*50,(searchPage+1)*50).map(hit=><div className="library-item search-result" key={`${hit.section}:${hit.start}`}><button onClick={()=>openSearchResult(hit)}><span><small>{book.sections[hit.section].title}</small>{indexed.sections[hit.section].text.slice(Math.max(0,hit.start-35),hit.start)}<mark>{indexed.sections[hit.section].text.slice(hit.start,hit.end)}</mark>{indexed.sections[hit.section].text.slice(hit.end,hit.end+80)}</span></button></div>)}
          {searchHits.length>50&&<div className="search-pages"><button disabled={!searchPage} onClick={()=>setSearchPage(p=>p-1)}>Previous</button><span>{searchPage+1} / {Math.ceil(searchHits.length/50)}</span><button disabled={(searchPage+1)*50>=searchHits.length} onClick={()=>setSearchPage(p=>p+1)}>Next</button></div>}
        </>:panel==='library'?<><p className="hint">Saved on this browser.</p>{recent.map(item=><div className="library-item" key={item.id}><button onClick={()=>openFile(item.blob)}><BookOpen size={17}/><span>{item.title}<small>{new Date(item.opened).toLocaleDateString()}</small></span></button><IconButton label={'Remove '+item.title} icon={Trash2} onClick={()=>deleteBook(item.id).then(refreshLibrary).catch(error=>setNotice(error.message))}/></div>)}{!recent.length&&<p className="hint">Open an EPUB to start your library.</p>}</>:<><div className="add-mark"><input aria-label="Bookmark name" placeholder="Name this bookmark" value={markName} onChange={event=>setMarkName(event.target.value)} onKeyDown={event=>{if(event.key==='Enter')bookmark();}}/><IconButton label="Save bookmark" icon={Plus} disabled={!part} onClick={bookmark}/></div>{marks.map(mark=><div className="library-item" key={mark.id}><button onClick={()=>{const i=indexed.parts.findIndex(p=>p.section===mark.section&&p.end>mark.start);if(i>=0)player.jump(i);}}><Bookmark size={16}/><span>{mark.name}<small>{book.sections[mark.section]?.title}</small></span></button><IconButton label={'Delete bookmark '+mark.name} icon={Trash2} onClick={()=>removeMark(mark.id)}/></div>)}{!marks.length&&<p className="hint">Save a sentence to return to it later.</p>}</>}
      </aside>}
      <section className="reader-area" aria-label="Book reader">
        {book&&<div className="book-bar"><div><BookOpen size={16}/><span title={book.title}>{book.title}</span></div><select aria-label="Section" value={part?.section??0} onChange={event=>{const i=indexed?.parts.findIndex(p=>p.section===Number(event.target.value));if(i>=0)player.jump(i,playing);}}>{book.sections.map((s,i)=><option key={i} value={i}>{s.title}</option>)}</select></div>}
        {book?<iframe ref={frame} title="EPUB text" sandbox="allow-same-origin" srcDoc={book.srcdoc} onLoad={ready}/>:<div className="empty-state"><div className="book-art"><img src="./yapbook.png" alt="An open book with a speaker"/></div><span className="eyebrow">MAKE TIME FOR YOUR NEXT CHAPTER</span><h2>Read along.<br/><em>Listen at your own pace.</em></h2><p>Open a book, choose a voice, and settle in.<br/>Every sentence stays right there with you.</p><button className="open-button" onClick={()=>file.current.click()} disabled={opening}><FolderOpen size={18}/>{opening?'Opening book…':'Choose an EPUB'}<ArrowRight size={17}/></button><div className="empty-features"><span><Check size={14}/>Your place, remembered</span><span><Check size={14}/>Click any sentence</span></div></div>}
        {opening&&book&&<div className="opening-overlay"><LoaderCircle className="spin"/>Opening book…</div>}
      </section>
    </div>
    <footer className="status-bar"><div className="status"><span className={'status-dot '+playback.status}/><span aria-live="polite">{opening?'Opening book…':playback.status==='preparing'?`${local?(playback.detail||'Preparing on your GPU'):playback.preview?'Preview':'Preparing audio'} · ${elapsed}s · ${Math.round((playback.bytes||0)/1024)} KB${part&&!playback.preview?' · '+part.text.length+' characters':''}`:playback.status==='playing'?(playback.preview?'Voice preview':'Reading'):playback.status==='paused'?'Paused':playback.status==='finished'?'Book finished':playback.status==='error'?'Could not prepare audio':part?'Ready to read':'Open an EPUB to begin'}</span></div>{part&&<div className="progress"><span>{percent}% of section</span><input aria-label="Section progress" type="range" min="0" max={Math.max(0,sectionParts.length-1)} value={sectionParts.indexOf(part)} onChange={event=>player.jump(indexed.parts.indexOf(sectionParts[Number(event.target.value)]),playing)}/></div>}<span className="privacy" title={local?'Kokoro generates audio on your device. Book text stays in this browser. Model and voice downloads require internet on first use.':"EPUBs, bookmarks and preferences stay in your browser. Only the current sentence and up to five following sentences pass through this app to Microsoft's voice service."}>{local?'Kokoro · Your GPU':'Books stay in your browser'}</span></footer>
  </main>;
}
createRoot(document.getElementById('root')).render(<App/>);
