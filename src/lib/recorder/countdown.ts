/** Pure countdown tick, mirroring countdown.py's `_tick`.
 *
 * Decrements the remaining seconds by one and reports whether the countdown
 * has reached (or passed) zero — at which point the recording should START.
 */
export function tickDown(remaining: number): { remaining: number; done: boolean } {
  const next = remaining - 1;
  return { remaining: next, done: next <= 0 };
}
