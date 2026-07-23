#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';

const OPERATION = 'evaluate-functional-v1-react-author-filter';
const REQUEST_PATH = '/evaluator-request/request.json';
const RESULT_PATH = '/evaluator-result/result.json';
const specs = [];

function addCase(id, group, state, action, expectedOutcome, sameStateReference = false) {
  specs.push({ id, group, state, action, expectedOutcome, sameStateReference });
}

const filterArticles = [
  { slug: 'first', author: { username: 'alice' } },
  { slug: 'second', author: { username: 'bob' } },
  { slug: 'third', author: { username: 'alice' } },
  { slug: 'case-near-match', author: { username: 'Alice' } },
  { slug: 'coercible-near-match', author: { username: 1 } },
];
const filterState = { articles: filterArticles, articlesCount: filterArticles.length };
addCase(
  'filter-matches',
  'output',
  filterState,
  { type: 'FILTER_BY_AUTHOR', author: 'alice' },
  { ...filterState, articles: [filterArticles[0], filterArticles[2]], filteredByAuthor: 'alice' },
);
addCase(
  'filter-zero-match',
  'output',
  filterState,
  { type: 'FILTER_BY_AUTHOR', author: 'nobody' },
  { ...filterState, articles: [], filteredByAuthor: 'nobody' },
);
const preservedState = {
  articles: [
    { slug: 'one', author: { username: 'alice' } },
    { slug: 'two', author: { username: 'bob' } },
  ],
  articlesCount: 2,
  currentPage: 3,
  filteredByAuthor: 'previous',
  pager: { page: 3 },
  tag: 'redux',
  unrelated: { nested: ['preserve', 7] },
};
addCase(
  'filter-preserves-state',
  'state',
  preservedState,
  { type: 'FILTER_BY_AUTHOR', author: 'alice' },
  {
    ...preservedState,
    articles: [preservedState.articles[0]],
    filteredByAuthor: 'alice',
  },
);

