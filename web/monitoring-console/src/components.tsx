import type { ReactNode } from 'react';
import type { Timestamp } from './models';

export const label = (value: string) => value.replaceAll('_', ' ');
export function Badge({ value }: { value: string }) {
  const tone = ['rejected', 'failed', 'mismatch', 'degraded', 'unavailable'].includes(value) ? 'warning' : ['applied', 'completed', 'reviewed', 'verified', 'available'].includes(value) ? 'good' : 'neutral';
  return <span className={`badge ${tone}`}><span aria-hidden="true" className="status-dot" />{label(value)}</span>;
}
export function Time({ value }: { value: Timestamp }) { return <span className="timestamp"><code>{value.value} {value.unit}</code><span>{value.clock_domain}</span></span>; }
export function Empty({ children }: { children: ReactNode }) { return <p className="empty">{children}</p>; }
export function Card({ title, children, className = '' }: { title: string; children: ReactNode; className?: string }) { return <section className={`card ${className}`}><h2>{title}</h2>{children}</section>; }
export function Metric({ title, value, detail }: { title: string; value: number; detail: string }) { return <article className="metric"><span>{title}</span><strong>{value.toString().padStart(2, '0')}</strong><small>{detail}</small></article>; }
