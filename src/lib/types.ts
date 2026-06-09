export type CaptureKind = 'image' | 'video';

export interface Capture {
  id: string;
  path: string;
  kind: CaptureKind;
  thumbnail: string;   // data URL or file src
  createdAt: number;   // epoch ms
  title: string;
}

export interface LibraryGroup {
  label: string;       // "Today", "Yesterday", or a date
  items: Capture[];
}

export type RecordingState =
  | { status: 'idle' }
  | { status: 'recording'; elapsedMs: number; paused: boolean };
