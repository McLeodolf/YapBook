# YapBook for Streamlit

An EPUB reader with natural online voices, preserved book formatting, sentence highlighting, click-to-read, and saved reading positions. The light/dark switch also changes the book page and remembers your choice.

## Optional Kokoro voices on your GPU

Use the AI icon beside the light/dark button to switch between online voices and **Kokoro GPU**. Online voices remain the default. Each engine remembers its own selected voice, and favorites work within either voice list.

Kokoro uses this user's browser GPU through WebGPU, not the Streamlit server. It currently offers American and British English voices; keep online voices for German and other languages. Use a current Chrome or Edge browser with graphics acceleration enabled and a compatible GPU. If WebGPU is unavailable, the reader shows an error and never silently switches to CPU or sends local-mode text to the online service.

The first Play or Preview in Kokoro mode downloads about 350 MB of model/tokenizer/voice assets from Hugging Face. The browser caches these where storage permits; later model loading can reuse those files. No model download starts just from opening YapBook or selecting Kokoro. Generation runs in a dedicated worker so the reader remains responsive, with visible download/loading/generation status. GPU performance and available memory determine whether preparation keeps ahead of playback.

The same moving window retains five previous, the current, and five upcoming sentence chunks. Local inference processes its queued chunks one at a time on one model instance to avoid competing GPU graphs. Already-started work finishes into the engine-specific audio cache; navigation cancels queued work outside the window. A local timeout or GPU failure requires an explicit retry or engine switch. Kokoro speed `0%` uses the model's unchanged native `1.0×` default, with a range of `-50%` to `+100%` (`0.5×` to `2.0×`). Online voices retain their existing `-15%` baseline at displayed `0%`.

Kokoro produces sentence-level highlighting without word timestamps. Long sentence chunks are further split at word boundaries before inference and joined for playback; oversized phoneme sequences are rejected rather than silently dropping text. EPUB display and citation filtering use the original source offsets. Closing the page ends unfinished work. Switching back to online voices stops playback; press Play to continue with the selected engine.

The JavaScript package is pinned to `kokoro-js@1.2.1`, using the official `onnx-community/Kokoro-82M-v1.0-ONNX` model with `fp32` and `device: webgpu`. Its API selects the model repository's current revision, and browser caching retains downloaded files; it does not expose a revision argument. Node-only `sharp` and `onnxruntime-node` dependencies are overridden to patched versions; neither is part of the browser synthesis bundle. Original license texts for the new bundled packages are included in `frontend/public/licenses` and copied into the deployment bundle.

## Run locally

From the repository root, enter `web/`. Use a Python virtual environment with the web dependencies, then run:

```sh
cd web
python -m pip install --require-hashes -r requirements.txt
python -m streamlit run streamlit_app.py
```

These commands use `web/requirements.txt`; the desktop dependency files are separate under `requirements/`. If your terminal is already in `web/`, omit `cd web`. The built browser component in `frontend/dist` is included, so deployment does not need Node.js. To edit its source, use Node.js 22.13+ and run `npm ci` followed by `npm run build` in `frontend`.

## Publish on Streamlit Community Cloud

1. Sign in at https://share.streamlit.io/ with the GitHub account that has access to this repository.
2. Choose **Create app** / **Deploy a public app from GitHub**.
3. Select the repository `McLeodolf/YapBook`, the branch containing this web version, and main file `web/streamlit_app.py`.
4. Choose the subdomain `yapbook` if available. A different available name is required if someone else has already claimed it.
5. In advanced settings choose Python **3.13** (or 3.14 if offered). No API keys or secrets are required.
6. Deploy, then test **Preview voice** and open an EPUB on the deployed URL. Local speech success does not guarantee that the external service accepts requests from a cloud host.

Streamlit installs `web/requirements.txt` next to this entry point, rather than the Windows desktop dependencies in `requirements/`. Keep `web/streamlit_app.py` as the deployment entry point; `scripts/launch_gui.py` belongs to the Windows EXE build.

Community Cloud hosting and its `*.streamlit.app` hostname can be free. Apps sleep after 12 hours without traffic and wake through the page shown to the next visitor; this is not guaranteed uninterrupted availability. A separately registered custom domain is not included.

