# YapBook for Streamlit

An EPUB reader with natural online voices, preserved book formatting, sentence highlighting, click-to-read, and saved reading positions. The light/dark switch also changes the book page and remembers your choice.

## Run locally

From this directory, install `requirements.txt` in a Python virtual environment, then run:

```sh
python -m streamlit run streamlit_app.py
```

The built browser component in `frontend/dist` is included, so deployment does not need Node.js. To edit its source, use Node.js 22.13+ and run `npm ci` followed by `npm run build` in `frontend`.

## Publish on Streamlit Community Cloud

1. Sign in at https://share.streamlit.io/ with the GitHub account that has access to this repository.
2. Choose **Create app** / **Deploy a public app from GitHub**.
3. Select the repository `McLeodolf/YapBook`, the branch containing this web version, and main file `web/streamlit_app.py`.
4. Choose the subdomain `yapbook` if available. A different available name is required if someone else has already claimed it.
5. In advanced settings choose Python **3.13** (or 3.14 if offered). No API keys or secrets are required.
6. Deploy, then test **Preview voice** and open an EPUB on the deployed URL. Local speech success does not guarantee that the external service accepts requests from a cloud host.

Streamlit installs the `requirements.txt` next to this entry point, rather than the Windows desktop dependencies at the repository root. Do not set the main file to `gui_entry.py`.

Community Cloud hosting and its `*.streamlit.app` hostname can be free. Apps sleep after 12 hours without traffic and wake through the page shown to the next visitor; this is not guaranteed uninterrupted availability. A separately registered custom domain is not included.

## Reading and privacy

- Open `.epub` files locally. DRM-protected books are not supported.
- Click an internal book link to read its label aloud first, then jump to its destination and continue reading. Pause defers the jump; Stop or another navigation cancels it. All book sections remain available for scrolling.
- EPUBs, library entries, bookmarks, preferences and positions are stored in this browser's IndexedDB/localStorage. Nothing synchronizes between devices. Clearing browser data removes the saved library; private browsing may not keep it.
- Only speech requests pass through Streamlit to Microsoft's online speech service. Each request is one sentence; at most the current sentence and the next two are prepared. Sentences longer than 700 characters are split into smaller parts.
- Sentence detection keeps common abbreviations, initials such as `Matthew C. Perry`, and ordinals such as `17. Jahrhundert` and `105. Geburtstag` together. Timing fragments from the service are combined into one sentence highlight; pronunciation remains controlled by the selected voice.
- The server keeps at most three independent request/results per session in memory, removing delivered results when acknowledged. It does not store EPUBs or log their text. The current sentence and next two are prepared concurrently, subject to the shared server capacity. Synthesis is bounded by 90 seconds, with up to 30 seconds waiting for capacity.
- Search the entire open book locally using the magnifying glass or Ctrl+F. Results retain source positions, including references omitted from speech.
- **Read citations** is saved and initially enabled. Disable it to omit recognized author–year references, `[12]`-style citations and explicit footnote markers. Book formatting and visible citations remain unchanged. Unusual citation formats can require manual review; ordinary quotations and mathematical superscripts are retained.
- Successful audio is saved in IndexedDB by spoken text, voice and effective speed, and identical pending requests share a promise. Stop/seek detaches playback while started requests finish into the cache. Reopening or reloading can reuse completed audio. Failed requests are retried only through an explicit user action. Clearing browser storage, storage failure, closing during an unfinished request, or using another browser/device can require new requests. Audio cache size grows with use; there is no automatic eviction from disk.
- Visible speed `0%` sends `-15%` to the service. The default voice is `en-US-BrianMultilingualNeural`. Volume is local to browser playback.
- Streamlit and the voice service have resource and availability limits. `edge-tts` uses an unofficial free service that may be slow or unavailable, particularly from some cloud networks.
- The reader preserves normal book markup, local images, fonts and scoped CSS, while blocking scripts and external book resources. Some advanced EPUB layouts or SVG features may differ from a dedicated reading application. Dark mode adapts book text colors for contrast; light mode restores the original colors.
- Browsers may require another tap on Play after audio finishes preparing, and may pause playback in the background or when a phone locks. Keep the reader tab open for continuous playback.

## Checks

```sh
python -m unittest discover -s tests -v
cd frontend
npm test
# With local Streamlit running and Google Chrome installed:
node tests/browser-check.mjs
node tests/link-check.mjs
```

The browser check uses an invented EPUB and muted playback. It verifies real speech, whole-sentence requests and highlights for initials and ordinals, exactly two preloaded sentences, formatting, all sections, clicking a sentence, bookmarking, restoring progress, light/dark mode and a narrow viewport. It never uses a book from your library.

The link check covers reading a label before navigation, pause/resume, cancellation, navigation within and between sections, body and named anchors, keyboard activation, and missing targets. Set `YAPBOOK_TEST_URL` to test a local server on a port other than 8501.
