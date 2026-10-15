import { canonicalTelemetry, loadTelemetrySnapshot, replayTelemetry, TelemetryError } from './telemetry';
import type { Diagnostic, RecordEntry, Stamp, TelemetrySnapshot } from './telemetry';

export type TimelineSelection = Readonly<{
  record_index: number;
  record: RecordEntry;
}> & (Readonly<{ status: 'accepted'; diagnostic: null }> | Readonly<{ status: 'rejected'; diagnostic: Diagnostic }>);

export interface TelemetryTimeline {
  readonly frontier: number;
  readonly record_count: number;
  readonly selected: TimelineSelection | null;
  readonly snapshot: TelemetrySnapshot;
}

/** Replay exactly the first `frontier` supplied records (zero means before-first).
 * The last included occurrence is selected; its index is the original array index.
 * Revalidate the COMPLETE imported snapshot before slicing, including unvisited
 * records and derived fields. Neither caller-owned inputs nor the original
 * evaluation time are changed. The returned graph is owned and deeply frozen.
 *
 * Evaluation uses the original receipt clock and millisecond uint64 contract.
 * Future receipts are rejected by the existing engine, never hidden or sorted.
 * Acceptance/diagnostics apply only to this prefix at this evaluation time and
 * may differ from the original snapshot. Backward selection recomputes from zero.
 * No wall clock, implicit alignment, mutable cursor or alternate replay policy.
 */
export function projectTelemetryTimeline(
  input: TelemetrySnapshot, frontier: number, evaluationTimestamp: Stamp,
): TelemetryTimeline {
  const original = loadTelemetrySnapshot(canonicalTelemetry(input));
  if (!Number.isSafeInteger(frontier) || frontier < 0 || frontier > original.replay.records.length) {
    throw new TelemetryError('Timeline frontier must be an integer from zero through record count');
  }
  // Even empty source inventories must retain the original receipt-time domain.
  if (evaluationTimestamp?.clock_domain !== original.replay.evaluation_timestamp.clock_domain) {
    throw new TelemetryError('Timeline evaluation must retain the original receipt clock domain');
  }
  const snapshot = replayTelemetry({
    ...original.replay,
    records: original.replay.records.slice(0, frontier),
    evaluation_timestamp: evaluationTimestamp,
  });
  const record = snapshot.replay.records[frontier - 1];
  const diagnostic = snapshot.diagnostics.find(d => d.record_index === frontier - 1);
  const selected: TimelineSelection | null = record === undefined ? null : diagnostic
    ? Object.freeze({ record_index: frontier - 1, record, status: 'rejected', diagnostic })
    : Object.freeze({ record_index: frontier - 1, record, status: 'accepted', diagnostic: null });
  return Object.freeze({ frontier, record_count: original.replay.records.length, selected, snapshot });
}
