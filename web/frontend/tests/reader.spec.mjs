import {test as base, expect} from '@playwright/test';
import {zipSync, strToU8} from 'fflate';

function makeBook(body = '<p>Evidence (Smith et al., 2021) supports this [12].</p><p>A second invented sentence.</p><a href="b.xhtml#target">Read the destination</a>') {
  const files = {
    mimetype: 'application/epub+zip',
    'META-INF/container.xml': '<container><rootfiles><rootfile full-path="book/package.opf"/></rootfiles></container>',
    'book/package.opf': '<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>Reader fixture</dc:title><dc:language>en</dc:language></metadata><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>',
    'book/a.xhtml': '<html><body>' + body + '</body></html>',
    'book/b.xhtml': '<html><body><p id="target">The search destination is in the next section.</p><p>Matthew C. Perry visited in the 17. Jahrhundert.</p></body></html>',
  };
  return Buffer.from(zipSync(Object.fromEntries(Object.entries(files).map(([name, text]) => [name, strToU8(text)]))));
}

const test = base.extend({
  page: async ({page}, use) => {
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      return url.hostname === '127.0.0.1' ? route.continue() : route.abort();
    });
    await page.addInitScript(() => {
      window.__speech = [];
      window.__audio = [];
      window.__seen = new Map();
      window.Audio = class extends EventTarget {
        constructor() {super(); this.currentTime = 0; this.volume = 1; this.src = ''; window.__audio.push(this);}
        play() {return Promise.resolve();}
        pause() {}
        load() {}
        removeAttribute(name) {if (name === 'src') this.src = '';}
        getAttribute(name) {return name === 'src' ? this.src : null;}
      };
      window.addEventListener('message', event => {
        if (event.data?.type !== 'streamlit:setComponentValue') return;
        const command = event.data.value;
        for (const id of command?.ack || []) window.__seen.delete(id);
        for (const request of command?.requests || []) {
          if (window.__seen.has(request.id)) continue;
          let result;
          if (request.action === 'voices') result = {voices: [{name: 'en-US-BrianMultilingualNeural', locale: 'en-US', gender: 'Male'}]};
          else {
            window.__speech.push(request);
            result = {audio: btoa('synthetic audio boundary'), boundaries: [{text: request.text, offset: 0, duration: 10_000_000}]};
          }
          window.__seen.set(request.id, {id: request.id, status: 'ready', result});
        }
        if (window.__seen.size) queueMicrotask(() => window.postMessage({type: 'streamlit:render',
          args: {reply: {replies: [...window.__seen.values()]}}, disabled: false}, window.location.origin));
      });
    });
    await use(page);

  },
});

test('EPUB scripts, event handlers, external resources and active elements cannot escape the reader', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  const hostile = '<h1>A safe heading</h1><script>parent.__pwned=true</script>' +
    '<img src="https://attacker.invalid/pixel" onerror="parent.__pwned=true">' +
    '<a href="javascript:parent.__pwned=true">Bad link</a><iframe src="https://attacker.invalid/"></iframe>' +
    '<form action="https://attacker.invalid/"><input autofocus></form>' +
    '<style>@import "https://attacker.invalid/evil.css";p{position:fixed;background:url(https://attacker.invalid/pixel)}</style>' +
    '<p onclick="parent.__pwned=true">Readable text.</p><a href="b.xhtml#target">Internal link</a>';
  await page.locator('input[type=file]').setInputFiles({name: 'hostile.epub', mimeType: 'application/epub+zip', buffer: makeBook(hostile)});
  const frame = page.frameLocator('iframe[title="EPUB text"]');
  await expect(frame.locator('#section-1')).toBeVisible();
  expect(await frame.locator('script,iframe,form,input,object,embed').count()).toBe(0);
  expect(await frame.locator('body').evaluate(body => [...body.querySelectorAll('*')].some(node => [...node.attributes].some(a => /^on/i.test(a.name))))).toBe(false);
  expect(await frame.locator('img').getAttribute('src')).toBe('');
  expect(await frame.getByText('Bad link').getAttribute('href')).toBeNull();
  expect(await frame.getByText('Internal link').getAttribute('href')).toBe('#s1-target');
  expect(await frame.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content')).toContain("default-src 'none'");
  expect(await page.locator('iframe[title="EPUB text"]').getAttribute('sandbox')).toBe('allow-same-origin');
  expect(await page.evaluate(() => Boolean(window.__pwned))).toBe(false);
  expect(errors).toEqual([]);
});

test('search, citation projection, prefetch, themes and persisted cache work together without a voice service', async ({page}) => {
  await page.goto('/');
  await page.locator('input[type=file]').setInputFiles({name: 'fixture.epub', mimeType: 'application/epub+zip', buffer: makeBook()});
  const frame = page.frameLocator('iframe[title="EPUB text"]');
  await expect(frame.locator('#section-1')).toBeVisible();
  await page.getByRole('checkbox', {name: 'Read citations'}).uncheck();
  await page.getByRole('button', {name: 'Play', exact: true}).click();
  await expect(page.locator('.status')).toContainText('Reading');
  await expect.poll(() => page.evaluate(() => window.__speech.length)).toBe(3);
  expect(await page.evaluate(() => window.__speech[0].text)).toBe('Evidence supports this.');
  await page.getByRole('button', {name: 'Pause', exact: true}).click();
  await page.getByRole('button', {name: 'Search book (Ctrl+F)'}).click();
  await page.getByRole('textbox', {name: 'Search book', exact: true}).fill('search destination');
  await page.locator('.search-result button').click();
  await expect(page.getByRole('combobox', {name: 'Section', exact: true})).toHaveValue('1');
  expect(await frame.locator('body').evaluate(() => [...CSS.highlights.get('search')][0].toString())).toBe('search destination');
  await page.getByRole('button', {name: 'Close panel'}).click();
  await page.getByRole('button', {name: 'Switch to dark mode'}).click();
  await expect(frame.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await page.getByRole('button', {name: 'Your library', exact: true}).click();
  await page.locator('.library-item').getByRole('button').first().click();
  await expect(frame.locator('#section-1')).toBeVisible();
  await expect(page.getByRole('checkbox', {name: 'Read citations'})).not.toBeChecked();
  await page.getByRole('combobox', {name: 'Section', exact: true}).selectOption('0');
  await page.getByRole('button', {name: 'Play', exact: true}).click();
  await expect(page.locator('.status')).toContainText('Reading');
  expect(await page.evaluate(() => window.__speech.length)).toBe(0);
});

test('malformed and oversized archives are rejected', async ({page}) => {
  await page.goto('/');
  const errors = await page.evaluate(async () => {
    const {openEpub} = await import('/src/lib/epub.mjs');
    const messages = [];
    for (const blob of [new Blob(['not a zip']), new Blob([new Uint8Array(50 * 1024 * 1024 + 1)])]) {
      try {await openEpub(blob); messages.push('unexpected success');}
      catch (error) {messages.push(error.message);}
    }
    return messages;
  });
  expect(errors).toEqual(['This file is not a readable EPUB archive.', 'Please choose an EPUB smaller than 50 MB.']);
});
