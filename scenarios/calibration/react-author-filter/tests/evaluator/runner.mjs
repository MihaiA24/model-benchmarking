#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { isDeepStrictEqual } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';

const OPERATION = 'evaluate-functional-v1-react-author-filter';
const REQUEST_PATH = '/request/request.json';
const RESULT_PATH = '/result/result.json';
const MAX_REQUEST_BYTES = 256 * 1024;
const MAX_RESULT_BYTES = 1024 * 1024;
const repositoryRoot = fs.realpathSync('/repository');
const context = vm.createContext(Object.create(null), {
  codeGeneration: { strings: false, wasm: false },
  name: 'submitted-react-reducer',
});
const moduleCache = new Map();

const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

function exactKeys(value, expected) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('object required');
  }
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (!isDeepStrictEqual(actual, wanted)) throw new Error('unexpected object keys');
}

function validateJsonValue(value, budget, depth = 0) {
  if (depth > 20) throw new Error('JSON nesting limit exceeded');
  budget.nodes += 1;
  if (budget.nodes > 10000) throw new Error('JSON node limit exceeded');
  if (value === null || typeof value === 'boolean') return;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error('finite number required');
    return;
  }
  if (typeof value === 'string') {
    if (value.length > 10000) throw new Error('string limit exceeded');
    return;
  }
  if (Array.isArray(value)) {
    if (value.length > 1000) throw new Error('array limit exceeded');
    for (const item of value) validateJsonValue(item, budget, depth + 1);
    return;
  }
  if (typeof value !== 'object') throw new Error('JSON value required');
  const keys = Object.keys(value);
  if (keys.length > 1000) throw new Error('object key limit exceeded');
  for (const key of keys) {
    if (key.length > 256 || ['__proto__', 'constructor', 'prototype'].includes(key)) {
      throw new Error('object key rejected');
    }
    validateJsonValue(value[key], budget, depth + 1);
  }
}

async function readRequest() {
  for (let attempt = 0; attempt < 600; attempt += 1) {
    if (fs.existsSync(REQUEST_PATH)) break;
    await sleep(50);
  }
  const stat = fs.lstatSync(REQUEST_PATH);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > MAX_REQUEST_BYTES) {
    throw new Error('invalid request file');
  }
  const encoded = fs.readFileSync(REQUEST_PATH, 'utf8');
  if (Buffer.byteLength(encoded) > MAX_REQUEST_BYTES) throw new Error('request too large');
  const request = JSON.parse(encoded);
  exactKeys(request, ['cases', 'operation', 'schemaVersion']);
  if (request.schemaVersion !== 1 || request.operation !== OPERATION) {
    throw new Error('unsupported request');
  }
  if (!Array.isArray(request.cases) || request.cases.length === 0 || request.cases.length > 32) {
    throw new Error('case count rejected');
  }
  const identifiers = new Set();
  for (const testCase of request.cases) {
    exactKeys(testCase, ['action', 'id', 'state']);
    if (typeof testCase.id !== 'string' || !/^[a-z0-9-]{1,64}$/.test(testCase.id)) {
      throw new Error('case identifier rejected');
    }
    if (identifiers.has(testCase.id)) throw new Error('duplicate case identifier');
    identifiers.add(testCase.id);
    exactKeys(testCase.state, Object.keys(testCase.state));
    exactKeys(testCase.action, Object.keys(testCase.action));
    if (typeof testCase.action.type !== 'string' || testCase.action.type.length > 128) {
      throw new Error('action type rejected');
    }
    validateJsonValue(testCase.state, { nodes: 0 });
    validateJsonValue(testCase.action, { nodes: 0 });
  }
  return request;
}

function withinRepository(candidate) {
  return candidate === repositoryRoot || candidate.startsWith(`${repositoryRoot}${path.sep}`);
}

function resolveImport(specifier, referencingIdentifier) {
  if (!specifier.startsWith('.')) throw new Error('external import rejected');
  const referencingPath = fileURLToPath(referencingIdentifier);
  let candidate = path.resolve(path.dirname(referencingPath), specifier);
  if (path.extname(candidate) === '') candidate += '.js';
  candidate = fs.realpathSync(candidate);
  if (!withinRepository(candidate)) throw new Error('import escaped repository');
  return candidate;
}