const favoriteState = {
  articles: [
    { slug: 'target', favorited: false, favoritesCount: 4 },
    { slug: 'other', favorited: true, favoritesCount: 2 },
  ],
  sentinel: 'keep',
};
addCase(
  'article-favorited',
  'regression',
  favoriteState,
  {
    type: 'ARTICLE_FAVORITED',
    payload: { article: { slug: 'target', favorited: true, favoritesCount: 5 } },
  },
  {
    ...favoriteState,
    articles: [
      { slug: 'target', favorited: true, favoritesCount: 5 },
      favoriteState.articles[1],
    ],
  },
);
const unfavoriteState = {
  articles: [
    { slug: 'target', favorited: true, favoritesCount: 5 },
    { slug: 'other', favorited: false, favoritesCount: 2 },
  ],
  sentinel: 'keep',
};
addCase(
  'article-unfavorited',
  'regression',
  unfavoriteState,
  {
    type: 'ARTICLE_UNFAVORITED',
    payload: { article: { slug: 'target', favorited: false, favoritesCount: 4 } },
  },
  {
    ...unfavoriteState,
    articles: [
      { slug: 'target', favorited: false, favoritesCount: 4 },
      unfavoriteState.articles[1],
    ],
  },
);
const pageState = {
  articles: [{ slug: 'old' }],
  articlesCount: 1,
  currentPage: 4,
  sentinel: 'keep',
};
const pagePayload = { articles: [{ slug: 'new-page' }], articlesCount: 7 };
addCase(
  'set-page',
  'regression',
  pageState,
  { type: 'SET_PAGE', payload: pagePayload, page: 2 },
  { ...pageState, ...pagePayload, currentPage: 2 },
);
const tagState = {
  articles: [{ slug: 'old' }],
  articlesCount: 1,
  currentPage: 4,
  pager: { id: 'old-pager' },
  sentinel: 'keep',
  tab: 'global',
  tag: 'old-tag',
};
const tagAction = {
  type: 'APPLY_TAG_FILTER',
  pager: { id: 'tag-pager' },
  payload: { articles: [{ slug: 'tagged' }], articlesCount: 2 },
  tag: 'react',
};
addCase(
  'apply-tag-filter',
  'regression',
  tagState,
  tagAction,
  {
    ...tagState,
    pager: tagAction.pager,
    articles: tagAction.payload.articles,
    articlesCount: tagAction.payload.articlesCount,
    tab: null,
    tag: 'react',
    currentPage: 0,
  },
);
const homeState = {
  articles: [{ slug: 'old' }],
  articlesCount: 1,
  currentPage: 4,
  pager: { id: 'old-pager' },
  sentinel: 'keep',
  tab: 'old-tab',
  tags: ['old'],
};
const homeAction = {
  type: 'HOME_PAGE_LOADED',
  pager: { id: 'home-pager' },
  payload: [
    { tags: ['react', 'redux'] },
    { articles: [{ slug: 'home' }], articlesCount: 9 },
  ],
  tab: 'feed',
};
addCase(
  'home-page-loaded',
  'regression',
  homeState,
  homeAction,
  {
    ...homeState,
    pager: homeAction.pager,
    tags: homeAction.payload[0].tags,
    articles: homeAction.payload[1].articles,
    articlesCount: homeAction.payload[1].articlesCount,
    currentPage: 0,
    tab: 'feed',
  },
);
addCase(
  'home-page-unloaded',
  'regression',
  { articles: [{ slug: 'old' }], sentinel: 'discard' },
  { type: 'HOME_PAGE_UNLOADED' },
  {},
);
const tabState = {
  articles: [{ slug: 'old' }],
  articlesCount: 1,
  currentPage: 4,
  pager: { id: 'old-pager' },
  sentinel: 'keep',
  tab: 'old-tab',
  tag: 'react',
};
const tabAction = {
  type: 'CHANGE_TAB',
  pager: { id: 'tab-pager' },
  payload: { articles: [{ slug: 'tabbed' }], articlesCount: 3 },
  tab: 'all',
};
addCase(
  'change-tab',
  'regression',
  tabState,
  tabAction,
  {
    ...tabState,
    pager: tabAction.pager,
    articles: tabAction.payload.articles,
    articlesCount: tabAction.payload.articlesCount,
    tab: 'all',
    currentPage: 0,
    tag: null,
  },
);
const profileState = {
  articles: [{ slug: 'old' }],
  articlesCount: 1,
  currentPage: 4,
  pager: { id: 'old-pager' },
  sentinel: 'keep',
};
const profileAction = {
  type: 'PROFILE_PAGE_LOADED',
  pager: { id: 'profile-pager' },
  payload: [
    { profile: { username: 'alice' } },
    { articles: [{ slug: 'profile' }], articlesCount: 4 },
  ],
};
addCase(
  'profile-page-loaded',
  'regression',
  profileState,
  profileAction,
  {
    ...profileState,
    pager: profileAction.pager,
    articles: profileAction.payload[1].articles,
    articlesCount: profileAction.payload[1].articlesCount,
    currentPage: 0,
  },
);
const favoritesAction = {
  type: 'PROFILE_FAVORITES_PAGE_LOADED',
  pager: { id: 'favorites-pager' },
  payload: [
    { profile: { username: 'alice' } },
    { articles: [{ slug: 'favorite' }], articlesCount: 5 },
  ],
};
addCase(
  'profile-favorites-page-loaded',
  'regression',
  profileState,
  favoritesAction,
  {
    ...profileState,
    pager: favoritesAction.pager,
    articles: favoritesAction.payload[1].articles,
    articlesCount: favoritesAction.payload[1].articlesCount,
    currentPage: 0,
  },
);
addCase(
  'profile-page-unloaded',
  'regression',
  { articles: [{ slug: 'old' }], sentinel: 'discard' },
  { type: 'PROFILE_PAGE_UNLOADED' },
  {},
);
addCase(
  'profile-favorites-page-unloaded',
  'regression',
  { articles: [{ slug: 'old' }], sentinel: 'discard' },
  { type: 'PROFILE_FAVORITES_PAGE_UNLOADED' },
  {},
);
const defaultState = { articles: [], sentinel: { retained: true } };
addCase(
  'default',
  'regression',
  defaultState,
  { type: 'UNRELATED_ACTION' },
  defaultState,
  true,
);

