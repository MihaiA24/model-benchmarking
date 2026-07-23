# Filter articles by author

Update `src/reducers/articleList.js` so the article-list reducer handles an action shaped as `{ type: 'FILTER_BY_AUTHOR', author: string }`.

For that action, the reducer must:

- keep only articles whose `article.author.username` strictly equals `action.author`;
- preserve the relative order of matching articles;
- set `filteredByAuthor` to the requested author; and
- preserve every unrelated state field.

Existing behavior for every unrelated action must remain unchanged. Only `src/reducers/articleList.js` may be modified.
