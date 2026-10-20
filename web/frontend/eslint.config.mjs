import security from 'eslint-plugin-security';
import noUnsanitized from 'eslint-plugin-no-unsanitized';

const browserNames = ['window','document','location','navigator','localStorage','indexedDB','IDBKeyRange','Audio','EventTarget','URL','Blob','File','DOMParser','CSSStyleSheet','CSSRule','Node','CSS','Highlight','TextDecoder','TextEncoder','AbortController','DOMException','crypto','performance','atob','btoa','setTimeout','clearTimeout','setInterval','clearInterval','queueMicrotask','console','requestAnimationFrame','cancelAnimationFrame','fetch'];
export default [{
  files: ['**/*.mjs','**/*.jsx'],
  ignores: ['dist/**','node_modules/**','test-output/**'],
  plugins: {security, 'no-unsanitized': noUnsanitized},
  languageOptions: {ecmaVersion: 'latest', sourceType: 'module', parserOptions: {ecmaFeatures: {jsx: true}},
    globals: Object.fromEntries([...browserNames, 'process', 'Buffer'].map(name => [name, 'readonly']))},
  rules: {
    'no-undef': 'error', 'no-dupe-args': 'error', 'no-dupe-keys': 'error',
    'no-unreachable': 'error', 'no-unsafe-finally': 'error', 'valid-typeof': 'error',
    'security/detect-eval-with-expression': 'error',
    'security/detect-new-buffer': 'error', 'security/detect-pseudoRandomBytes': 'error',
    'security/detect-child-process': 'error',
    'no-unsanitized/method': 'error', 'no-unsanitized/property': 'error'
  }
}];
