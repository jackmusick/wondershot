import { writable } from 'svelte/store';
import type { Snippet } from 'svelte';

// The mounted video player supplies its actions to the shared application row.
export const videoToolbar = writable<Snippet | null>(null);
