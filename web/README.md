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
- The server keeps only the latest request/result for each session in memory. It does not store EPUBs or log their text. A closed connection may allow an already running request to finish (bounded by 90 seconds).
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

The browser check uses an invented EPUB and muted playback. It verifies real speech, exactly two preloaded sentences, formatting, all sections, clicking a sentence, bookmarking, restoring progress, light/dark mode and a narrow viewport. It never uses a book from your library.

The link check covers reading a label before navigation, pause/resume, cancellation, navigation within and between sections, body and named anchors, keyboard activation, and missing targets. Set `YAPBOOK_TEST_URL` to test a local server on a port other than 8501.