async function loadModule(candidate) {
  const file = fs.realpathSync(candidate);
  if (!withinRepository(file)) throw new Error('module escaped repository');
  const cached = moduleCache.get(file);
  if (cached) return cached;
  const source = fs.readFileSync(file, 'utf8');
  if (Buffer.byteLength(source) > 100000) throw new Error('module too large');
  const identifier = pathToFileURL(file).href;
  const module = new vm.SourceTextModule(source, {
    context,
    identifier,
    importModuleDynamically: async () => { throw new Error('dynamic import rejected'); },
  });
  moduleCache.set(file, module);
  await module.link((specifier, referencingModule) => (
    loadModule(resolveImport(specifier, referencingModule.identifier))
  ));
  return module;
}

function deepFreeze(value) {
  if (value === null || typeof value !== 'object' || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

function isDeepFrozen(value) {
  if (value === null || typeof value !== 'object') return true;
  return Object.isFrozen(value) && Object.values(value).every(isDeepFrozen);
}

function jsonCloneBounded(value) {
  const encoded = JSON.stringify(value);
  if (encoded === undefined || Buffer.byteLength(encoded) > 65536) {
    throw new Error('case result rejected');
  }
  return JSON.parse(encoded);
}

function evaluateCase(testCase, reducer, moduleError) {
  const state = structuredClone(testCase.state);
  const action = structuredClone(testCase.action);
  const snapshot = structuredClone(state);
  deepFreeze(state);
  deepFreeze(action);
  let errorCode = moduleError ? 'module-load-failed' : null;
  let outcome = null;
  let sameStateReference = false;
  if (!errorCode) {
    try {
      context.__reducer = reducer;
      context.__state = state;
      context.__action = action;
      const rawOutcome = vm.runInContext('__reducer(__state, __action)', context, { timeout: 2000 });
      sameStateReference = rawOutcome === state;
      outcome = jsonCloneBounded(rawOutcome);
    } catch {
      errorCode = 'evaluation-failed';
    } finally {
      delete context.__reducer;
      delete context.__state;
      delete context.__action;
    }
  }
  return {
    errorCode,
    id: testCase.id,
    inputFrozen: isDeepFrozen(state),
    inputUnchanged: isDeepStrictEqual(state, snapshot),
    outcome,
    sameStateReference,
  };
}

async function evaluate(request) {
  let reducer = null;
  let moduleError = false;
  try {
    const module = await loadModule(path.join(repositoryRoot, 'src/reducers/articleList.js'));
    await module.evaluate({ timeout: 5000 });
    reducer = module.namespace.default;
    if (typeof reducer !== 'function') moduleError = true;
  } catch {
    moduleError = true;
  }
  return {
    cases: request.cases.map(testCase => evaluateCase(testCase, reducer, moduleError)),
    evaluatorStatus: 'complete',
    operation: OPERATION,
    schemaVersion: 1,
  };
}

let response;
try {
  response = await evaluate(await readRequest());
} catch {
  response = {
    cases: [],
    errorCode: 'invalid-request',
    evaluatorStatus: 'error',
    operation: OPERATION,
    schemaVersion: 1,
  };
}
let encoded = `${JSON.stringify(response)}\n`;
if (Buffer.byteLength(encoded) > MAX_RESULT_BYTES) {
  encoded = `${JSON.stringify({
    cases: [],
    errorCode: 'result-too-large',
    evaluatorStatus: 'error',
    operation: OPERATION,
    schemaVersion: 1,
  })}\n`;
}
const temporary = `${RESULT_PATH}.tmp`;
fs.writeFileSync(temporary, encoded, { flag: 'wx', mode: 0o600 });
fs.renameSync(temporary, RESULT_PATH);
for (let attempt = 0; attempt < 600 && !fs.existsSync('/result/ack'); attempt += 1) {
  await sleep(50);
}
