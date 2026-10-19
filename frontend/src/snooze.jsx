import React, {useState} from 'react';
import {Button, DateField, Dialog, MenuButton} from '@doshi-experiments/design-system/react';

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
    <MenuButton label="Snooze" size="small" disabled={disabled} loading={loading} items={[
      ...snoozeChoices().map(([label, until]) => ({key:label, label, onSelect:() => onSnooze(until)})),
      'separator',
      {label:'Pick a date…', onSelect:() => {setDate(iso(plus(1))); setPicking(true);}},
    ]}/>
    <Dialog open={picking} onOpenChange={setPicking} title="Snooze until" description="It stays on its schedule; this only hides it until then."
      actions={<Button size="small" variant="primary" disabled={!date} onClick={() => {setPicking(false); onSnooze(date);}}>Snooze</Button>}>
      <DateField label="Date" min={iso(plus(1))} value={date} onValueChange={setDate} clearable={false}/>
    </Dialog>
  </>;
}
