import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

// Fictional SVG display units only; never joined to validated fixture observations.
const DEMO_MARKERS = Object.freeze([
  Object.freeze({ id: 'demo-marker-01', x: 106, y: 96, description: 'Illustrative observation Alpha', review: 'Not reviewed', provenance: 'SYNTHETIC DEMO', timestamp: '0 s · demo-only clock' }),
  Object.freeze({ id: 'demo-marker-02', x: 224, y: 128, description: 'Illustrative observation Bravo', review: 'Interpretation under review', provenance: 'SYNTHETIC DEMO', timestamp: null }),
  Object.freeze({ id: 'demo-marker-03', x: 134, y: 237, description: 'Illustrative observation Charlie', review: 'Not reviewed', provenance: 'SYNTHETIC DEMO', timestamp: '4 s · demo-only clock' }),
  Object.freeze({ id: 'demo-marker-04', x: 226, y: 218, description: 'Illustrative observation Delta', review: 'Interpretation rejected', provenance: 'SYNTHETIC DEMO', timestamp: null }),
]);

export function RadarDisplay({ children }: { children?: ReactNode }) {
  const [showDemo, setShowDemo] = useState(false);
  const [selectedDemo, setSelectedDemo] = useState<number | null>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const demo = selectedDemo === null ? null : DEMO_MARKERS[selectedDemo]!;
  useEffect(() => { if (selectedDemo !== null) detailHeading.current?.focus(); }, [selectedDemo]);
  const [density, setDensity] = useState(4);
  const [paused, setPaused] = useState(false);
  const [history, setHistory] = useState(true);
  const [reduced, setReduced] = useState(() => globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);
  const [fullscreen, setFullscreen] = useState(false);
  const [message, setMessage] = useState('');
  const frame = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const media = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)');
    const change = () => setReduced(media?.matches ?? false);
    media?.addEventListener('change', change);
    const sync = () => setFullscreen(document.fullscreenElement === frame.current);
    document.addEventListener('fullscreenchange', sync);
    return () => { media?.removeEventListener('change', change); document.removeEventListener('fullscreenchange', sync); };
  }, []);
  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === frame.current) { await document.exitFullscreen(); return; }
      if (!frame.current?.requestFullscreen) { setMessage('Radar fullscreen unavailable in this browser.'); return; }
      await frame.current.requestFullscreen(); setMessage('');
    } catch { setMessage('Radar fullscreen unavailable or permission denied.'); }
  }
  return <div ref={frame} className={`radar-frame${paused || reduced ? ' scan-paused' : ''}`}>
    <p className="boundary-label">SYNTHETIC DISPLAY — NON-GEOGRAPHIC</p>
    <div className="radar-controls"><label>Decorative ring density<select value={density} onChange={e => { const value = Number(e.target.value); if ([3, 4, 6, 8].includes(value)) setDensity(value); }}>{[3, 4, 6, 8].map(n => <option key={n} value={n}>{n} rings</option>)}</select></label><button disabled={reduced} aria-pressed={paused || reduced} onClick={() => setPaused(value => !value)}>{paused || reduced ? 'Resume decorative sweep' : 'Pause decorative sweep'}</button><button aria-pressed={history} onClick={() => setHistory(value => !value)}>Decorative scan history</button><button onClick={() => { void toggleFullscreen(); }}>{fullscreen ? 'Exit radar fullscreen' : 'Fullscreen radar'}</button></div>
    <button className="demo-marker-toggle" aria-pressed={showDemo} onClick={() => { setShowDemo(value => !value); setSelectedDemo(null); }}>SHOW SYNTHETIC DEMO MARKERS</button>
    {showDemo && <p className="demo-marker-warning">SYNTHETIC DEMONSTRATION — MARKER POSITIONS ARE NOT SENSOR MEASUREMENTS</p>}
    {message && <p role="status">{message}</p>}
    {reduced && <p className="note">Reduced motion: radar sweep is static.</p>}
    <p className="spatial-boundary">No spatial observation positions are supplied.</p>
    <div className="radar-scope"><svg width="420" height="420" viewBox="0 0 320 320" role={showDemo ? 'group' : undefined} aria-label={showDemo ? 'Fictional demonstration marker display' : undefined} aria-hidden={showDemo ? undefined : true}>
      <g aria-hidden="true">
      <g className="radar-grid">{Array.from({ length: density }, (_, i) => <circle key={i} cx="160" cy="160" r={144 * (i + 1) / density} />)}<path d="M16 160h288M160 16v288M58 58l204 204M58 262 262 58" />{Array.from({ length: 72 }, (_, i) => <path key={i} transform={`rotate(${i * 5} 160 160)`} d={i % 6 === 0 ? 'M160 9v10' : 'M160 9v4'} />)}</g>
      <g className="radar-sweep">{history && <g className="scan-history"><path d="M160 160V20A140 140 0 0 0 39 90Z" /><path d="M160 160 39 90A140 140 0 0 0 39 230Z" /></g>}<path d="M160 160V20A140 140 0 0 1 281 90Z" /><path className="sweep-edge" d="M160 160V20" /></g>
      <path className="radar-crosshair" d="M151 160h18M160 151v18" />
      <g className="radar-labels"><text x="160" y="35">000°</text><text x="280" y="155">090°</text><text x="160" y="293">180°</text><text x="40" y="155">270°</text></g>
      </g>
      {showDemo && <g className="demo-markers">{DEMO_MARKERS.map((marker, index) => <g key={marker.id} data-demo-id={marker.id} className={`demo-marker${selectedDemo === index ? ' selected' : ''}`} role="button" tabIndex={0} aria-label={`Inspect synthetic demo ${marker.id}: ${marker.description}`} aria-pressed={selectedDemo === index} onClick={() => setSelectedDemo(index)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedDemo(index); } }} transform={`translate(${marker.x} ${marker.y})`}><circle className="demo-marker-halo" r="12" /><circle className="demo-marker-dot" r="5" /><title>{marker.id} · SYNTHETIC DEMO</title></g>)}</g>}
    </svg><span className="scope-caption">{showDemo ? 'FICTIONAL SVG DISPLAY POSITIONS ONLY' : 'DECORATIVE SCAN · NO POSITION DATA'}</span></div>
    <div className="scope-legend"><span>Rings / azimuth: decorative</span><span>{showDemo ? 'Synthetic demo markers only · no sensor detections' : 'No observation markers'}</span><span>History is a visual effect, not sensor history</span></div>
    {demo && <section className="demo-observation-details" aria-label="Synthetic demo observation details">
      <h3 ref={detailHeading} tabIndex={-1}>{demo.id}</h3>
      <p className="demo-marker-warning">SYNTHETIC DEMO · Separate from validated observations</p>
      <dl><dt>Description</dt><dd>{demo.description}</dd><dt>Provenance</dt><dd>{demo.provenance}</dd><dt>Review status</dt><dd>{demo.review}</dd><dt>Demonstration timestamp</dt><dd>{demo.timestamp ?? 'Not supplied'}</dd><dt>Sensor-fusion status</dt><dd>NOT AVAILABLE</dd><dt>Classification</dt><dd>NOT ESTABLISHED</dd></dl>
      <p>Fictional display coordinates only. Not sensor measurements, geographic positions, range, bearing or altitude.</p>
      <div className="demo-detail-controls"><button disabled={selectedDemo === 0} onClick={() => setSelectedDemo(index => index === null ? null : Math.max(0, index - 1))}>Previous demo observation</button><button disabled={selectedDemo === DEMO_MARKERS.length - 1} onClick={() => setSelectedDemo(index => index === null ? null : Math.min(DEMO_MARKERS.length - 1, index + 1))}>Next demo observation</button><button onClick={() => { const id = demo.id; setSelectedDemo(null); frame.current?.querySelector<SVGGElement>(`[data-demo-id="${id}"]`)?.focus(); }}>Close demo details</button></div>
    </section>}
    {children}
  </div>;
}
