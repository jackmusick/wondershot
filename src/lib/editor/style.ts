import { writable } from 'svelte/store';

export interface DrawStyle {
  color: string;
  width: number;
}

export const drawStyle = writable<DrawStyle>({ color: '#ff3b30ff', width: 4 });
