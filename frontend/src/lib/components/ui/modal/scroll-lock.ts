// Reference-counted body scroll lock shared across modals.
// The first acquirer captures the prior overflow value; the last releaser
// restores it. Multiple concurrent modals are safe because each acquirer
// only contributes to the count — individual snapshots can't race.

let count = 0;
let previousOverflow = '';

export function acquireScrollLock(): () => void {
  if (count === 0) {
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }
  count++;

  let released = false;
  return function release() {
    if (released) return;
    released = true;
    count--;
    if (count === 0) {
      document.body.style.overflow = previousOverflow;
      previousOverflow = '';
    }
  };
}
