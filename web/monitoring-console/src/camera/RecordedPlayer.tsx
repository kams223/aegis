import { useEffect, useRef, useState } from 'react';
import { mediaTime, resolveApprovedRecording } from './catalog';

export function RecordedPlayer({ recordingId = null }: { recordingId?: string | null }) {
  const recording = resolveApprovedRecording(recordingId);
  // Remount when the approved selection changes: old playback/error state cannot
  // leak into the new resource. No raw path or URL prop is accepted.
  return recording ? <LoadedPlayer key={recording.id} recordingId={recording.id} /> : <UnavailablePlayer />;
}

function UnavailablePlayer() {
  const viewport = useRef<HTMLDivElement>(null);
  const [message, setMessage] = useState('');
  async function fullscreen() {
    try {
      if (!viewport.current?.requestFullscreen) { setMessage('Fullscreen unavailable in this browser.'); return; }
      await viewport.current.requestFullscreen();
    } catch { setMessage('Fullscreen unavailable or permission denied.'); }
  }
  return <><div ref={viewport} className="camera-viewport"><div className="camera-overlay"><span>APPROVED MEDIA CATALOG</span><span>PLACEHOLDER</span></div><div className="camera-empty"><svg width="48" height="36" viewBox="0 0 48 36" aria-hidden="true"><path d="M3 7h28v22H3Z M31 14l13-7v22l-13-7 M8 32 39 2" /></svg><strong>NO VERIFIED CAMERA FEED</strong><small>No playable recording supplied</small></div><span className="viewport-caption">NO MEDIA LOADED · NO LIVE ACQUISITION</span></div><div className="viewport-toolbar"><button onClick={() => { void fullscreen(); }}>Fullscreen placeholder</button></div>{message && <p role="status">{message}</p>}</>;
}

function LoadedPlayer({ recordingId }: { recordingId: string }) {
  const recording = resolveApprovedRecording(recordingId)!;
  const video = useRef<HTMLVideoElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState('1');
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(true);
  const [message, setMessage] = useState('');
  useEffect(() => {
    const element = video.current;
    return () => { element?.pause(); element?.removeAttribute('src'); element?.load(); };
  }, []);
  function sync() {
    if (!video.current) return;
    setTime(Number.isFinite(video.current.currentTime) ? Math.max(0, video.current.currentTime) : 0);
    setDuration(Number.isFinite(video.current.duration) ? Math.max(0, video.current.duration) : 0);
    setPlaying(!video.current.paused && !video.current.ended);
    setVolume(video.current.volume); setMuted(video.current.muted);
  }
  async function toggle() {
    if (!video.current) return;
    if (!video.current.paused) video.current.pause();
    else try { await video.current.play(); setMessage(''); } catch { setMessage('Playback unavailable or permission denied.'); }
  }
  async function fullscreen() {
    try {
      if (!viewport.current?.requestFullscreen) { setMessage('Fullscreen unavailable in this browser.'); return; }
      await viewport.current.requestFullscreen();
    } catch { setMessage('Fullscreen unavailable or permission denied.'); }
  }
  return <div className="recorded-player"><div ref={viewport} className="camera-viewport playable"><video ref={video} src={recording.src} aria-label={recording.title} preload="metadata" playsInline muted={muted}
    onLoadedMetadata={sync} onCanPlay={() => { setState('ready'); sync(); }} onWaiting={() => setState('loading')} onPlaying={() => { setState('ready'); sync(); }} onTimeUpdate={sync} onDurationChange={sync} onPlay={sync} onPause={sync} onEnded={sync} onVolumeChange={sync}
    onError={() => { setState('error'); setPlaying(false); video.current?.pause(); }} />
    <div className="camera-overlay"><span>{recording.title}</span><span>RECORDED DEMO · NOT LIVE</span></div>
    {state !== 'ready' && <p className="media-state" role="status">{state === 'error' ? 'Recording unavailable — media error' : 'Loading approved recording…'}</p>}
  </div><p className="note">Recording playback: {state === 'error' ? 'Unavailable' : state === 'loading' ? 'Loading' : playing ? 'Playing recorded demo' : 'Paused recorded demo'}</p><div className="viewport-toolbar"><button disabled={state !== 'ready' && !playing} onClick={() => { void toggle(); }}>{playing ? 'Pause recording' : 'Play recording'}</button><button onClick={() => { void fullscreen(); }}>Fullscreen recording</button><span className="playback-time">{mediaTime(time)} / {duration ? mediaTime(duration) : 'Unavailable'}</span></div>
    <label>Recording timeline<input type="range" min="0" max={duration || 1} step="0.1" value={Math.min(time, duration)} disabled={!duration || state === 'error'} onChange={e => { if (video.current) { video.current.currentTime = Math.min(duration, Math.max(0, Number(e.target.value))); sync(); } }} /></label>
    <div className="player-settings"><label>Recording playback speed<select value={speed} onChange={e => { setSpeed(e.target.value); if (video.current) video.current.playbackRate = Number(e.target.value); }}><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option></select></label><label>Recording volume<input type="range" min="0" max="1" step="0.05" value={volume} onChange={e => { const value = Number(e.target.value); setVolume(value); if (video.current) video.current.volume = value; }} /></label><button aria-pressed={muted} onClick={() => { setMuted(!muted); if (video.current) video.current.muted = !muted; }}>{muted ? 'Unmute recording' : 'Mute recording'}</button></div>
    {message && <p role="status">{message}</p>}
  </div>;
}
