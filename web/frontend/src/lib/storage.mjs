const FALLBACK = { voice: 'en-US-BrianMultilingualNeural', rate: 0, volume: 100, fontSize: 20, follow: true, readCitations: true, theme: 'light', favorites: [] };
export function readSettings() {
  let value; try { value = JSON.parse(localStorage.getItem('yapbook-settings') || '{}'); } catch { value = {}; }
  if (!value || typeof value !== 'object') value = {};
  const result = { ...FALLBACK, favorites: [] };
  if (typeof value.voice === 'string' && /^[a-z]{2,3}-[A-Z]{2}-.+Neural$/.test(value.voice)) result.voice = value.voice;
  for (const [key, low, high] of [['rate', -50, 100], ['volume', 0, 100], ['fontSize', 14, 36]]) {
    if (Number.isInteger(value[key]) && value[key] >= low && value[key] <= high) result[key] = value[key];
  }
  if (typeof value.follow === 'boolean') result.follow = value.follow;
  if (typeof value.readCitations === 'boolean') result.readCitations = value.readCitations;
  if (['light','dark'].includes(value.theme)) result.theme = value.theme;
  if (Array.isArray(value.favorites)) result.favorites = value.favorites.filter(item => typeof item === 'string' && item.endsWith('Neural'));
  return result;
}
export function saveSettings(settings) { localStorage.setItem('yapbook-settings', JSON.stringify(settings)); }
let connection;
async function db() {
  if (!connection) connection = new Promise((resolve, reject) => {
    const request = indexedDB.open('YapBook', 2);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains('books')) request.result.createObjectStore('books', { keyPath: 'id' });
      if (!request.result.objectStoreNames.contains('speech')) request.result.createObjectStore('speech');
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => { connection = null; reject(new Error('Browser storage is unavailable. You can still read, but books cannot be remembered.')); };
  });
  return connection;
}
async function transact(mode, callback, name = 'books') {
  const database = await db();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(name, mode), request = callback(transaction.objectStore(name));
    transaction.oncomplete = () => resolve(request.result);
    transaction.onerror = () => reject(new Error('Could not save in this browser. Its storage may be full.'));
    transaction.onabort = transaction.onerror;
  });
}
export const getBook = id => transact('readonly', store => store.get(id));
export const getSpeech = key => transact('readonly', store => store.get(key), 'speech');
export const putSpeech = (key, value) => transact('readwrite', store => store.put(value, key), 'speech');
export const listBooks = async () => (await transact('readonly', store => store.getAll())).sort((a, b) => b.opened - a.opened);
export const putBook = book => transact('readwrite', store => store.put(book));
export const deleteBook = id => transact('readwrite', store => store.delete(id));
export async function updateBook(id, fields) {
  const database = await db();
  return new Promise((resolve, reject) => {
    const tx = database.transaction('books', 'readwrite'), store = tx.objectStore('books'), request = store.get(id);
    request.onsuccess = () => { if (request.result) store.put({ ...request.result, ...fields }); };
    tx.oncomplete = () => resolve(); tx.onerror = () => reject(new Error('Could not save your reading position.'));
  });
}
