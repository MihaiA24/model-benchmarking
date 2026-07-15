#!/usr/bin/env node
import fs from 'node:fs';

const source = fs.readFileSync(
  '/tmp/submitted-repository/src/app/features/article/components/article-preview.component.ts',
  'utf8',
);

function methodImplementation() {
  const signature = /getReadingTime\s*\(\s*body\s*:\s*string\s*\)\s*:\s*number\s*\{/g;
  const match = signature.exec(source);
  if (!match) return null;
  const start = match.index + match[0].length;
  let depth = 1;
  let quote = null;
  let escaped = false;
  for (let index = start; index < source.length; index += 1) {
    const character = source[index];
    if (quote !== null) {
      if (escaped) escaped = false;
      else if (character === '\\') escaped = true;
      else if (character === quote) quote = null;
      continue;
    }
    if (character === "'" || character === '"' || character === '`') {
      quote = character;
    } else if (character === '{') {
      depth += 1;
    } else if (character === '}') {
      depth -= 1;
      if (depth === 0) {
        const body = source.slice(start, index)
          .replace(/:\s*(?:string|number|boolean)(?:\[\])?\s*(?=[=;,])/g, '');
        try {
          return new Function('body', body);
        } catch {
          return null;
        }
      }
    }
  }
  return null;
}

function words(count) {
  return Array.from({ length: count }, (_, index) => `word${index}`).join(' ');
}

function acceptance() {
  const implementation = methodImplementation();
  return implementation !== null
    && source.includes('{{ getReadingTime(article().body) }} min read')
    && implementation(words(200)) === 1
    && implementation(words(201)) === 2;
}

function regression() {
  return source.includes('article = signal<Article>(null!);')
    && source.includes('toggleFavorite(favorited: boolean): void')
    && source.includes('favoritesCount: favorited ? article.favoritesCount + 1 : article.favoritesCount - 1');
}

function domain() {
  const implementation = methodImplementation();
  return implementation !== null
    && implementation('') === 1
    && implementation(' \t\n ') === 1
    && implementation('one\ttwo\nthree') === 1
    && implementation(words(400)) === 2
    && implementation(words(401)) === 3;
}

const checks = { acceptance: acceptance(), domain: domain(), regression: regression() };
const scores = {
  acceptance_score: Number(checks.acceptance),
  reading_time_behavior: Number(checks.domain),
  regression_score: Number(checks.regression),
  task_success: Number(checks.acceptance && checks.domain && checks.regression),
};
const status = value => value ? 'pass' : 'fail';
const result = {
  acceptance_score: scores.acceptance_score,
  reading_time_behavior: scores.reading_time_behavior,
  checks: [
    { evidence: ['article-preview.component.ts', 'rendered-reading-time-cases'], id: 'preview-output', status: status(checks.acceptance) },
    { evidence: ['article-preview.component.ts', 'favorite-toggle-boundary'], id: 'component-regression', status: status(checks.regression) },
    { evidence: ['reading-time-boundary-matrix'], id: 'reading-time-boundaries', status: status(checks.domain) },
  ],
  domain_scores: { reading_time_behavior: scores.reading_time_behavior },
  regression_score: scores.regression_score,
  required_group_statuses: {
    'component-regression': status(checks.regression),
    'preview-output': status(checks.acceptance),
    'reading-time-boundaries': status(checks.domain),
  },
  task_success: Boolean(scores.task_success),
  verifier_complete: true,
};
fs.mkdirSync('/logs/verifier', { recursive: true });
fs.writeFileSync('/logs/verifier/verifier-result.json', `${JSON.stringify(result)}\n`);
fs.writeFileSync('/logs/verifier/reward.json', `${JSON.stringify(scores)}\n`);