## Reading and privacy

- Open `.epub` files locally. DRM-protected books are not supported.
- Click an internal book link to read its label aloud first, then jump to its destination and continue reading. Pause defers the jump; Stop or another navigation cancels it. All book sections remain available for scrolling.
- EPUBs, library entries, bookmarks, preferences and positions are stored in this browser's IndexedDB/localStorage. Nothing synchronizes between devices. Clearing browser data removes the saved library; private browsing may not keep it.
- In online mode, only speech requests pass through Streamlit to Microsoft's online speech service. Each request is one sentence; at most the current sentence and the next five are requested ahead. The previous five available sentences stay in RAM for immediate backward navigation. Sentences longer than 700 characters are split into smaller parts.
- Sentence detection keeps common abbreviations, initials such as `Matthew C. Perry`, and ordinals such as `17. Jahrhundert` and `105. Geburtstag` together. Timing fragments from the service are combined into one sentence highlight; pronunciation remains controlled by the selected voice.
- In online mode, the server keeps at most six independent request/results per session in memory, removing delivered results when acknowledged. It does not store EPUBs or log their text. The current sentence and next five are prepared concurrently, subject to the shared server capacity. Synthesis is bounded by 90 seconds, with up to 30 seconds waiting for capacity.
- Ready audio plays without waiting for its browser-cache write; background saving retains the in-memory copy until it is persisted.
- Search the entire open book locally using the magnifying glass or Ctrl+F. Results retain source positions, including references omitted from speech.
- **Read citations** is saved and initially enabled. Disable it to omit recognized author–year references, `[12]`-style citations and explicit footnote markers. Book formatting and visible citations remain unchanged. Unusual citation formats can require manual review; ordinary quotations and mathematical superscripts are retained.
- Successful audio is saved in IndexedDB by engine/model, spoken text, voice and effective speed, and identical pending requests share a promise. Stop/seek detaches playback while started requests finish into the cache. Reopening or reloading can reuse completed audio. Failed requests are retried only through an explicit user action. Clearing browser storage, storage failure, closing during an unfinished request, or using another browser/device can require new requests. Audio cache size grows with use; there is no automatic eviction from disk.
- Visible speed `0%` sends `-15%` to the service. The default voice is `en-US-BrianMultilingualNeural`. Volume is local to browser playback.
- Streamlit and the voice service have resource and availability limits. `edge-tts` uses an unofficial free service that may be slow or unavailable, particularly from some cloud networks.
- The reader preserves normal book markup, local images, fonts and scoped CSS, while blocking scripts and external book resources. Some advanced EPUB layouts or SVG features may differ from a dedicated reading application. Dark mode adapts book text colors for contrast; light mode restores the original colors.
- Browsers may require another tap on Play after audio finishes preparing, and may pause playback in the background or when a phone locks. Keep the reader tab open for continuous playback.

## Checks

Run the backend checks from `web/`, then enter `frontend/` for browser checks:

```sh
python -m unittest discover -s tests -v
cd frontend
npm test
npm run test:browser
# With local Streamlit running and Google Chrome installed:
node tests/browser-check.mjs
node tests/link-check.mjs
```

The automated browser suite (`npm run test:browser`) checks rolling refill, delayed/out-of-order responses, five-sentence backward and forward navigation, and duplicate prevention using a simulated voice service.

The live browser check uses an invented EPUB and muted playback. It verifies real speech, whole-sentence requests and highlights for initials and ordinals, five preloaded sentences, formatting, all sections, clicking a sentence, bookmarking, restoring progress, light/dark mode and a narrow viewport. It never uses a book from your library.

The link check covers reading a label before navigation, pause/resume, cancellation, navigation within and between sections, body and named anchors, keyboard activation, and missing targets. Set `YAPBOOK_TEST_URL` to test a local server on a port other than 8501.

For an optional real GPU check, run `npm run build`, start `npm exec vite preview -- --host 127.0.0.1 --port 4181 --strictPort` in one terminal, and run `node tests/kokoro-live-check.mjs` in another. It uses an invented English sample and verifies that the production worker returns nonempty WAV audio. This test downloads the model; ordinary automated tests simulate the GPU worker and make no external voice requests.
