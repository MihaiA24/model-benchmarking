#!/usr/bin/env node
import fs from 'node:fs';

const target = '/workspace/repository/src/reducers/articleList.js';
const source = fs.readFileSync(target, 'utf8');
const needle = '    case SET_PAGE:\n';
if (source.split(needle).length !== 2) {
  throw new Error('reducer insertion point was not found exactly once');
}
const implementation = `    case 'FILTER_BY_AUTHOR':
      return {
        ...state,
        articles: state.articles.filter(
          article => article.author.username === action.author
        ),
        filteredByAuthor: action.author
      };
`;
fs.writeFileSync(target, source.replace(needle, implementation + needle));
