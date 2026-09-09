import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const cache = new Map();
export function loadTs(file) {
  const path = file instanceof URL ? fileURLToPath(file) : file;
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const nativeRequire = createRequire(path);
  const require = id => {
    if (id.endsWith('.css')) return {};
    if (!id.startsWith('.')) return nativeRequire(id);
    const base = resolve(dirname(path), id);
    const target = [base, base + '.ts', base + '.tsx'].find(existsSync);
    return target ? loadTs(target) : nativeRequire(id);
  };
  const js = ts.transpileModule(readFileSync(path, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  }).outputText;
  new Function('require', 'module', 'exports', js)(require, module, module.exports);
  return module.exports;
}
