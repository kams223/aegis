export interface ApprovedRecording { readonly id: string; readonly title: string; readonly src: string }

// Only developer-reviewed bundled assets belong here. No recording is approved
// or bundled in this phase. Evidence local_path values are never consulted.
export const APPROVED_RECORDINGS: readonly ApprovedRecording[] = Object.freeze([]);

export function resolveApprovedRecording(id: unknown): ApprovedRecording | null {
  return recordingFromCatalog(id, APPROVED_RECORDINGS);
}

// Pure catalog validation, also usable by asset-generation checks. Runtime UI
// calls resolveApprovedRecording and cannot supply its own catalog.
export function recordingFromCatalog(id: unknown, catalog: readonly ApprovedRecording[]): ApprovedRecording | null {
  if (typeof id !== 'string') return null;
  const recording = catalog.find(recording => recording.id === id);
  if (!recording || !/^(?:\.\/|\/)(?:assets|src\/media)\/[A-Za-z0-9_./-]+\.(?:mp4|webm|ogv)$/.test(recording.src) || recording.src.split('/').includes('..')) return null;
  return recording;
}

export function mediaTime(value: number): string {
  if (!Number.isFinite(value) || value < 0) return 'Unavailable';
  const seconds = Math.floor(value);
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
}
