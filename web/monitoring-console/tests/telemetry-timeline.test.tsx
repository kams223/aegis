import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it } from 'vitest';
import { OfflineTelemetry } from '../src/flight/OfflineTelemetry';
import { canonicalTelemetry, loadTelemetryReplay, replayTelemetry } from '../src/flight/telemetry';
import px4 from '../examples/telemetry/px4.json?raw';
import conflict from '../examples/telemetry/conflict.json?raw';
import unsupported from '../examples/telemetry/unsupported.json?raw';

afterEach(cleanup);
function encoded(text = px4) { return canonicalTelemetry(replayTelemetry(loadTelemetryReplay(text))); }
function upload(text: string, read?: () => Promise<ArrayBuffer>) {
  const bytes = new TextEncoder().encode(text), file = new File([bytes], 'snapshot.json');
  Object.defineProperty(file, 'arrayBuffer', { value: read ?? (async () => bytes.buffer) });
  fireEvent.change(screen.getByLabelText('Import recorded SITL snapshot'), { target: { files: [file] } });
}
async function loaded(text = encoded()) { render(<OfflineTelemetry />); upload(text); await screen.findByLabelText('Record frontier'); }
function frontier(value: number) { fireEvent.change(screen.getByLabelText('Record frontier'), { target: { value: String(value) } }); }
function evaluation(value: string) { fireEvent.change(screen.getByLabelText('Evaluation timestamp (ms)'), { target: { value } }); }
function details() { return within(screen.getByRole('region', { name: 'Recorded SITL vehicle details' })); }

