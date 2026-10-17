import {chromium} from '@playwright/test';
import {zipSync,strToU8} from 'fflate';
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';

const archive={
 'mimetype':strToU8('application/epub+zip'),
 'META-INF/container.xml':strToU8('<container><rootfiles><rootfile full-path="book/package.opf"/></rootfiles></container>'),
 'book/package.opf':strToU8('<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>A Small Test Book</dc:title><dc:language>en</dc:language></metadata><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/><item id="two" href="two.xhtml" media-type="application/xhtml+xml"/><item id="three" href="three.xhtml" media-type="application/xhtml+xml"/><item id="style" href="style.css" media-type="text/css"/></manifest><spine><itemref idref="one"/><itemref idref="two"/><itemref idref="three"/></spine></package>'),
 'book/style.css':strToU8('h1{color:rgb(42,94,65)}em{font-style:italic}.hidden{display:none}'),
 'book/one.xhtml':strToU8('<html><head><link rel="stylesheet" href="style.css"/></head><body><h1>Chapter One</h1><p>Matthew C. Perry wrote a <em>beautiful</em> sentence. Im 17. Jahrhundert entstand ein kleines Dorf. Wir feiern ihren 105. Geburtstag.</p><p class="hidden">This text must not be spoken.</p><script>parent.__epubScriptRan=true</script>'+Array.from({length:10},(_,i)=>`<p>A quiet test paragraph number ${i+1}. This text is invented for testing.</p>`).join('')+'</body></html>'),
 'book/two.xhtml':strToU8('<html><body><h1>Chapter Two</h1><p>Here is a different chapter. Reading continues across chapter boundaries.</p></body></html>'),
 'book/three.xhtml':strToU8('<html><body><h1>Chapter Three</h1><p>This is the last chapter. We can return here later.</p></body></html>')
};
const book=Buffer.from(zipSync(archive));
await writeFile('tests/sample.epub',book);
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--mute-audio']});
const page=await browser.newPage({viewport:{width:1280,height:920}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>{window.__commands=[];window.addEventListener('message',event=>{if(event.data?.type==='streamlit:setComponentValue')window.__commands.push(event.data.value);});});
try {
 await page.goto(process.env.YAPBOOK_TEST_URL || 'http://127.0.0.1:8501/');
 const app=page.frameLocator('iframe[title="streamlit_app.yapbook_reader"]');
 await app.getByRole('heading',{name:'YapBook'}).waitFor({timeout:30000});
 await page.screenshot({path:'tests/web-desktop.png',fullPage:true});
 await app.locator('input[type=file]').setInputFiles({name:'sample.epub',mimeType:'application/epub+zip',buffer:book});
 const reader=app.frameLocator('iframe[title="EPUB text"]');
 await reader.getByRole('heading',{name:'Chapter Three'}).waitFor();
 assert.equal(await reader.locator('.book-section').count(),3);
 assert.equal(await reader.locator('em').textContent(),'beautiful');
 assert.equal(await reader.locator('h1').first().evaluate(e=>getComputedStyle(e).color),'rgb(42, 94, 65)');
 assert.equal(await reader.locator('script').count(),0);
 await app.getByRole('slider',{name:'Volume',exact:true}).fill('0');
 await app.getByRole('button',{name:'Play',exact:true}).click();
 await app.locator('.status').filter({hasText:'Reading'}).waitFor({timeout:60000});
 await app.getByRole('button',{name:'Pause',exact:true}).click();
 await page.waitForFunction(()=>window.__commands.filter(c=>c.action==='speech').length>=3,{},{timeout:60000});
 await page.waitForTimeout(1200);
 const commands=await page.evaluate(()=>window.__commands.filter(c=>c.action==='speech'));
 assert.deepEqual(commands.slice(0,3).map(c=>c.text),['Chapter One','Matthew C. Perry wrote a beautiful sentence.','Im 17. Jahrhundert entstand ein kleines Dorf.']);
 assert.equal(commands.length,3,'Only current and next two sentences should be requested while paused.');
 assert.ok(commands.every(c=>c.rate===-15));
 assert.equal(await reader.locator('body').evaluate(()=>[...CSS.highlights.get('spoken')][0].toString()),'Chapter One');
 await app.getByRole('button',{name:'Bookmarks',exact:true}).click();
 await app.getByRole('textbox',{name:'Bookmark name'}).fill('The start');
 await app.getByRole('button',{name:'Save bookmark'}).click();
 await app.locator('.library-item').filter({hasText:'The start'}).waitFor();
 await app.getByRole('button',{name:'Close panel'}).click();
 await app.getByRole('button',{name:'Switch to dark mode'}).click();
 assert.equal(await app.locator('.brand h1').evaluate(e=>getComputedStyle(e).color),'rgb(213, 224, 216)');
 assert.equal(await reader.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(22, 30, 36)');
 assert.equal(await reader.locator('em').evaluate(e=>getComputedStyle(e).color),'rgb(213, 222, 217)');
 assert.equal(await reader.locator('body').evaluate(()=>[...CSS.highlights.get('spoken')][0].toString()),'Chapter One');
 await page.screenshot({path:'tests/web-dark.png',fullPage:true});
 for(const sentence of ['Matthew C. Perry wrote a beautiful sentence.','Im 17. Jahrhundert entstand ein kleines Dorf.','Wir feiern ihren 105. Geburtstag.']){
   await app.getByRole('button',{name:'Next sentence',exact:true}).click();
   await app.locator('.status').filter({hasText:'Reading'}).waitFor({timeout:60000});
   await page.waitForTimeout(500);
   await app.getByRole('button',{name:'Pause',exact:true}).click();
   assert.equal(await reader.locator('body').evaluate(()=>[...CSS.highlights.get('spoken')][0].toString()),sentence);
 }
 const sentenceRequests=await page.evaluate(()=>window.__commands.filter(c=>c.action==='speech').map(c=>c.text));
 assert.ok(sentenceRequests.includes('Wir feiern ihren 105. Geburtstag.'));
 assert.ok(!sentenceRequests.some(t=>['Matthew C.','Im 17.','Wir feiern ihren 105.'].includes(t)));
 await reader.getByRole('heading',{name:'Chapter Three'}).click();
 await app.getByRole('button',{name:'Pause',exact:true}).click();
 assert.equal(await app.getByRole('combobox',{name:'Section',exact:true}).inputValue(),'2');
 await page.screenshot({path:'tests/web-reading.png',fullPage:true});
 await page.reload();
 await app.getByRole('button',{name:'Your library',exact:true}).click();
 await app.getByRole('button',{name:'Switch to light mode'}).waitFor();
 await app.locator('.library-item').getByRole('button').first().click();
 await reader.getByRole('heading',{name:'Chapter Three'}).waitFor();
 await app.getByRole('combobox',{name:'Section',exact:true}).evaluate(el=>new Promise((resolve,reject)=>{let count=0;const t=setInterval(()=>{if(el.value==='2'){clearInterval(t);resolve();}else if(count++>50){clearInterval(t);reject(new Error('Resume position not restored'));}},100);}));
 assert.equal(await app.getByRole('slider',{name:'Volume',exact:true}).inputValue(),'0');
 await app.getByRole('button',{name:'Bookmarks',exact:true}).click();
 await app.locator('.library-item').filter({hasText:'The start'}).waitFor();
 await app.getByRole('button',{name:'Close panel'}).click();
 assert.equal(await reader.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(22, 30, 36)');
 await page.setViewportSize({width:390,height:844});
 await page.waitForTimeout(1200);
 await page.screenshot({path:'tests/web-mobile.png',fullPage:true});
 const layout=await app.locator('body').evaluate(()=>({width:innerWidth,scroll:document.body.scrollWidth}));
 assert.ok(layout.scroll<=layout.width,'Mobile layout should not overflow horizontally.');
 const highlight=await reader.locator('body').evaluate(()=>{const r=[...CSS.highlights.get('spoken')][0].getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:innerHeight};});
 assert.ok(highlight.top>=0&&highlight.bottom<=highlight.height,'The current sentence should remain visible after resizing.');
 assert.deepEqual(errors,[]);
 console.log('PASS: EPUB formatting, all sections, live speech, exactly two preloaded sentences, -15% default, highlighting, click-to-jump, bookmarks, resume, mobile layout.');
} catch(error) { await page.screenshot({path:'tests/web-failure.png',fullPage:true}); console.log('Browser errors:',errors); throw error; }
finally { await browser.close(); }
