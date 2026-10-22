import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  base: './',
  server: { host: '127.0.0.1', hmr: false, fs: { allow: [
    fileURLToPath(new URL('.', import.meta.url)),
    fileURLToPath(new URL('../../examples/sensor_telemetry_example.json', import.meta.url)),
    fileURLToPath(new URL('../../examples/sensor_telemetry_example.json', import.meta.url)) + '?raw',
    fileURLToPath(new URL('../../configs/simulation/sensor-telemetry-v1.schema.json', import.meta.url)),
  ] } },
  build: { outDir: 'dist', target: 'es2022' },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'], include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'] },
});
