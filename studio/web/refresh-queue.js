// A completion event arriving during a read must trigger a read after it.
// Otherwise a snapshot captured while busy can leave controls disabled forever.
export function createRefreshQueue(read) {
  let pending = null, again = false;
  return function refresh(afterChange = false) {
    if (pending) { again ||= afterChange; return pending; }
    pending = (async () => {
      do { again = false; await read(); } while (again);
    })().finally(() => { pending = null; });
    return pending;
  };
}
