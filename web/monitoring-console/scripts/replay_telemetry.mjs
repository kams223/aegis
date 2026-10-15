// Explicit local-file CLI. No automatic writes or wire decoding.
import { open, lstat } from 'node:fs/promises';
import { constants } from 'node:fs';
import { resolve } from 'node:path';
import { loadTelemetryReplay, replayTelemetry, canonicalTelemetry, MAX_TELEMETRY_BYTES } from '../src/flight/telemetry.ts';
async function main() {
  if (process.argv.length !== 3 || /^(?:[a-z]+:|\\\\)/i.test(process.argv[2])) throw new Error('Usage: node scripts/replay_telemetry.mjs LOCAL_REPLAY.json');
  const path = resolve(process.argv[2]);
  const initial = await lstat(path); if (!initial.isFile() || initial.size > MAX_TELEMETRY_BYTES) throw new Error('Regular local replay required');
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await file.stat(); if (!info.isFile() || info.size > MAX_TELEMETRY_BYTES || info.ino !== initial.ino || info.dev !== initial.dev) throw new Error('Replay must be a regular local file at most 1 MiB');
    const buffer = Buffer.alloc(MAX_TELEMETRY_BYTES + 1); let count = 0;
    while (count < buffer.length) { const { bytesRead } = await file.read(buffer, count, buffer.length - count, null); if (!bytesRead) break; count += bytesRead; }
    if (count > MAX_TELEMETRY_BYTES) throw new Error('Replay exceeds 1 MiB');
    const input = new TextDecoder('utf-8', { fatal: true }).decode(buffer.subarray(0, count));
    const output = canonicalTelemetry(replayTelemetry(loadTelemetryReplay(input)));
    process.stdout.write(output + '\n');
  } finally { await file.close(); }
}
main().catch(() => { process.stderr.write('Invalid offline telemetry replay or local input.\n'); process.exitCode = 2; });
