import React, {useEffect, useState} from 'react';
import {Button, CheckboxField, SegmentedControl, TextField} from '@doshi-experiments/design-system/react';
import {Select, TimeField} from './controls';
import {post} from './api';

const DAYS = [['MO', 'Mon'], ['TU', 'Tue'], ['WE', 'Wed'], ['TH', 'Thu'], ['FR', 'Fri'], ['SA', 'Sat'], ['SU', 'Sun']];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const SEASONS = [[3, 'Spring'], [6, 'Summer'], [9, 'Fall'], [12, 'Winter']];
const DAY_NUMBERS = Array.from({length:31}, (_, i) => [String(i + 1), String(i + 1)]);

// Split an RRULE into the builder's calendar modes; anything else is "custom".
export function ruleToParts(rule) {
  const p = Object.fromEntries((rule || '').split(';').filter(Boolean).map(x => x.split('=')));
  const n = Number(p.INTERVAL || 1);
  if (p.FREQ === 'WEEKLY' && p.BYDAY) return {mode:'weekly', every:n, days:p.BYDAY.split(',')};
  if (p.FREQ === 'MONTHLY' && p.BYMONTHDAY && !p.BYDAY) return {mode:'monthly', every:n, day:Number(p.BYMONTHDAY)};
  if (p.FREQ === 'YEARLY' && p.BYMONTH && p.BYMONTHDAY) {
    const months = p.BYMONTH.split(',').map(Number);
    if (p.BYMONTHDAY === '21' && months.every(m => [3, 6, 9, 12].includes(m))) return {mode:'seasonal', seasons:months};
    if (months.length === 1) return {mode:'yearly', month:months[0], day:Number(p.BYMONTHDAY)};
  }
  return {mode:'custom', custom:rule || ''};
}

export function partsToRule(parts) {
  const every = n => n > 1 ? `;INTERVAL=${n}` : '';
  switch (parts.mode) {
    case 'weekly': return `FREQ=WEEKLY${every(parts.every)};BYDAY=${(parts.days.length ? parts.days : ['SA']).join(',')}`;
    case 'monthly': return `FREQ=MONTHLY${every(parts.every)};BYMONTHDAY=${parts.day}`;
    case 'yearly': return `FREQ=YEARLY;BYMONTH=${parts.month};BYMONTHDAY=${parts.day}`;
    case 'seasonal': return `FREQ=YEARLY;BYMONTH=${(parts.seasons.length ? parts.seasons : [3]).sort((a, b) => a - b).join(',')};BYMONTHDAY=21`;
    default: return parts.custom || '';
  }
}

const DEFAULT_PARTS = {mode:'weekly', every:1, days:['SA'], day:1, month:4, seasons:[3, 9], custom:''};

