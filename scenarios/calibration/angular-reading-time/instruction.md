# Developer Brief

Complete the reading-time behavior in the article preview component.

The preview template already renders `getReadingTime(article().body)` as minutes. Implement `getReadingTime(body: string): number` so it counts whitespace-separated words, uses 200 words per minute, rounds partial minutes up, and returns a minimum of one minute for empty or short content.

Preserve the component's signal input, favorite-toggle behavior, OnPush change detection, and existing template. Change only `src/app/features/article/components/article-preview.component.ts`.
