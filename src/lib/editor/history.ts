//! Generic snapshot history stack backing the editor's undo/redo.
//!
//! Each editor mutation pushes a full snapshot of state `T`. `undo`/`redo`
//! walk the stack; pushing after an undo truncates the (now stale) redo
//! branch. A "clean" index marks the snapshot last persisted to disk so the
//! UI can show an unsaved-changes indicator.

export class History<T> {
  private stack: T[];
  private index: number; // points at the current snapshot
  private cleanIndex: number; // snapshot index considered "saved"

  constructor(initial: T) {
    this.stack = [initial];
    this.index = 0;
    this.cleanIndex = 0;
  }

  current(): T {
    return this.stack[this.index];
  }

  push(snapshot: T): void {
    // Drop any redo branch ahead of the current position before appending.
    this.stack = this.stack.slice(0, this.index + 1);
    this.stack.push(snapshot);
    this.index = this.stack.length - 1;
  }

  undo(): T | null {
    if (this.index === 0) return null;
    this.index--;
    return this.current();
  }

  redo(): T | null {
    if (this.index >= this.stack.length - 1) return null;
    this.index++;
    return this.current();
  }

  markClean(): void {
    this.cleanIndex = this.index;
  }

  isClean(): boolean {
    return this.index === this.cleanIndex;
  }
}
