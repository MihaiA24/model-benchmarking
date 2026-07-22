#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repositoryRoot = fs.realpathSync('/tmp/submitted-repository');
const moduleCache = new Map();

function withinRepository(candidate) {
  return candidate === repositoryRoot || candidate.startsWith(`${repositoryRoot}${path.sep}`);
}

function resolveImport(specifier, referencingIdentifier) {
  if (!specifier.startsWith('.')) {
    throw new Error(`external module import is not permitted: ${specifier}`);
  }
  const referencingPath = fileURLToPath(referencingIdentifier);
  let candidate = path.resolve(path.dirname(referencingPath), specifier);
  if (path.extname(candidate) === '') candidate += '.js';
  candidate = fs.realpathSync(candidate);
  if (!withinRepository(candidate)) throw new Error('module import escaped the repository');
  return candidate;
}

async function loadModule(candidate) {
  const file = fs.realpathSync(candidate);
  if (!withinRepository(file)) throw new Error('module path escaped the repository');
  const cached = moduleCache.get(file);
  if (cached) return cached;
  const identifier = pathToFileURL(file).href;
  const module = new vm.SourceTextModule(fs.readFileSync(file, 'utf8'), { identifier });
  moduleCache.set(file, module);
  await module.link((specifier, referencingModule) => (
    loadModule(resolveImport(specifier, referencingModule.identifier))
  ));
  return module;
}

let reducer = null;
let actionTypes = null;
try {
  const reducerModule = await loadModule(path.join(repositoryRoot, 'src/reducers/articleList.js'));
  await reducerModule.evaluate();
  reducer = reducerModule.namespace.default;
  const constantsModule = await loadModule(path.join(repositoryRoot, 'src/constants/actionTypes.js'));
  actionTypes = constantsModule.namespace;
} catch {
  reducer = null;
  actionTypes = null;
}

function check(run) {
  try {
    assert.equal(typeof reducer, 'function');
    run();
    return true;
  } catch {
    return false;
  }
}

const outputPassed = check(() => {
  const articles = [
    { slug: 'first', author: { username: 'alice' } },
    { slug: 'second', author: { username: 'bob' } },
    { slug: 'third', author: { username: 'alice' } },
    { slug: 'case-near-match', author: { username: 'Alice' } },
    { slug: 'coercible-near-match', author: { username: new String('alice') } },
  ];
  const result = reducer(
    { articles, articlesCount: articles.length },
    { type: 'FILTER_BY_AUTHOR', author: 'alice' },
  );
  assert.deepEqual(result.articles.map(article => article.slug), ['first', 'third']);

  const empty = reducer(
    { articles, articlesCount: articles.length },
    { type: 'FILTER_BY_AUTHOR', author: 'nobody' },
  );
  assert.deepEqual(empty.articles, []);
});

const statePassed = check(() => {
  const pager = { page: 3 };
  const unrelated = { nested: ['preserve', 7] };
  const state = {
    articles: [
      { slug: 'one', author: { username: 'alice' } },
      { slug: 'two', author: { username: 'bob' } },
    ],
    articlesCount: 2,
    currentPage: 3,
    filteredByAuthor: 'previous',
    pager,
    tag: 'redux',
    unrelated,
  };
  const result = reducer(state, { type: 'FILTER_BY_AUTHOR', author: 'alice' });
  assert.equal(result.filteredByAuthor, 'alice');
  const { articles: _articles, filteredByAuthor: _filter, ...rest } = result;
  const { articles: _originalArticles, filteredByAuthor: _originalFilter, ...expected } = state;
  assert.deepEqual(rest, expected);
});

const regressionPassed = check(() => {
  assert.ok(actionTypes);
  const untouched = { articles: [], sentinel: { retained: true } };
  assert.equal(reducer(untouched, { type: 'UNRELATED_ACTION' }), untouched);

  const state = {
    articles: [
      { slug: 'target', favorited: false, favoritesCount: 4 },
      { slug: 'other', favorited: false, favoritesCount: 2 },
    ],
    sentinel: 'keep',
  };
  const result = reducer(state, {
    type: actionTypes.ARTICLE_FAVORITED,
    payload: { article: { slug: 'target', favorited: true, favoritesCount: 5 } },
  });
  assert.deepEqual(result, {
    articles: [
      { slug: 'target', favorited: true, favoritesCount: 5 },
      { slug: 'other', favorited: false, favoritesCount: 2 },
    ],
    sentinel: 'keep',
  });
});

const status = passed => (passed ? 'pass' : 'fail');
const taskSuccess = outputPassed && statePassed && regressionPassed;
const scores = {
  acceptance_score: Number(outputPassed),
  author_filter_state: Number(statePassed),
  regression_score: Number(regressionPassed),
  task_success: Number(taskSuccess),
};
const result = {
  acceptance_score: scores.acceptance_score,
  author_filter_state: scores.author_filter_state,
  checks: [
    { evidence: ['author-filter-behavior-matrix'], id: 'author-filter-output', status: status(outputPassed) },
    { evidence: ['state-preservation-matrix'], id: 'author-filter-state', status: status(statePassed) },
    { evidence: ['existing-reducer-behavior'], id: 'reducer-regression', status: status(regressionPassed) },
  ],
  domain_scores: { author_filter_state: scores.author_filter_state },
  regression_score: scores.regression_score,
  required_group_statuses: {
    'author-filter-output': status(outputPassed),
    'author-filter-state': status(statePassed),
    'reducer-regression': status(regressionPassed),
  },
  task_success: taskSuccess,
  verifier_complete: true,
};
fs.mkdirSync('/logs/verifier', { recursive: true });
fs.writeFileSync('/logs/verifier/verifier-result.json', `${JSON.stringify(result)}\n`);
fs.writeFileSync('/logs/verifier/reward.json', `${JSON.stringify(scores)}\n`);
