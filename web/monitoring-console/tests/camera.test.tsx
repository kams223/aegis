import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RecordedPlayer } from '../src/camera/RecordedPlayer';
import { mediaTime, recordingFromCatalog } from '../src/camera/catalog';

vi.mock('../src/camera/catalog', async importOriginal => {
  const original = await importOriginal<typeof import('../src/camera/catalog')>();
  const recordings = Object.freeze([{ id: 'TEST-APPROVED', title: 'Test-only approved recording', src: '/assets/test-approved.webm' }]);
  return { ...original, resolveApprovedRecording: (id: unknown) => original.recordingFromCatalog(id, recordings) };
});

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLMediaElement) {
    Object.defineProperty(this, 'paused', { value: false, configurable: true }); this.dispatchEvent(new Event('play')); return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (this: HTMLMediaElement) {
    Object.defineProperty(this, 'paused', { value: true, configurable: true }); this.dispatchEvent(new Event('pause'));
  });
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function ready() {
  const video = screen.getByLabelText('Test-only approved recording') as HTMLVideoElement;
  Object.defineProperty(video, 'duration', { value: 12, configurable: true });
  fireEvent.loadedMetadata(video); fireEvent.canPlay(video); return video;
}

it('production catalog is empty and rejects all path-like IDs without media elements', async () => {
  const actual = await vi.importActual<typeof import('../src/camera/catalog')>('../src/camera/catalog');
  expect(actual.APPROVED_RECORDINGS).toHaveLength(0);
  for (const id of ['TEST-APPROVED', '/assets/a.webm', 'https://example.com/video.mp4', '../video.mp4', null]) expect(actual.resolveApprovedRecording(id)).toBeNull();
  const { container } = render(<RecordedPlayer />);
  expect(screen.getByText('NO VERIFIED CAMERA FEED')).toBeVisible();
  expect(container.querySelector('video, source')).toBeNull();
});

it('allows only a declared local bundled resource and rejects invalid catalog URLs', () => {
  const valid = { id: 'approved', title: 'Test fixture only', src: './assets/fixture.webm' };
  expect(recordingFromCatalog('approved', [valid])).toEqual(valid);
  expect(recordingFromCatalog('unlisted', [valid])).toBeNull();
  for (const src of ['https://example.com/a.mp4', '//example.com/a.webm', 'data:video/webm,x', 'blob:example', '/assets/../a.mp4', '/etc/a.mp4', '/assets/a.mp4?x', './assets/a%2f.mp4', '/assets/a.mp4#x']) expect(recordingFromCatalog('approved', [{ ...valid, src }])).toBeNull();
});

it('unknown media never gets a source even if it resembles a fixture reference', () => {
  const { container } = render(<RecordedPlayer recordingId="examples/recorded_datasets/placeholder.txt" />);
  expect(container.querySelector('video')).toBeNull();
});

it('loads only the allowlisted source with no autoplay or live acquisition', () => {
  const { container } = render(<RecordedPlayer recordingId="TEST-APPROVED" />);
  const video = container.querySelector('video')!;
  expect(video).toHaveAttribute('src', '/assets/test-approved.webm');
  expect(video).not.toHaveAttribute('autoplay'); expect(video).toHaveAttribute('preload', 'metadata');
  expect(screen.getByRole('button', { name: 'Play recording' })).toBeDisabled();
  expect(screen.getByText('Loading approved recording…')).toBeVisible();
});

it('plays, pauses and shows native playback time and duration', async () => {
  render(<RecordedPlayer recordingId="TEST-APPROVED" />); const video = ready();
  fireEvent.click(screen.getByRole('button', { name: 'Play recording' }));
  expect(await screen.findByRole('button', { name: 'Pause recording' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Pause recording' }));
  expect(video.paused).toBe(true);
  video.currentTime = 3.5; fireEvent.timeUpdate(video);
  expect(screen.getByText('00:03 / 00:12')).toBeVisible();
});

it('seeks, selects speed and adjusts mute/volume through labeled controls', () => {
  render(<RecordedPlayer recordingId="TEST-APPROVED" />); const video = ready();
  fireEvent.change(screen.getByLabelText('Recording timeline'), { target: { value: '6' } }); expect(video.currentTime).toBe(6);
  fireEvent.change(screen.getByLabelText('Recording playback speed'), { target: { value: '2' } }); expect(video.playbackRate).toBe(2);
  fireEvent.change(screen.getByLabelText('Recording volume'), { target: { value: '.25' } }); expect(video.volume).toBe(.25);
  fireEvent.click(screen.getByRole('button', { name: 'Unmute recording' })); expect(video.muted).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Mute recording' })); expect(video.muted).toBe(true);
});

it('exposes loading, media errors, blocked play and unavailable duration honestly', async () => {
  render(<RecordedPlayer recordingId="TEST-APPROVED" />); const video = ready();
  vi.mocked(video.play).mockRejectedValueOnce(new Error('blocked'));
  fireEvent.click(screen.getByRole('button', { name: 'Play recording' }));
  expect(await screen.findByText('Playback unavailable or permission denied.')).toBeVisible();
  fireEvent.waiting(video); expect(screen.getByText('Loading approved recording…')).toBeVisible();
  fireEvent.canPlay(video); fireEvent.error(video);
  expect(screen.getByText('Recording unavailable — media error')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Play recording' })).toBeDisabled();
  expect(screen.getByLabelText('Recording timeline')).toBeDisabled();
});

it('does not accept nonfinite duration for seeking', () => {
  render(<RecordedPlayer recordingId="TEST-APPROVED" />); const video = ready();
  Object.defineProperty(video, 'duration', { value: Infinity, configurable: true }); fireEvent.durationChange(video);
  expect(screen.getByLabelText('Recording timeline')).toBeDisabled();
  expect(screen.getByText('00:00 / Unavailable')).toBeVisible();
});

it('keeps pause available while an already playing recording buffers', async () => {
  render(<RecordedPlayer recordingId="TEST-APPROVED" />); const video = ready();
  fireEvent.click(screen.getByRole('button', { name: 'Play recording' }));
  await screen.findByRole('button', { name: 'Pause recording' });
  fireEvent.waiting(video);
  expect(screen.getByRole('button', { name: 'Pause recording' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Pause recording' })); expect(video.paused).toBe(true);
});

it('supports keyboard activation and fullscreen of the media viewport', async () => {
  const user = userEvent.setup(); const { container } = render(<RecordedPlayer recordingId="TEST-APPROVED" />); ready();
  await user.tab(); expect(screen.getByRole('button', { name: 'Play recording' })).toHaveFocus();
  await user.keyboard('{Enter}'); expect(await screen.findByRole('button', { name: 'Pause recording' })).toBeVisible();
  const request = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(container.querySelector('.camera-viewport'), 'requestFullscreen', { value: request });
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen recording' })); expect(request).toHaveBeenCalledOnce();
});

it('cleans up playback and source on unmount or selection change', () => {
  const { unmount } = render(<RecordedPlayer recordingId="TEST-APPROVED" />); const video = ready();
  const pause = vi.mocked(video.pause), load = vi.mocked(video.load);
  unmount(); expect(pause).toHaveBeenCalled(); expect(load).toHaveBeenCalled(); expect(video).not.toHaveAttribute('src');
});

it('formats actual media seconds without fabricating invalid values', () => {
  expect(mediaTime(65.9)).toBe('01:05'); expect(mediaTime(NaN)).toBe('Unavailable'); expect(mediaTime(-1)).toBe('Unavailable');
});
