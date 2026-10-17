import { unzip } from 'fflate';
import DOMPurify from 'dompurify';
import { sentenceParts } from './text.mjs';

const decode = new TextDecoder();
const local = (name, base = '') => {
  try { const url = new URL(name, 'https://epub.invalid/' + base); return url.origin === 'https://epub.invalid' ? decodeURIComponent(url.pathname.slice(1)) : ''; } catch { return ''; }
};
const escape = value => value.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const xml = value => {
  const result = new DOMParser().parseFromString(value, 'application/xml');
  if (result.querySelector('parsererror')) throw new Error('This EPUB contains invalid package information.');
  return result;
};

export async function openEpub(blob) {
  if (blob.size > 50 * 1024 * 1024) throw new Error('Please choose an EPUB smaller than 50 MB.');
  const buffer = await blob.arrayBuffer();
  const id = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', buffer)), n => n.toString(16).padStart(2,'0')).join('');
  let expanded = 0, count = 0, invalid = false;
  const files = await new Promise((resolve, reject) => unzip(new Uint8Array(buffer), {filter: file => {
    expanded += file.originalSize; count++;
    if (expanded > 120 * 1024 * 1024 || count > 5000) invalid = true;
    return !invalid;
  }}, (error, result) => error ? reject(new Error('This file is not a readable EPUB archive.')) : resolve(result)));
  if (invalid) throw new Error('This EPUB is too large to unpack safely in your browser.');
  const read = path => { if (!files[path]) throw new Error('A required file is missing from this EPUB.'); return decode.decode(files[path]); };
  const container = xml(read('META-INF/container.xml'));
  const packagePath = container.getElementsByTagNameNS('*','rootfile')[0]?.getAttribute('full-path');
  if (!packagePath) throw new Error('This EPUB has no book package.');
  const opf = xml(read(packagePath));
  const title = opf.getElementsByTagNameNS('*','title')[0]?.textContent?.trim() || blob.name || 'Untitled book';
  const language = opf.getElementsByTagNameNS('*','language')[0]?.textContent?.trim() || 'en';
  const manifest = new Map([...opf.getElementsByTagNameNS('*','item')].map(item => [item.id || item.getAttribute('id'), {path:local(item.getAttribute('href'),packagePath), type:item.getAttribute('media-type'), properties:item.getAttribute('properties') || ''}]));
  const ordered = [...opf.getElementsByTagNameNS('*','itemref')].filter(item => item.getAttribute('linear') !== 'no').map(item => manifest.get(item.getAttribute('idref'))).filter(item => item && !item.properties.split(/\s+/).includes('nav') && /html/.test(item.type));
  if (!ordered.length) throw new Error('This EPUB has no readable sections.');
  const types = new Map([...manifest.values()].map(item => [item.path,item.type]));
  const urls = new Map();
  const resource = (href, base) => {
    const path = local(href,base), type = types.get(path) || '';
    if (!path || !files[path] || !/^(image|font)\//.test(type) && !/\.(woff2?|ttf|otf)$/i.test(path)) return '';
    if (!urls.has(path)) urls.set(path, URL.createObjectURL(new Blob([files[path]], {type:type || 'application/octet-stream'})));
    return urls.get(path);
  };
  const rewriteUrls = (css, base) => css.replace(/url\(\s*(['"]?)(.*?)\1\s*\)/gi, (_, quote, href) => `url("${resource(href,base)}")`);
  const cssFor = (source, base, scope, seen = new Set()) => {
    if (seen.has(base) || seen.size > 20) return '';
    const visited = new Set(seen).add(base);
    let imports = '';
    source = source.replace(/@import\s+(?:url\()?\s*['"]([^'"]+)['"]\s*\)?[^;]*;/gi, (_, href) => {
      const path = local(href,base); if (files[path]) imports += cssFor(read(path),path,scope,visited); return '';
    });
    const sheet = new CSSStyleSheet();
    try { sheet.replaceSync(rewriteUrls(source,base)); } catch { return imports; }
    const scoped = rules => [...rules].map(rule => {
      if (rule.type === CSSRule.STYLE_RULE) {
        const selector = rule.selectorText.split(',').map(s => {
          s = s.trim().replace(/#([\w-]+)/g, '#s' + scope.slice(9) + '-$1').replace(/(^|[\s>+~])(html|body|:root)(?=[\s.#:[>+~]|$)/g, '$1' + scope);
          return s.startsWith(scope) ? s : scope + ' ' + s;
        }).join(',');
        const style = rule.style;
        // Book CSS may style the page, but cannot cover or escape its reader section.
        if (['fixed','sticky'].includes(style.position)) style.position = 'static';
        return selector + '{' + style.cssText + '}';
      }
      if (rule.type === CSSRule.FONT_FACE_RULE) return rule.cssText;
      if (rule.cssRules && (rule.type === CSSRule.MEDIA_RULE || rule.type === CSSRule.SUPPORTS_RULE)) return rule.cssText.slice(0,rule.cssText.indexOf('{')+1) + scoped(rule.cssRules) + '}';
      return '';
    }).join('\n');
    return imports + scoped(sheet.cssRules);
  };
  try {
    const paths = new Map(ordered.map((item,i) => [item.path,i]));
    const sections = ordered.map((item,i) => {
      const doc = new DOMParser().parseFromString(read(item.path),'text/html');
      let css = '';
      for (const style of doc.querySelectorAll('style,link[rel="stylesheet"]')) {
        const path = style.tagName === 'LINK' ? local(style.getAttribute('href'),item.path) : item.path;
        if (style.tagName !== 'LINK' || files[path]) css += cssFor(style.tagName === 'LINK' ? read(path) : style.textContent,path,`#section-${i}`);
      }
      const content = DOMPurify.sanitize(doc.body.innerHTML, {RETURN_DOM_FRAGMENT:true, FORBID_TAGS:['style','link','script','iframe','object','embed','form','input','button','textarea','select','audio','video','source','base','meta'], FORBID_ATTR:['srcset','formaction','autofocus']});
      for (const node of content.querySelectorAll('*')) {
        for (const attr of [...node.attributes]) if (attr.name === 'src' || attr.name === 'xlink:href' || attr.name === 'poster') node.setAttribute(attr.name,resource(attr.value,item.path));
        if (node.hasAttribute('style')) node.setAttribute('style',rewriteUrls(node.getAttribute('style'),item.path).replace(/position\s*:\s*(fixed|sticky)/gi,'position:static'));
        if (node.id) node.id = `s${i}-` + node.id;
        else if (node.tagName === 'A' && node.getAttribute('name')) node.id = `s${i}-` + node.getAttribute('name');
        if (node.tagName === 'A') {
          const href = node.getAttribute('href') || '', target = local(href,item.path), section = paths.get(target), hash = href.includes('#') ? href.slice(href.indexOf('#')+1) : '';
          if (node.hasAttribute('href') && section !== undefined) {
            let fragment; try { fragment = decodeURIComponent(hash); } catch { fragment = hash; }
            node.setAttribute('href',hash ? `#s${section}-${fragment}` : `#section-${section}`);
          }
          else node.removeAttribute('href');
          node.removeAttribute('target');
        }
      }
      const wrap = document.createElement('div');
      if (doc.body.id) { const anchor = document.createElement('a'); anchor.id = `s${i}-` + doc.body.id; wrap.append(anchor); }
      wrap.append(content);
      const heading = wrap.querySelector('h1,h2,h3');
      return {title:heading?.textContent?.trim() || doc.title || `Section ${i+1}`, html:`<section id="section-${i}" class="book-section ${escape(doc.body.className)}" data-section="${i}" lang="${escape(language)}">${wrap.innerHTML}</section>`, css};
    });
    const csp = "default-src 'none'; img-src blob: data:; font-src blob: data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'";
    const srcdoc = `<!doctype html><html lang="${escape(language)}"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><style>
      :root{color-scheme:light}html{font-size:20px;scroll-behavior:auto}body{margin:0 auto;padding:36px clamp(20px,6vw,80px) 50vh;max-width:860px;color:#28313c;background:#fffdf8;font:1rem/1.85 Georgia,serif;overflow-wrap:anywhere}.book-section{position:relative;isolation:isolate;overflow:hidden;padding:16px 0 48px;border-bottom:1px solid #e8e3d8;margin-bottom:48px}img,svg{max-width:100%;height:auto}h1,h2,h3{line-height:1.3}p{margin-block:1em}a{color:inherit}::highlight(spoken){background:#ffe17a;color:#25281f}::selection{background:#ffe17a} ${sections.map(s=>s.css).join('\n').replace(/<\/style/gi,'')}
      :root[data-theme=dark]{color-scheme:dark;background:#161e24!important}html[data-theme=dark] body{background:#161e24!important;color:#d5ded9!important}html[data-theme=dark] .book-section,html[data-theme=dark] .book-section *:not(img):not(svg):not(svg *){color:#d5ded9!important;background-color:transparent!important;border-color:#36463e!important}html[data-theme=dark] a{color:#9fc9b1!important}html[data-theme=dark] ::highlight(spoken){background:#e8bd58;color:#18221d}html[data-theme=dark] ::selection{background:#e8bd58;color:#18221d}
      </style></head><body>${sections.map(s=>s.html).join('\n')}</body></html>`;
    return {id,title,language,sections,srcdoc,dispose:()=>{for(const url of urls.values()) URL.revokeObjectURL(url);}};
  } catch (error) { for (const url of urls.values()) URL.revokeObjectURL(url); throw error; }
}

export function indexDocument(doc, book) {
  const sections = [], parts = [];
  for (const element of doc.querySelectorAll('.book-section')) {
    const spans = []; let text = '', space = '';
    const walk = node => {
      if (node.nodeType === 3) {
        for (const match of node.data.matchAll(/\s+|\S+/g)) {
          if (/^\s/.test(match[0])) { if (space !== '\n') space = ' '; continue; }
          if (text && space) text += space;
          space = '';
          const start = text.length; text += match[0];
          spans.push({start,end:text.length,node,offset:match.index});
        }
      } else if (node.nodeType === 1) {
        if (['SCRIPT','STYLE','NOSCRIPT','SVG','RT','RP'].includes(node.tagName) || node.hidden || node.getAttribute('aria-hidden') === 'true') return;
        const style = doc.defaultView.getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return;
        const block = !['inline','inline-block','contents'].includes(style.display) || node.tagName === 'BR';
        if (block) space = '\n';
        for (const child of node.childNodes) walk(child);
        if (block) space = '\n';
      }
    };
    walk(element);
    const section = sections.length;
    sections.push({text,spans,element});
    let locale = book.language; try { new Intl.Segmenter(locale); } catch { locale = 'en'; }
    for (const part of sentenceParts(text,0,locale)) parts.push({...part,section,key:`${section}:${part.start}`});
  }
  if (!parts.length) throw new Error('This EPUB has no selectable text. It may contain only pictures.');
  return {sections,parts};
}

export function textRange(doc, section, start, end) {
  const first = section.spans.find(span => span.end > start), last = section.spans.findLast(span => span.start < end);
  if (!first || !last) return null;
  const range = doc.createRange();
  range.setStart(first.node,first.offset + Math.max(0,start-first.start));
  range.setEnd(last.node,last.offset + Math.min(last.end,end)-last.start);
  return range;
}

export function clickedPart(event, index) {
  const doc = event.currentTarget;
  if (event.target.closest?.('a[href]')) return null;
  const caret = doc.caretPositionFromPoint?.(event.clientX,event.clientY);
  const range = caret ? null : doc.caretRangeFromPoint?.(event.clientX,event.clientY);
  const node = caret?.offsetNode || range?.startContainer, offset = caret?.offset ?? range?.startOffset;
  for (let section = 0; section < index.sections.length; section++) {
    const span = index.sections[section].spans.find(span => span.node === node && offset >= span.offset && offset <= span.offset + span.end-span.start);
    if (span) {
      const position = span.start+offset-span.offset;
      return index.parts.findIndex(part => part.section === section && part.end >= position);
    }
  }
  return null;
}

export function followBookLink(event, index, readLink, jump, missing) {
  const anchor = event.target.closest?.('a[href]');
  if (!anchor) return false;
  // A fragment URL in srcdoc otherwise resolves to the containing app's URL.
  event.preventDefault();
  const doc = event.currentTarget, href = anchor.getAttribute('href');
  const target = href.startsWith('#') ? doc.getElementById(href.slice(1)) : null;
  if (!target) { missing('This link target is not included in the book.'); return true; }
  const section = Number(target.closest('.book-section')?.dataset.section);
  const spans = index.sections[section]?.spans || [];
  const span = spans.find(span => target.contains(span.node) || Boolean(target.compareDocumentPosition(span.node) & 4));
  const part = span && index.parts.findIndex(part => part.section === section && part.end > span.start);
  const sourceSection = Number(anchor.closest('.book-section')?.dataset.section);
  const sourceSpans = index.sections[sourceSection]?.spans.filter(span => anchor.contains(span.node)) || [];
  const source = sourceSpans.length ? {section:sourceSection,start:sourceSpans[0].start,end:sourceSpans.at(-1).end} : null;
  const label = source ? index.sections[sourceSection].text.slice(source.start,source.end) : anchor.textContent.trim();
  readLink(label, () => {
    if (typeof part === 'number' && part >= 0) jump(part);
    target.scrollIntoView({block:'start'});
  }, source);
  return true;
}
