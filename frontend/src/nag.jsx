import React from 'react';
import {CheckboxField, Select, TimeField} from '@doshi-experiments/design-system/react';

const EVERY = [['15', 'Every 15 minutes'], ['30', 'Every 30 minutes'], ['60', 'Every hour'], ['120', 'Every 2 hours']];
const clock = hhmm => {const [h, m] = hhmm.split(':').map(Number); return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;};
const later = (hhmm, hours) => {const [h, m] = hhmm.split(':').map(Number); return `${String(Math.min(h + hours, 23)).padStart(2, '0')}:${String(m).padStart(2, '0')}`;};
// a value saved through the API may not be one of the choices; keep it selectable
const withValue = (options, v) => !v || options.some(([k]) => k === String(v)) ? options : [...options, [String(v), `Every ${v} minutes`]];

/** The form's copy of a task's nag: {every, escalate_at, escalate_every, escalate_to: [ids]}, or null. */
export const nagFromTask = nag => nag ? {...nag, escalate_at:nag.escalate_at || ''} : null;

/** What the API takes: null turns it off; escalation fields only when escalating. */
export const nagBody = nag => !nag ? null : {every:nag.every || null, escalate_at:nag.escalate_at || null,
  escalate_every:nag.escalate_at ? nag.escalate_every : null, escalate_to:nag.escalate_at ? nag.escalate_to : []};

/** value: the form's nag (or null); dueTime: the schedule's time; assignee: person id or ''. */
export function NagBuilder({value, onChange, dueTime, assignee, people}) {
  const start = dueTime || '17:30';
  const who = people.find(p => p.id === assignee)?.name || 'everyone';
  const set = patch => onChange({...value, ...patch});
  const escalating = !!value?.escalate_at;
  // at least one person always gets the escalation
  const toggle = id => {const to = value.escalate_to.includes(id) ? value.escalate_to.filter(x => x !== id) : [...value.escalate_to, id];
    if (to.length) set({escalate_to:to});};
  return <fieldset className="ds-field-group tasks-schedule">
    <legend>Keep reminding</legend>
    <div className="tasks-stack-tight">
      <CheckboxField label="Repeat the reminder until it’s done" checked={!!value}
        onCheckedChange={on => onChange(on ? {every:30, escalate_at:'', escalate_every:60, escalate_to:[]} : null)}
        hint={`On the day it’s due, from ${clock(start)}: a push to ${who} and a message in the Telegram group, each a little snippier than the last, until someone taps Done. Waits while night mode is on. Not in the summaries or read out.`}/>
      {value && <>
        <div className="tasks-inline">
          <Select label="How often" value={String(value.every || '')} onValueChange={v => set({every:Number(v) || null})}
            options={[...withValue(EVERY, value.every), ...(escalating ? [['', 'Only the critical alert']] : [])]}/>
        </div>
        <CheckboxField label="Then send a critical alert" checked={escalating}
          onCheckedChange={on => set(on ? {escalate_at:later(start, 3), escalate_every:value.escalate_every || 60,
            escalate_to:value.escalate_to.length ? value.escalate_to : people.map(p => p.id)} : {escalate_at:'', every:value.every || 30})}
          hint="To the people you pick and the group, repeating until someone taps Done. Goes out in night mode too."/>
        {escalating && <>
          <div className="tasks-inline">
            <TimeField label="From" value={value.escalate_at} onValueChange={v => set({escalate_at:v || later(start, 3)})}/>
            <Select label="Then" value={String(value.escalate_every || '')} onValueChange={v => set({escalate_every:Number(v) || null})}
              options={[...withValue(EVERY, value.escalate_every), ['', 'Just once']]}/>
          </div>
          <fieldset className="tasks-chips"><legend>To</legend>{people.map(p =>
            <CheckboxField key={p.id} label={p.name} checked={value.escalate_to.includes(p.id)} onCheckedChange={() => toggle(p.id)}/>)}</fieldset>
        </>}
      </>}
    </div>
  </fieldset>;
}
