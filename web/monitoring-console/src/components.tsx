import type { ReactNode } from 'react';
import type { Timestamp } from './models';

export const label = (value: string) => value.replaceAll('_', ' ');
export type StatusTone = 'neutral' | 'good' | 'warning' | 'critical';

export function Badge({ value }: { value: string }) {
  const tone: StatusTone = ['failed', 'mismatch'].includes(value) ? 'critical' : ['rejected', 'degraded', 'unavailable', 'completed_with_rejections'].includes(value) ? 'warning' : ['applied', 'completed', 'reviewed', 'verified', 'available'].includes(value) ? 'good' : 'neutral';
  return <span className={`badge ${tone}`} data-tone={tone}><span aria-hidden="true" className="status-dot" />{label(value)}</span>;
}
export function Time({ value }: { value: Timestamp }) { return <span className="timestamp"><code>{value.value} {value.unit}</code><span>{value.clock_domain}</span></span>; }
export function Empty({ children }: { children: ReactNode }) { return <p className="empty">{children}</p>; }
export function Card({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) { return <section className={`card ${className}`}><h2>{title}</h2>{children}</section>; }
export function MetricGroup({ children }: { children: ReactNode }) { return <div className="metrics" aria-label="Session metrics">{children}</div>; }
export function Metric({ title, value, detail, tone = 'neutral' }: { title: string; value: number; detail: string; tone?: StatusTone }) { return <article className="metric" aria-label={title} data-tone={tone}><span>{title}</span><strong>{value.toString().padStart(2, '0')}</strong><small>{detail}</small></article>; }