const request = {
  cases: specs.map(({ id, state, action }) => ({ id, state, action })),
  operation: OPERATION,
  schemaVersion: 1,
};
const requestTemporary = `${REQUEST_PATH}.tmp`;
fs.writeFileSync(requestTemporary, `${JSON.stringify(request)}\n`, { flag: 'wx', mode: 0o600 });
fs.renameSync(requestTemporary, REQUEST_PATH);

for (let attempt = 0; attempt < 1200 && !fs.existsSync(RESULT_PATH); attempt += 1) {
  await new Promise(resolve => setTimeout(resolve, 50));
}
const resultStat = fs.lstatSync(RESULT_PATH);
assert.ok(resultStat.isFile() && !resultStat.isSymbolicLink());
assert.ok(resultStat.size <= 1024 * 1024);
const evaluation = JSON.parse(fs.readFileSync(RESULT_PATH, 'utf8'));
assert.deepEqual(Object.keys(evaluation).sort(), [
  'cases',
  'evaluatorStatus',
  'operation',
  'schemaVersion',
]);
assert.equal(evaluation.schemaVersion, 1);
assert.equal(evaluation.operation, OPERATION);
assert.equal(evaluation.evaluatorStatus, 'complete');
assert.ok(Array.isArray(evaluation.cases));
assert.equal(evaluation.cases.length, specs.length);
const responses = new Map();
for (const response of evaluation.cases) {
  assert.deepEqual(Object.keys(response).sort(), [
    'errorCode',
    'id',
    'inputFrozen',
    'inputUnchanged',
    'outcome',
    'sameStateReference',
  ]);
  assert.equal(typeof response.id, 'string');
  assert.ok(!responses.has(response.id));
  responses.set(response.id, response);
}
assert.deepEqual([...responses.keys()].sort(), specs.map(spec => spec.id).sort());

const passedById = new Map();
for (const spec of specs) {
  const response = responses.get(spec.id);
  let passed = false;
  try {
    assert.equal(response.errorCode, null);
    assert.equal(response.inputFrozen, true);
    assert.equal(response.inputUnchanged, true);
    assert.equal(response.sameStateReference, spec.sameStateReference);
    assert.deepEqual(response.outcome, spec.expectedOutcome);
    passed = true;
  } catch {
    passed = false;
  }
  passedById.set(spec.id, passed);
}
const groupPassed = group => specs
  .filter(spec => spec.group === group)
  .every(spec => passedById.get(spec.id));
const outputPassed = groupPassed('output');
const statePassed = groupPassed('state');
const regressionPassed = groupPassed('regression');
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
    {
      evidence: ['author-filter-behavior-matrix', 'zero-match-filtered-author'],
      id: 'author-filter-output',
      status: status(outputPassed),
    },
    {
      evidence: ['state-snapshot-deep-freeze', 'state-preservation-matrix'],
      id: 'author-filter-state',
      status: status(statePassed),
    },
    {
      evidence: ['all-original-article-list-branches', 'os-isolated-evaluator'],
      id: 'reducer-regression',
      status: status(regressionPassed),
    },
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
fs.writeFileSync('/evaluator-result/ack.tmp', 'ok\n', { flag: 'wx', mode: 0o600 });
fs.renameSync('/evaluator-result/ack.tmp', '/evaluator-result/ack');
