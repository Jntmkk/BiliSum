#!/usr/bin/env node
/**
 * Generate TypeScript API types from the BiliSum FastAPI service.
 *
 * Usage:
 *   SERVER_URL=http://192.168.1.10:3838 npm run gen:api
 *
 * Requires the service to be running (it serves /openapi.json).
 */
import { execSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const serverUrl = process.env.SERVER_URL ?? 'http://127.0.0.1:3838';
const here = dirname(fileURLToPath(import.meta.url));
const outFile = resolve(here, '../src/api/types.ts');

console.log(`Fetching OpenAPI spec from ${serverUrl}/openapi.json …`);
const res = await fetch(`${serverUrl}/openapi.json`);
if (!res.ok) {
  console.error(`Failed to fetch spec: HTTP ${res.status}`);
  process.exit(1);
}
const spec = await res.json();

console.log('Generating types via openapi-typescript …');
const { astToString, openapiTS } = await import('openapi-typescript');
const ast = await openapiTS(spec);
writeFileSync(outFile, astToString(ast));
console.log(`Wrote ${outFile}`);

// Prettify if available; ignore failure (openapi-typescript output is already readable).
try {
  execSync(`npx --yes prettier --write "${outFile}"`, { stdio: 'ignore' });
} catch {
  /* optional */
}
