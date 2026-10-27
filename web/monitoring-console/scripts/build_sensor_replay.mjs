// Uses the already installed Vite toolchain; generated CLI stays outside Git.
import { build } from 'vite';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const outDir = resolve(process.argv[2] ?? '/tmp/aegis76a-cli');
if (!outDir.startsWith('/tmp/')) throw Error('Build output must be under /tmp/');
await build({configFile: false, root: fileURLToPath(new URL('..', import.meta.url)),
  build: {ssr: fileURLToPath(new URL('../src/sensor/replay-cli.ts', import.meta.url)), outDir, emptyOutDir: false,
    rollupOptions: {output: {entryFileNames: 'sensor-replay.mjs'}}}});
