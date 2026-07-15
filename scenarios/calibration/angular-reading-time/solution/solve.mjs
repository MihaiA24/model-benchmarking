#!/usr/bin/env node
import fs from 'node:fs';

const path = '/workspace/repository/src/app/features/article/components/article-preview.component.ts';
const source = fs.readFileSync(path, 'utf8');
const needle = '  toggleFavorite(favorited: boolean): void {';
if (source.split(needle).length !== 2) {
  throw new Error('component insertion point was not found exactly once');
}
const method = `  getReadingTime(body: string): number {
    const words = body.trim().split(/\\s+/).filter(Boolean);
    return Math.max(1, Math.ceil(words.length / 200));
  }

`;
fs.writeFileSync(path, source.replace(needle, method + needle));
