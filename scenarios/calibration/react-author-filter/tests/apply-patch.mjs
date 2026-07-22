#!/usr/bin/env node
import fs from 'node:fs';

const [, , targetPath, patchPath] = process.argv;
const original = fs.readFileSync(targetPath, 'utf8');
const patch = fs.readFileSync(patchPath, 'utf8');
if (patch.length === 0) process.exit(0);

const source = original.match(/[^\n]*\n|[^\n]+$/g) ?? [];
const lines = patch.match(/[^\n]*\n|[^\n]+$/g) ?? [];
const output = [];
let sourceIndex = 0;
let index = 0;
while (index < lines.length) {
  const match = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(lines[index]);
  if (!match) {
    index += 1;
    continue;
  }
  const oldStart = Number(match[1]) - 1;
  if (oldStart < sourceIndex) throw new Error('overlapping patch hunks');
  output.push(...source.slice(sourceIndex, oldStart));
  sourceIndex = oldStart;
  index += 1;
  while (index < lines.length && !lines[index].startsWith('@@ ') && !lines[index].startsWith('diff --git ')) {
    const line = lines[index];
    if (line.startsWith('\\ No newline at end of file')) {
      index += 1;
      continue;
    }
    const marker = line[0];
    const content = line.slice(1);
    if (marker === ' ' || marker === '-') {
      if (source[sourceIndex] !== content) throw new Error('patch context does not match baseline');
      if (marker === ' ') output.push(content);
      sourceIndex += 1;
    } else if (marker === '+') {
      output.push(content);
    } else {
      break;
    }
    index += 1;
  }
}
output.push(...source.slice(sourceIndex));
fs.writeFileSync(targetPath, output.join(''));