it('starts at full frontier and navigates original occurrences through zero', async () => {
  await loaded(); expect(screen.getByText('Record 5 of 5')).toBeVisible(); expect(screen.getByRole('button', { name: 'Next record' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Previous record' })); expect(screen.getByText('Selected record: fictional-4')).toBeVisible();
  frontier(0); expect(screen.getByText(/Record 0 of 5 — Before first/)).toBeVisible();
  expect(screen.queryByRole('region', { name: 'Selected timeline record' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Previous record' })).toBeDisabled();
  expect(details().getAllByText('MISSING')).toHaveLength(5); expect(details().getByText('Missing')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Next record' })); expect(screen.getByText('Selected record: fictional-1')).toBeVisible();
  fireEvent.click(screen.getByText('Inspect selected record')); expect(within(screen.getByRole('region', { name: 'Selected timeline record' })).getByText('0')).toBeVisible();
});

it('edits evaluation losslessly and shows exact freshness transitions', async () => {
  await loaded(); evaluation('1900'); expect(details().getAllByText('Fresh')).toHaveLength(5);
  evaluation('1901'); expect(details().getAllByText('Stale · Last reported')).toHaveLength(5);
  evaluation('18446744073709551615'); expect(screen.getByLabelText('Evaluation timestamp (ms)')).toHaveValue('18446744073709551615');
  expect(details().getAllByText('18446744073709550715 ms old at evaluation')).toHaveLength(5);
});

it.each(['', '-1', '01', '1.5', '1e3', '18446744073709551616'])('rejects invalid evaluation %s and hides previous projected data', async value => {
  await loaded(); evaluation(value); expect(screen.getByRole('alert')).toHaveTextContent('unsigned decimal integer');
  expect(screen.getByLabelText('Evaluation timestamp (ms)')).toHaveAttribute('aria-invalid', 'true');
  expect(screen.getByLabelText('Recorded source/session')).toBeVisible(); expect(screen.queryByRole('region', { name: 'Recorded SITL vehicle details' })).toBeNull(); expect(screen.queryByRole('region', { name: 'Selected timeline record' })).toBeNull();
  evaluation('1000'); expect(screen.queryByRole('alert')).toBeNull(); expect(screen.getByLabelText('Recorded source/session')).toBeVisible();
});

it('explains a selected rejection without claiming a field update', async () => {
  await loaded(encoded(conflict));
  fireEvent.click(screen.getByText('Inspect selected record'));
  const record = within(screen.getByRole('region', { name: 'Selected timeline record' }));
  expect(record.getByText('REJECTED')).toBeVisible(); expect(record.getAllByText('IDENTITY_CONFLICT').length).toBeGreaterThan(0);
  expect(record.getByText(/did not update telemetry values/)).toBeVisible(); expect(record.getByText('Provenance kind')).toBeVisible();
  fireEvent.click(screen.getByText('altitude evidence details')); expect(details().getByText('fictional-1')).toBeVisible();
});

it('keeps future receipt rejection distinct from missing values', async () => {
  await loaded(); frontier(1); evaluation('899');
  expect(screen.getByRole('region', { name: 'Selected timeline record' })).toHaveTextContent('RECEIPT_AFTER_EVALUATION');
  expect(details().getByText('INVALID')).toBeVisible(); expect(details().getAllByText('MISSING')).toHaveLength(4); expect(details().getByText('Missing')).toBeVisible();
});

it('shows unsupported reception without replacing the last accepted declaration', async () => {
  const replay = loadTelemetryReplay(px4), record = replay.records[0]!;
  const s = replayTelemetry({ ...replay, records: [
    { ...record, record_id: 'open', field: 'reception', value: { status: 'open', note: 'supplied declaration' } },
    { ...record, record_id: 'unsupported', field: 'reception', value: { status: 'unrecognized', note: 'unsupported declaration' } },
  ] });
  await loaded(canonicalTelemetry(s));
  expect(details().getByText(/Recorded reception: unsupported/)).toHaveTextContent('Last reported: open');
  expect(screen.getByRole('region', { name: 'Selected timeline record' })).toHaveTextContent('UNSUPPORTED_RECEPTION_DECLARATION');
});

it('preserves component identity and separate projected vehicle state', async () => {
  const replay = loadTelemetryReplay(px4), source = replay.sources[0]!, record = replay.records[0]!;
  const s = replayTelemetry({ ...replay, sources: [source, { ...source, component_id: 2 }], records: [record, { ...record, component_id: 2, record_id: 'component-two' }] });
  await loaded(canonicalTelemetry(s));
  const selector = screen.getByLabelText('Recorded source/session');
  expect(within(selector).getAllByRole('option')).toHaveLength(2);
  fireEvent.change(selector, { target: { value: s.vehicles[1]!.identity_key } }); fireEvent.click(screen.getByText('altitude evidence details')); expect(details().getByText('component-two')).toBeVisible();
  frontier(1); expect(details().getAllByText('MISSING')).toHaveLength(5); expect(details().getByText('Missing')).toBeVisible();
  fireEvent.click(screen.getByText('Inspect selected record')); expect(screen.getByRole('region', { name: 'Selected timeline record' })).toHaveTextContent('1/1');
});

it('provides keyboard operable native frontier and evaluation controls', async () => {
  await loaded(); const user = userEvent.setup();
  const select = screen.getByLabelText('Record frontier'); select.focus(); expect(select).toHaveFocus();
  await user.selectOptions(select, '0'); await user.tab(); expect(screen.getByRole('button', { name: 'Next record' })).toHaveFocus();
  await user.keyboard('{Enter}'); expect(select).toHaveValue('1');
  const input = screen.getByLabelText('Evaluation timestamp (ms)'); input.focus(); await user.clear(input); await user.type(input, '1901');
  expect(input).toHaveValue('1901'); expect(details().getByText('Stale · Last reported')).toBeVisible();
});

it('clears and resets selection and evaluation on reimport', async () => {
  await loaded(); frontier(0); evaluation('2000'); upload(encoded());
  expect(await screen.findByLabelText('Record frontier')).toHaveValue('5'); expect(screen.getByLabelText('Evaluation timestamp (ms)')).toHaveValue('1000');
  fireEvent.click(screen.getByRole('button', { name: 'Clear recorded snapshot' })); expect(screen.queryByLabelText('Record frontier')).toBeNull();
  upload(encoded()); expect(await screen.findByLabelText('Record frontier')).toHaveValue('5');
});

it('removes timeline data immediately for invalid replacements', async () => {
  await loaded(); upload(unsupported); expect(screen.queryByLabelText('Record frontier')).toBeNull();
  expect(await screen.findByRole('alert')).toBeVisible(); expect(screen.queryByLabelText('Recorded source/session')).toBeNull();
});

it('ignores late imports after replacement, clear and unmount', async () => {
  let resolve!: (bytes: ArrayBuffer) => void;
  const pending = () => new Promise<ArrayBuffer>(done => { resolve = done; });
  const bytes = new TextEncoder().encode(encoded()).buffer;
  const view = render(<OfflineTelemetry />); upload('', pending); upload('{'); await screen.findByRole('alert');
  await act(async () => resolve(bytes)); expect(screen.queryByLabelText('Record frontier')).toBeNull();
  upload('', pending); fireEvent.click(screen.getByRole('button', { name: 'Clear recorded snapshot' }));
  await act(async () => resolve(bytes)); expect(screen.queryByLabelText('Record frontier')).toBeNull();
  upload('', pending); view.unmount(); await act(async () => resolve(bytes)); expect(screen.queryByLabelText('Record frontier')).toBeNull();
});

it('synchronizes the native record scrubber, exact selector and previous/next boundaries', async () => {
  await loaded();
  const scrubber = screen.getByRole('slider', { name: 'Record frontier, not time' });
  expect(scrubber).toHaveAttribute('min', '0'); expect(scrubber).toHaveAttribute('max', '5'); expect(scrubber).toHaveValue('5');
  fireEvent.change(scrubber, { target: { value: '0' } });
  expect(screen.getByLabelText('Record frontier')).toHaveValue('0'); expect(scrubber).toHaveAttribute('aria-valuetext', 'Before first record, 0 of 5');
  fireEvent.click(screen.getByRole('button', { name: 'Next record' })); expect(scrubber).toHaveValue('1');
  frontier(4); expect(scrubber).toHaveValue('4');
  fireEvent.click(screen.getByRole('button', { name: 'Next record' })); expect(scrubber).toHaveValue('5');
  expect(screen.getByRole('button', { name: 'Next record' })).toBeDisabled();
  scrubber.focus(); expect(scrubber).toHaveFocus();
});

it('keeps record metadata collapsed while exposing status, zeros and compact cards', async () => {
  await loaded();
  const summary = screen.getByText('Inspect selected record'), disclosure = summary.closest('details')!;
  expect(disclosure).not.toHaveAttribute('open'); expect(screen.getByText('Selected record: fictional-5')).toBeVisible();
  expect(screen.getByText('ACCEPTED')).toBeVisible();
  const cards = screen.getByRole('region', { name: 'Recorded SITL vehicle details' });
  expect(cards.querySelector('pre')).toBeNull();
  expect(within(cards).getByText('0 m · home relative')).toBeVisible(); expect(within(cards).getByText('0 m/s')).toBeVisible(); expect(within(cards).getByText('0 %')).toBeVisible();
  const user = userEvent.setup(); summary.focus(); expect(summary).toHaveFocus();
  // jsdom does not emulate Enter's native <summary> activation; exercise
  // disclosure activation by click and leave native keyboard behavior intact.
  await user.click(summary);
  expect(disclosure).toHaveAttribute('open'); expect(screen.getByText('Original record index (zero-based)')).toBeVisible();
  await user.click(summary); expect(disclosure).not.toHaveAttribute('open');
});

it('disables navigation for an empty snapshot and keeps validation domains separate', async () => {
  const r = loadTelemetryReplay(px4);
  await loaded(canonicalTelemetry(replayTelemetry({ ...r, records: [] })));
  expect(screen.getByRole('slider')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Previous record' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Next record' })).toBeDisabled();
  expect(screen.getByText(/Imported snapshot validation:/)).toBeVisible(); expect(screen.getByText(/Prefix validation:/)).toBeVisible();
});

function card(field: string) {
  return details().getByRole('heading', { name: field }).closest('article')!;
}
function evidenceValue(article: HTMLElement, label: string) {
  return within(article).getByText(label, { selector: 'dt' }).nextElementSibling;
}

it('uses reception timeout at age 100 ms independently of a fresh altitude field', async () => {
  const r = loadTelemetryReplay(px4), first = r.records[0]!;
  const s = replayTelemetry({ ...r, policy: { ...r.policy, reception_timeout_ms: 50 }, records: [first,
    { ...first, record_id: 'reception', field: 'reception', value: { status: 'receiving', note: 'Fictional reception' } },
  ] });
  await loaded(canonicalTelemetry(s));
  const reception = card('reception'), altitude = card('altitude');
  expect(s.vehicles[0]!.fields.reception.age_ms).toBe('100');
  expect(s.vehicles[0]!.fields.reception.state).toBe('available');
  expect(s.vehicles[0]!.reception_state).toBe('stale');
  expect(within(reception).getByText('Stale — Last reported')).toBeVisible();
  expect(within(reception).getByText('receiving', { selector: 'strong' })).toBeVisible();
  expect(reception).toHaveAttribute('data-freshness', 'stale');
  expect(within(altitude).getByText('Fresh')).toBeVisible();
  evaluation('950'); expect(within(card('reception')).getByText('Fresh')).toBeVisible();
  evaluation('951'); expect(within(card('reception')).getByText('Stale — Last reported')).toBeVisible();
});

it('labels unsupported reception using the authoritative projection', async () => {
  const r = loadTelemetryReplay(px4), first = r.records[0]!;
  await loaded(canonicalTelemetry(replayTelemetry({ ...r, records: [
    { ...first, record_id: 'reception', field: 'reception', value: { status: 'unsupported-declaration', note: 'Fictional unsupported input' } },
  ] })));
  expect(within(card('reception')).getByText('Unsupported')).toBeVisible();
  expect(card('reception')).toHaveAttribute('data-freshness', 'unsupported');
});

it('restores all supplied payload metadata in collapsed named evidence fields', async () => {
  const r = loadTelemetryReplay(px4), first = r.records[0]!;
  await loaded(canonicalTelemetry(replayTelemetry({ ...r, records: [...r.records,
    { ...first, record_id: 'reception', field: 'reception', value: { status: 'open', note: '<script>fictional reception note</script>' } },
  ] })));
  for (const field of ['altitude', 'ground speed', 'battery', 'flight mode', 'link status', 'reception']) {
    const article = card(field), summary = within(article).getByText(`${field} evidence details`);
    expect(summary.closest('details')).not.toHaveAttribute('open'); fireEvent.click(summary);
  }
  expect(evidenceValue(card('altitude'), 'Altitude reference ID')).toHaveTextContent('fictional-home-a');
  expect(evidenceValue(card('altitude'), 'Altitude reference')).toHaveTextContent('home_relative');
  expect(evidenceValue(card('altitude'), 'Altitude unit')).toHaveTextContent('m');
  expect(evidenceValue(card('altitude'), 'Altitude value')).toHaveTextContent(/^0$/);
  expect(evidenceValue(card('battery'), 'Battery ID')).toHaveTextContent('fictional-battery');
  expect(evidenceValue(card('battery'), 'Battery percentage')).toHaveTextContent(/^0$/);
  expect(evidenceValue(card('battery'), 'Battery unit')).toHaveTextContent('%');
  expect(evidenceValue(card('ground speed'), 'Ground speed value')).toHaveTextContent(/^0$/);
  expect(evidenceValue(card('ground speed'), 'Ground speed unit')).toHaveTextContent('m/s');
  expect(evidenceValue(card('flight mode'), 'Base mode')).toHaveTextContent(/^0$/);
  expect(evidenceValue(card('flight mode'), 'Custom mode')).toHaveTextContent(/^0$/);
  expect(evidenceValue(card('link status'), 'Status note')).toHaveTextContent('No link health measurement or readiness inference.');
  expect(evidenceValue(card('reception'), 'Status note')).toHaveTextContent('<script>fictional reception note</script>');
  expect(evidenceValue(card('reception'), 'Declared status')).toHaveTextContent('open');
  expect(card('reception').querySelector('script,pre')).toBeNull();
  expect(evidenceValue(card('altitude'), 'Provenance')).toHaveTextContent('fictional_normalized');
  expect(evidenceValue(card('altitude'), 'Receipt timestamp')).toHaveTextContent('900 ms · replay:receipt');
});

it('shows absent optional timestamps and absent payloads without invented field metadata', async () => {
  const r = loadTelemetryReplay(px4), first = r.records[0]!;
  await loaded(canonicalTelemetry(replayTelemetry({ ...r, records: [{ ...first, source_timestamp: null }] })));
  fireEvent.click(screen.getByText('altitude evidence details')); fireEvent.click(screen.getByText('battery evidence details'));
  expect(evidenceValue(card('altitude'), 'Source timestamp')).toHaveTextContent('Not supplied');
  expect(evidenceValue(card('altitude'), 'Altitude value')).toHaveTextContent(/^0$/);
  expect(evidenceValue(card('battery'), 'Field payload')).toHaveTextContent('Not supplied');
  expect(within(card('battery')).queryByText('Battery ID')).toBeNull();
});

it('does not fabricate a reference ID for an explicitly absent altitude reference', async () => {
  const r = loadTelemetryReplay(px4), first = r.records[0]!;
  await loaded(canonicalTelemetry(replayTelemetry({ ...r, records: [{ ...first,
    value: { value: 0, unit: 'm', reference: 'home_relative', reference_id: null },
  }] })));
  expect(screen.getByRole('region', { name: 'Selected timeline record' })).toHaveTextContent('ALTITUDE_REFERENCE_UNAVAILABLE');
  fireEvent.click(screen.getByText('altitude evidence details'));
  expect(evidenceValue(card('altitude'), 'Field payload')).toHaveTextContent('Not supplied');
  expect(within(card('altitude')).queryByText('Altitude reference ID')).toBeNull();
});

it('keeps invalid empty required metadata rejected rather than defaulting it', () => {
  const r = loadTelemetryReplay(px4), first = r.records[0]!;
  for (const value of [
    { value: 0, unit: 'm', reference: 'home_relative', reference_id: '' },
    { battery_id: '', percentage: 0, unit: '%' },
    { status: 'open', note: '' },
  ]) {
    const field = 'battery_id' in value ? 'battery' : 'note' in value ? 'reception' : 'altitude';
    expect(() => loadTelemetryReplay(JSON.stringify({ ...r, records: [{ ...first, field, value }] }))).toThrow();
  }
});
