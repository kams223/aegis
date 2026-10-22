// Small, fail-closed validator for the keywords used by the checked-in v1
// telemetry schema. It never resolves $id/$schema or fetches remote schemas.
export type Schema = { type?: string; const?: unknown; enum?: readonly unknown[]; properties?: Record<string, Schema>; required?: readonly string[]; additionalProperties?: boolean; items?: Schema; minItems?: number; maxItems?: number; minLength?: number; maxLength?: number; pattern?: string; minimum?: number; maximum?: number; oneOf?: Schema[]; anyOf?: Schema[] };
export function validate(value: unknown, schema: Schema, path = 'input'): void {
  const fail = (why: string): never => { throw new Error(`${path}: ${why}`); };
  for (const keyword of ['oneOf', 'anyOf'] as const) {
    const choices = schema[keyword];
    if (choices) {
      const matches = choices.filter(choice => { try { validate(value, choice, path); return true; } catch { return false; } }).length;
      if (keyword === 'oneOf' ? matches !== 1 : matches === 0) fail('unknown version, field, unit, frame, or invalid schema variant');
    }
  }
  if ('const' in schema && value !== schema.const) fail('unsupported declared value/version');
  if (schema.enum && !schema.enum.includes(value)) fail('unsupported declared value');
  if (schema.type === 'null' && value !== null) fail('require null');
  if (schema.type === 'object') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) fail('require object');
    const obj = value as Record<string, unknown>;
    for (const key of schema.required ?? []) if (!Object.hasOwn(obj, key)) fail(`missing ${key}`);
    for (const [key, child] of Object.entries(obj)) {
      if (schema.properties && Object.hasOwn(schema.properties, key)) validate(child, schema.properties[key]!, `${path}.${key}`);
      else if (schema.additionalProperties === false) fail(`unknown field ${key}`);
    }
  }
  if (schema.type === 'array') {
    if (!Array.isArray(value)) fail('require array');
    const arr = value as unknown[];
    if (arr.length < (schema.minItems ?? 0) || arr.length > (schema.maxItems ?? Infinity)) fail('array limit');
    if (schema.items) arr.forEach((child, i) => validate(child, schema.items!, `${path}[${i}]`));
  }
  if (schema.type === 'string') {
    if (typeof value !== 'string') fail('require string');
    const str = value as string;
    if (str.length < (schema.minLength ?? 0) || str.length > (schema.maxLength ?? Infinity) || (schema.pattern && !new RegExp(schema.pattern).test(str))) fail('invalid string');
  }
  if (schema.type === 'integer' || schema.type === 'number') {
    if (typeof value !== 'number' || !Number.isFinite(value) || (schema.type === 'integer' && !Number.isSafeInteger(value))) fail('require finite number/integer');
    const n = value as number;
    if (n < (schema.minimum ?? -Infinity) || n > (schema.maximum ?? Infinity)) fail('numeric limit');
  }
}

// JSON.parse alone silently overwrites duplicate members. Tokenize first, with
// bounded recursion, then let the native parser enforce JSON grammar.
export function parseJson(text: string): unknown {
  const tokens = text.match(/"(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\]:,]|\S/g) ?? [];
  let i = 0;
  function walk(depth: number): void {
    if (depth > 32) throw new Error('JSON nesting exceeds 32');
    const token = tokens[i++];
    if (token === '{') {
      const keys = new Set<string>();
      if (tokens[i] === '}') { i++; return; }
      while (i < tokens.length) {
        const key = JSON.parse(tokens[i++]!);
        if (typeof key !== 'string' || keys.has(key)) throw new Error('Duplicate or invalid JSON key');
        keys.add(key);
        if (tokens[i++] !== ':') throw new Error('Malformed JSON object');
        walk(depth + 1);
        if (tokens[i] === '}') { i++; return; }
        if (tokens[i++] !== ',') throw new Error('Malformed JSON object');
      }
      throw new Error('Unclosed JSON object');
    }
    if (token === '[') {
      if (tokens[i] === ']') { i++; return; }
      while (i < tokens.length) {
        walk(depth + 1);
        if (tokens[i] === ']') { i++; return; }
        if (tokens[i++] !== ',') throw new Error('Malformed JSON array');
      }
      throw new Error('Unclosed JSON array');
    }
    // The lexer splits keywords into characters; native JSON.parse below validates
    // them. Advance to the next structural delimiter for primitive literals.
    if (token && /^[tfn]$/.test(token)) while (i < tokens.length && /^[a-z]$/.test(tokens[i]!)) i++;
  }
  walk(0);
  if (i !== tokens.length) throw new Error('Malformed JSON');
  const value: unknown = JSON.parse(text);
  function finite(v: unknown): void {
    if (typeof v === 'number' && !Number.isFinite(v)) throw new Error('Nonfinite JSON number');
    if (v && typeof v === 'object') Object.values(v).forEach(finite);
  }
  finite(value);
  return value;
}
