export type FloatingPlayerDockState = {
  docked: boolean;
  title: string;
  onRestore: (() => void) | null;
};

let state: FloatingPlayerDockState = { docked: false, title: "", onRestore: null };
const listeners = new Set<() => void>();

function emit(next: FloatingPlayerDockState) {
  state = next;
  for (const listener of listeners) {
    listener();
  }
}

export function getFloatingPlayerDockState(): FloatingPlayerDockState {
  return state;
}

export function subscribeFloatingPlayerDock(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function dockFloatingPlayer(title: string, onRestore: () => void): void {
  emit({ docked: true, title, onRestore });
}

export function undockFloatingPlayer(): void {
  if (!state.docked) {
    return;
  }
  emit({ docked: false, title: "", onRestore: null });
}
