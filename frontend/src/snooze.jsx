import React, {useState} from 'react';
import {Menu} from '@base-ui/react/menu';
import {Button, Dialog, TextField} from '@doshi-experiments/design-system/react';

const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const plus = n => {const d = new Date(); d.setHours(12); d.setDate(d.getDate() + n); return d;};

/** The snooze choices as of today: [label, YYYY-MM-DD]. */
export function snoozeChoices() {
  const day = new Date().getDay();                 // 0 Sun … 6 Sat
  const toSat = ((6 - day + 7) % 7) || 7;          // the coming Saturday (next week's when it's Saturday)
  return [
    ['Tomorrow', iso(plus(1))],
    ['In 3 days', iso(plus(3))],
    [day === 6 || day === 0 ? 'Next weekend' : 'This weekend', iso(plus(day === 0 ? 6 : toSat))],
    ['Next week', iso(plus(7))],
  ];
}

/** One raised "Snooze ▾" button; the menu holds every duration plus a date
    picker. onSnooze(until) with a YYYY-MM-DD date. */
export function SnoozeButton({onSnooze, disabled, loading}) {
  const [picking, setPicking] = useState(false), [date, setDate] = useState('');
  return <>
    <Menu.Root>
      <Menu.Trigger className="ds-button tasks-snooze" disabled={disabled || loading} aria-busy={loading || undefined}>
        Snooze
        <svg viewBox="0 0 16 16" aria-hidden="true" width="14" height="14"><path d="M3.5 6l4.5 4.5L12.5 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner className="tasks-menu-positioner" sideOffset={6} align="end">
          <Menu.Popup className="tasks-menu">
            {snoozeChoices().map(([label, until]) =>
              <Menu.Item key={label} className="tasks-menu-item" onClick={() => onSnooze(until)}>{label}</Menu.Item>)}
            <Menu.Separator className="tasks-menu-separator"/>
            <Menu.Item className="tasks-menu-item" onClick={() => {setDate(iso(plus(1))); setPicking(true);}}>Pick a date…</Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
    <Dialog open={picking} onOpenChange={setPicking} title="Snooze until" description="It stays on its schedule; this only hides it until then."
      actions={<Button variant="primary" disabled={!date} onClick={() => {setPicking(false); onSnooze(date);}}>Snooze</Button>}>
      <TextField label="Date" type="date" min={iso(plus(1))} value={date} onValueChange={setDate}/>
    </Dialog>
  </>;
}
