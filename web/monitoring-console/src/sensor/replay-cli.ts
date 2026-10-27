/** Read-only local Phase 75D inspection entry point. Bundle with existing Vite. */
import { open } from 'node:fs/promises';
import { constants } from 'node:fs';
import { parseArgs } from 'node:util';
import { MAX_BYTES } from './model';
import { encodeReplay, replayInspections } from './replay';
async function main() {
  const {values, positionals} = parseArgs({allowPositionals: true, options: {
    domain: {type: 'string'}, 'evaluation-ns': {type: 'string'}, 'stale-after-ns': {type: 'string'},
  }});
  if (!values.domain || !values['evaluation-ns'] || !values['stale-after-ns'] || positionals.length < 1 || positionals.length > 2)
    throw Error('Usage: sensor-replay.mjs --domain DOMAIN --evaluation-ns NS --stale-after-ns NS LOCAL_INSPECTION.json [SECOND.json]');
  const texts: string[] = [];
  for (const path of positionals) {
    if (/^(?:[a-z]+:|\\\\)/i.test(path)) throw Error('Local file required');
    const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    try {
      const stat = await file.stat();
      if (!stat.isFile() || stat.size > MAX_BYTES) throw Error('BOUND: regular local file at most 8 MiB required');
      const buffer = Buffer.alloc(stat.size + 1); let count = 0;
      while (count < buffer.length) {
        const {bytesRead} = await file.read(buffer, count, buffer.length - count, null);
        if (!bytesRead) break;
        count += bytesRead;
      }
      if (count > stat.size) throw Error('BOUND: input grew while reading');
      texts.push(new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(buffer.subarray(0, count)));
    } finally {await file.close();}
  }
  const output = await replayInspections(texts, {schema_version: 1, value_ns: values['evaluation-ns'], domain: values.domain, unit: 'ns'}, values['stale-after-ns']);
  process.stdout.write(encodeReplay(output));
}
main().catch(error => {process.stderr.write(`Offline replay rejected: ${error instanceof Error ? error.message : 'Invalid input'}\n`); process.exitCode = 2;});