/** value: {kind, rrule, interval_n, interval_unit, flex, due_time}; anchor: first due date (YYYY-MM-DD). */
export function ScheduleBuilder({value, onChange, anchor}) {
  const [parts, setParts] = useState(() => ({...DEFAULT_PARTS, ...(value.kind === 'rrule' ? ruleToParts(value.rrule) : {})}));
  const [phrase, setPhrase] = useState(''), [phraseError, setPhraseError] = useState('');
  const [preview, setPreview] = useState(null);
  const set = patch => onChange({...value, ...patch});
  const setRule = patch => {const next = {...parts, ...patch}; setParts(next); set({rrule:partsToRule(next)});};

  useEffect(() => {
    const ctl = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const r = await post('tasks/parse-schedule', {...value, anchor_date:anchor || undefined});
        if (!ctl.signal.aborted) setPreview({text:r.text, next:r.next_text, error:''});
      } catch (e) {if (!ctl.signal.aborted) setPreview({error:e.message, next:[]});}
    }, 300);
    return () => {clearTimeout(timer); ctl.abort();};
  }, [JSON.stringify(value), anchor]);

  const readPhrase = async () => {
    setPhraseError('');
    try {
      const r = await post('tasks/parse-schedule', {text:phrase, anchor_date:anchor || undefined});
      const s = r.schedule;
      if (s.kind === 'rrule') setParts({...DEFAULT_PARTS, ...ruleToParts(s.rrule)});
      onChange({...value, kind:s.kind, rrule:s.rrule, interval_n:s.interval_n, interval_unit:s.interval_unit,
        flex:s.flex || value.flex, due_time:s.due_time || value.due_time});
      setPhrase('');
    } catch (e) {setPhraseError(e.message);}
  };

  const toggle = (list, item) => list.includes(item) ? list.filter(x => x !== item) : [...list, item];
  return <fieldset className="ds-field-group tasks-schedule">
    <legend>Schedule</legend>
    <div className="tasks-stack-tight">
    <div className="tasks-phrase">
      <TextField label="Describe it" value={phrase} onValueChange={setPhrase} placeholder="every 30 days from done · every Saturday · seasonally"
        error={phraseError} hint="Type a schedule in words, or set it below." onKeyDown={e => {if (e.key === 'Enter') {e.preventDefault(); readPhrase();}}}/>
      <Button size="small" disabled={!phrase.trim()} onClick={readPhrase}>Use this</Button>
    </div>
    <SegmentedControl size="small" label="Repeats" value={value.kind} onValueChange={kind => set({kind, ...(kind === 'rrule' ? {rrule:partsToRule(parts)} : {}),
      ...(kind === 'interval' && !value.interval_n ? {interval_n:1, interval_unit:'months'} : {})})}
      options={[['none', 'Once'], ['rrule', 'On a calendar'], ['interval', 'After it’s done']]}/>

    {value.kind === 'interval' && <div className="tasks-inline">
      <TextField label="Every" type="number" min="1" inputMode="numeric" value={String(value.interval_n || '')} onValueChange={v => set({interval_n:Number(v) || ''})}/>
      <Select label="Unit" value={value.interval_unit || 'days'} onValueChange={u => set({interval_unit:u})}
        options={[['days', 'days'], ['weeks', 'weeks'], ['months', 'months'], ['years', 'years']]}/>
      <p className="tasks-muted tasks-inline-note">Counts from when it was last done, so a late one moves the next one too.</p>
    </div>}

    {value.kind === 'rrule' && <>
      <Select label="Pattern" value={parts.mode} onValueChange={mode => setRule({mode})}
        options={[['weekly', 'Weekly on certain days'], ['monthly', 'Monthly on a day'], ['yearly', 'Yearly on a date'], ['seasonal', 'Seasonally'], ['custom', 'Custom rule']]}/>
      {parts.mode === 'weekly' && <>
        <Select label="How often" value={String(parts.every)} onValueChange={v => setRule({every:Number(v)})}
          options={[['1', 'Every week'], ['2', 'Every other week'], ['3', 'Every 3 weeks'], ['4', 'Every 4 weeks']]}/>
        <fieldset className="tasks-chips"><legend>On</legend>{DAYS.map(([code, label]) =>
          <CheckboxField key={code} label={label} checked={parts.days.includes(code)} onCheckedChange={() => setRule({days:toggle(parts.days, code)})}/>)}</fieldset>
      </>}
      {parts.mode === 'monthly' && <div className="tasks-inline">
        <Select label="How often" value={String(parts.every)} onValueChange={v => setRule({every:Number(v)})}
          options={[['1', 'Every month'], ['2', 'Every 2 months'], ['3', 'Every 3 months (quarterly)'], ['6', 'Every 6 months']]}/>
        <Select label="On day" value={String(parts.day)} onValueChange={v => setRule({day:Number(v)})}
          options={[...DAY_NUMBERS, ['-1', 'Last day']]}/>
      </div>}
      {parts.mode === 'yearly' && <div className="tasks-inline">
        <Select label="Month" value={String(parts.month)} onValueChange={v => setRule({month:Number(v)})}
          options={MONTHS.map((m, i) => [String(i + 1), m])}/>
        <Select label="Day" value={String(parts.day)} onValueChange={v => setRule({day:Number(v)})} options={DAY_NUMBERS}/>
      </div>}
      {parts.mode === 'seasonal' && <fieldset className="tasks-chips"><legend>At the start of</legend>{SEASONS.map(([m, label]) =>
        <CheckboxField key={m} label={label} checked={parts.seasons.includes(m)} onCheckedChange={() => setRule({seasons:toggle(parts.seasons, m)})}/>)}</fieldset>}
      {parts.mode === 'custom' && <TextField label="RRULE" value={parts.custom} onValueChange={custom => setRule({custom})} hint="RFC 5545 rule without DTSTART, e.g. FREQ=MONTHLY;BYDAY=1SA"/>}
      <p className="tasks-muted">Stays on the calendar: doing it late doesn’t move the next one.</p>
    </>}

    <div className="tasks-when">
      <fieldset className="tasks-when-flex">
        <legend className="ds-field-label">Weekend</legend>
        <CheckboxField label="Any time that weekend" hint="Mon–Thu dates move to Friday; overdue from the Monday after." checked={value.flex === 'weekend'}
          onCheckedChange={on => set({flex:on ? 'weekend' : 'exact'})}/>
      </fieldset>
      <TimeField label="Time" hint="New tasks default to 5:30 PM." value={value.due_time || ''} onValueChange={v => set({due_time:v || null})}/>
    </div>
    {preview && (preview.error
      ? <p className="tasks-field-error" role="status">{preview.error}</p>
      : <p className="tasks-muted" role="status"><strong>{preview.text}</strong>{preview.next.length ? ` · next: ${preview.next.join(', ')}` : ''}</p>)}
    </div>
  </fieldset>;
}
