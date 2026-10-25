import {toast} from '@doshi-experiments/design-system/react';
import {del, patch, post} from './api';
import {changed} from './hooks';

// Toasts for the steps people take back: done, added and archived. Each one's
// Undo reverses it on the server, confirms in a toast of its own and tells the
// open views to reload (a toast outlives the page that raised it).
const undo = (title, run, outcome) => async () => {
  try {
    await run();
    toast(outcome, undefined, {tone:'info'});
    changed();
  } catch (e) {
    toast(`Couldn’t undo: ${title}`, e.message, {tone:'error'});
  }
};

/** r: the task the complete call returned (its completion_id is what Undo takes back). */
export function doneToast(t, r) {
  toast(`Done: ${t.title}`, r.closed ? undefined : `Next one ${r.due_text}.`, {action:{label:'Undo',
    onAction:undo(t.title, () => post(`tasks/${t.id}/undo`, {completion_id:r.completion_id}), `Undone: ${t.title}`)}});
}

export function addedToast(t, description) {
  toast(`Added: ${t.title}`, description, {action:{label:'Undo',
    onAction:undo(t.title, () => del(`tasks/${t.id}`), `Removed: ${t.title}`)}});
}

/** status: what the task was before archiving (open or done), which Undo restores. */
export function archivedToast(t, status) {
  toast(`Archived: ${t.title}`, 'Its history is kept.', {action:{label:'Undo',
    onAction:undo(t.title, () => patch(`tasks/${t.id}`, {status}), `Restored: ${t.title}`)}});
}
