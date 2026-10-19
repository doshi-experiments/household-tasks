import React from 'react';
import {Toast} from '@base-ui/react/toast';

/* App-wide toasts (Base UI): confirmations that survive moving to another page,
   such as "Saved" after the edit form closes. toast(title, description?). */
const manager = Toast.createToastManager();
export const toast = (title, description) => manager.add({title, description, timeout:4000});

function Toasts() {
  const {toasts} = Toast.useToastManager();
  return toasts.map(t => <Toast.Root key={t.id} toast={t} className="tasks-toast">
    <svg className="tasks-toast-icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M3 8.5l3.2 3L13 4.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
    <div className="tasks-toast-text">
      <Toast.Title className="tasks-toast-title"/>
      {t.description && <Toast.Description className="tasks-toast-description"/>}
    </div>
    <Toast.Close className="tasks-toast-close" aria-label="Dismiss">
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
    </Toast.Close>
  </Toast.Root>);
}

export function ToastProvider({children}) {
  return <Toast.Provider toastManager={manager} limit={3}>
    {children}
    <Toast.Portal><Toast.Viewport className="tasks-toasts"><Toasts/></Toast.Viewport></Toast.Portal>
  </Toast.Provider>;
}
