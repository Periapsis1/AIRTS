// WebAudio sound effects + looping music. Sound-effect buffers are decoded
// once; "artillery" reuses the laser buffer pitched down (matching the pygame
// client's runtime pitch-shift). Browsers block audio until a user gesture, so
// resume() must be called from a click/keypress before anything plays.

// Base-relative so assets resolve at any mount point (see `base` in
// vite.config.ts); with base "./" this yields e.g. "./sounds/laser.mp3".
const BASE = (import.meta as { env?: Record<string, string> }).env?.BASE_URL ?? "/";

const SOUND_URLS: Record<string, string> = {
  laser: `${BASE}sounds/laser.mp3`,
  fast_laser: `${BASE}sounds/fast_laser.mp3`,
};
const MUSIC_URLS = [`${BASE}music/ambient1.mp3`, `${BASE}music/ambient2.mp3`];

export class AudioEngine {
  private ctx: AudioContext | null = null;
  private buffers = new Map<string, AudioBuffer>();
  private music: HTMLAudioElement | null = null;
  private started = false;
  masterVolume = 0.6;
  musicVolume = 0.25;

  /** Decode sound buffers. Safe to call before any user gesture. */
  async preload(): Promise<void> {
    if (this.ctx) return;
    try {
      this.ctx = new AudioContext();
    } catch {
      return;
    }
    await Promise.all(
      Object.entries(SOUND_URLS).map(async ([name, url]) => {
        try {
          const res = await fetch(url);
          const buf = await res.arrayBuffer();
          this.buffers.set(name, await this.ctx!.decodeAudioData(buf));
        } catch {
          /* asset missing — skip */
        }
      }),
    );
  }

  /** Resume the audio context + start music. Call from a user gesture. */
  resume(): void {
    if (!this.ctx) void this.preload();
    this.ctx?.resume();
    if (!this.started) {
      this.started = true;
      this.startMusic();
    }
  }

  private startMusic(): void {
    try {
      // Vary the pick by current time without Math.random (banned in workflows
      // but fine here); a simple time-based index is enough.
      const idx = Math.floor(performance.now() / 1000) % MUSIC_URLS.length;
      this.music = new Audio(MUSIC_URLS[idx]);
      this.music.loop = true;
      this.music.volume = this.musicVolume;
      void this.music.play();
    } catch {
      /* ignore */
    }
  }

  /** Play a server sound event by name. */
  play(name: string): void {
    if (!this.ctx) return;
    let bufName = name;
    let rate = 1;
    if (name === "artillery") {
      bufName = "laser";
      rate = 1 / 1.7; // matches the pygame artillery pitch-shift
    }
    const buf = this.buffers.get(bufName);
    if (!buf) return;
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = rate;
    const gain = this.ctx.createGain();
    gain.gain.value = this.masterVolume;
    src.connect(gain).connect(this.ctx.destination);
    src.start();
  }
}

export const audio = new AudioEngine();
