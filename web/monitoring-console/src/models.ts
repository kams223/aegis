export interface Version { schema_version: 1 }
export type ReviewStatus = 'unreviewed' | 'under_review' | 'reviewed' | 'dismissed';
export type Connection = 'offline' | 'recorded' | 'unknown';
export interface Timestamp extends Version { value: number; unit: 's' | 'ms' | 'us' | 'ns'; clock_domain: string }
export interface Capability extends Version { name: string; support: 'supported' | 'unsupported' | 'unknown' }
export interface Source extends Version { source_id: string; device_id: string; clock_domain: string; evidence_id: string }
export interface Device extends Version {
  device_id: string; category: 'aegis_native' | 'third_party' | 'simulated'; device_type: 'aerial' | 'ground' | 'other';
  adapter: Version & { adapter_id: string; version: string }; capabilities: Capability[]; connection_status: Connection;
  health: Version & { status: 'healthy' | 'degraded' | 'unavailable' | 'unknown'; timestamp: Timestamp; note: string }; sources: Source[];
}
export interface Evidence extends Version { evidence_id: string; source_id: string; kind: string; local_path: string; dataset_id: string | null }
export interface Observation extends Version { observation_id: string; source_id: string; timestamp: Timestamp; category: 'synthetic' | 'recorded_metadata'; quality: 'declared' | 'uncertain' | 'missing'; uncertainty_note: string | null; annotation: string; review_status: ReviewStatus; evidence_id: string }
export interface Sentinel extends Version { device_id: string; sentinel_category: 'aerial' | 'ground'; connectivity: Connection; sensors: (Version & { source_id: string; status: 'available' | 'unavailable' | 'unknown' })[]; battery_percent: number | null; maintenance_status: string; camera_evidence_id: string | null; review_status: ReviewStatus }
export interface Alert extends Version { alert_id: string; observation_id: string; status: ReviewStatus; explanation: Version & { code: string; explanation: string; evidence_ids: string[] } }
export interface Request extends Version { request_id: string; alert_id: string; action: 'inspect_dataset_report' | 'retrieve_evidence' | 'summarize_device_health' | 'explain_observation' | 'compare_validation_results'; reference_ids: string[] }
export interface Result extends Version { result_id: string; request_id: string; status: 'completed' | 'not_evaluated'; summary: string; evidence_ids: string[] }
export interface Review extends Version { decision_id: string; subject_kind: 'observation' | 'sentinel' | 'alert'; subject_id: string; reviewer_id: string; previous_status: ReviewStatus; new_status: ReviewStatus; timestamp: Timestamp; note: string }
export interface Audit extends Version { audit_id: string; actor_id: string; event: 'investigation_completed' | 'investigation_not_evaluated' | 'human_review'; reference_id: string; timestamp: Timestamp; note: string }
export interface Outcome extends Version { evidence_id: string; dataset_id: string; metadata_status: 'passed' | 'failed' | 'not_evaluated'; integrity_status: 'verified' | 'mismatch' | 'not_evaluated' }
export interface Snapshot extends Version { snapshot_id: string; description: string; registry: Version & { devices: Device[] }; evidence: Evidence[]; observations: Observation[]; sentinels: Sentinel[]; alerts: Alert[]; investigation_requests: Request[]; investigation_results: Result[]; review_history: Review[]; audit_entries: Audit[]; validation_results: Outcome[] }
export interface Diagnostic extends Version { event_id: string; event_index: number; device_id: string; source_id: string | null; code: string; severity: 'Rejected'; explanation: string }
export interface EventResult extends Version { event_id: string; event_index: number; event_type: string; device_id: string; source_id: string | null; timestamp: Timestamp; status: 'applied' | 'rejected'; diagnostics: Diagnostic[] }
export interface Session extends Version { initial_snapshot_id: string; event_results: EventResult[]; final_snapshot: Snapshot; summary: Version & { event_count: number; applied_count: number; rejected_count: number; status: 'completed' | 'completed_with_rejections' } }
