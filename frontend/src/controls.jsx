import React, {useEffect, useId, useRef, useState} from 'react';
import {Select as BaseSelect} from '@base-ui/react/select';
import {Popover} from '@base-ui/react/popover';

/* App-styled replacements for the browser's own select, date and time
   controls, so every picker opens the same felt popup instead of an OS sheet.
   Values are strings, like native inputs. */

const Chevron = () => <svg className="tasks-picker-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
  <path d="M3.5 6l4.5 4.5L12.5 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>;
const Check = () => <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
  <path d="M3 8.5l3.2 3L13 4.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/></svg>;
const CalendarIcon = () => <svg className="tasks-picker-icon" viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
  <rect x="2" y="3.5" width="12" height="10.5" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.6"/>
  <path d="M2.5 7h11M5.5 2v3M10.5 2v3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>;

/** Field chrome shared by every picker: label above (or inline, or hidden) and a hint below. */
function Field({label, labelId, hint, hintId, layout, className = '', children}) {
  return <div className={`ds-field tasks-picker-field${layout === 'inline' ? ' is-inline' : ''} ${className}`}>
    <span id={labelId} className={`ds-field-label${layout === 'hidden' ? ' ds-visually-hidden' : ''}`}>{label}</span>
    {children}
    {hint && <p id={hintId} className="ds-field-hint">{hint}</p>}
  </div>;
}

/** options: [[value, label]]; groups: [[groupLabel, [[value, label]]]] shown after them.
    layout: 'stacked' (form field), 'inline' (label to the left) or 'hidden' (label for screen readers only).
    variant: 'field' (pressed-in) or 'quiet' (flat until hovered, for editing in a table). */
export function Select({label, value, onValueChange, options = [], groups = [], hint, disabled, layout = 'stacked',
  variant = 'field', size, className = '', triggerClassName = ''}) {
  const id = useId();
  const all = [...options, ...groups.flatMap(([, opts]) => opts)];
  const labelOf = v => all.find(([o]) => String(o) === String(v))?.[1] ?? '';
  const item = ([v, text]) => <BaseSelect.Item key={v} value={String(v)} className="tasks-option">
    <BaseSelect.ItemText>{text}</BaseSelect.ItemText>
    <BaseSelect.ItemIndicator className="tasks-option-check"><Check/></BaseSelect.ItemIndicator>
  </BaseSelect.Item>;
  return <Field label={label} labelId={`${id}-label`} hint={hint} hintId={`${id}-hint`} layout={layout} className={className}>
    <BaseSelect.Root value={String(value ?? '')} onValueChange={v => onValueChange?.(v)} disabled={disabled}>
      <BaseSelect.Trigger className={`tasks-picker tasks-picker-${variant}${size ? ` is-${size}` : ''} ${triggerClassName}`}
        aria-labelledby={`${id}-label`} aria-describedby={hint ? `${id}-hint` : undefined}>
        <BaseSelect.Value className="tasks-picker-value">{v => labelOf(v)}</BaseSelect.Value>
        <Chevron/>
      </BaseSelect.Trigger>
      <BaseSelect.Portal>
        <BaseSelect.Positioner className="tasks-menu-positioner" sideOffset={6} align="start" alignItemWithTrigger={false}>
          <BaseSelect.Popup className="tasks-menu tasks-select-popup">
            <BaseSelect.List>
              {options.map(item)}
              {groups.map(([g, opts]) => <BaseSelect.Group key={g} className="tasks-option-group">
                <BaseSelect.GroupLabel className="tasks-option-group-label">{g}</BaseSelect.GroupLabel>
                {opts.map(item)}
              </BaseSelect.Group>)}
            </BaseSelect.List>
          </BaseSelect.Popup>
        </BaseSelect.Positioner>
      </BaseSelect.Portal>
    </BaseSelect.Root>
  </Field>;
}

/** Times in half-hour steps (plus the current value if it's off the grid); '' = no time. */
export function TimeField({label, value, onValueChange, hint, allowEmpty = true, ...rest}) {
  const fmt = hhmm => {const [h, m] = hhmm.split(':').map(Number); return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;};
  const slots = Array.from({length:48}, (_, i) => `${String(Math.floor(i / 2)).padStart(2, '0')}:${i % 2 ? '30' : '00'}`);
  if (value && !slots.includes(value)) slots.push(value), slots.sort();
  return <Select label={label} hint={hint} value={value || ''} onValueChange={onValueChange} {...rest}
    options={[...(allowEmpty ? [['', 'No time']] : []), ...slots.map(s => [s, fmt(s)])]}/>;
}

// ---------------------------------------------------------------- dates
const pad = n => String(n).padStart(2, '0');
const isoOf = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const dateOf = iso => new Date(`${iso}T12:00:00`);
const addDays = (iso, n) => {const d = dateOf(iso); d.setDate(d.getDate() + n); return isoOf(d);};
const addMonths = (iso, n) => {const d = dateOf(iso); const day = d.getDate(); d.setDate(1); d.setMonth(d.getMonth() + n);
  d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate())); return isoOf(d);};
const todayIso = () => isoOf(new Date());
// "Wed 21 Oct 2026", like the rest of the app
export const longDate = iso => {const d = dateOf(iso);
  return `${d.toLocaleDateString('en', {weekday:'short'})} ${d.getDate()} ${d.toLocaleDateString('en', {month:'short'})} ${d.getFullYear()}`;};
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** A month grid. Arrow keys move a day or a week, Page Up/Down a month, Home/End the week; Enter picks. */
function Calendar({value, min, onPick}) {
  const start = value || (min && min > todayIso() ? min : todayIso());
  const [focus, setFocus] = useState(start);
  const grid = useRef(null), moved = useRef(false);
  const first = dateOf(focus.slice(0, 8) + '01');
  const lead = (first.getDay() + 6) % 7;                // Monday-first
  const cells = Array.from({length:42}, (_, i) => addDays(isoOf(first), i - lead));
  const month = first.getMonth();
  useEffect(() => {if (moved.current) grid.current?.querySelector(`[data-date="${focus}"]`)?.focus();}, [focus]);
  useEffect(() => {grid.current?.querySelector(`[data-date="${focus}"]`)?.focus();}, []);
  const go = next => {moved.current = true; setFocus(next);};
  const onKey = e => {
    const step = {ArrowLeft:-1, ArrowRight:1, ArrowUp:-7, ArrowDown:7}[e.key];
    if (step) go(addDays(focus, step));
    else if (e.key === 'PageUp') go(addMonths(focus, -1));
    else if (e.key === 'PageDown') go(addMonths(focus, 1));
    else if (e.key === 'Home') go(addDays(focus, -((dateOf(focus).getDay() + 6) % 7)));
    else if (e.key === 'End') go(addDays(focus, 6 - ((dateOf(focus).getDay() + 6) % 7)));
    else return;
    e.preventDefault();
  };
  return <div className="tasks-calendar">
    <div className="tasks-calendar-head">
      <button type="button" className="tasks-icon-button" aria-label="Previous month" onClick={() => go(addMonths(focus, -1))}>
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M10 3.5 5.5 8l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg></button>
      <span className="tasks-calendar-title" aria-live="polite">{first.toLocaleDateString(undefined, {month:'long', year:'numeric'})}</span>
      <button type="button" className="tasks-icon-button" aria-label="Next month" onClick={() => go(addMonths(focus, 1))}>
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg></button>
    </div>
    <table ref={grid} className="tasks-calendar-grid" role="grid" onKeyDown={onKey}>
      <thead><tr>{WEEKDAYS.map(d => <th key={d} scope="col" abbr={d}>{d.slice(0, 2)}</th>)}</tr></thead>
      <tbody>{Array.from({length:6}, (_, w) => <tr key={w}>{cells.slice(w * 7, w * 7 + 7).map(iso => {
        const off = dateOf(iso).getMonth() !== month, blocked = min && iso < min;
        return <td key={iso} role="gridcell" aria-selected={iso === value}>
          <button type="button" data-date={iso} tabIndex={iso === focus ? 0 : -1} disabled={blocked}
            className={`tasks-day${off ? ' is-outside' : ''}${iso === todayIso() ? ' is-today' : ''}${iso === value ? ' is-selected' : ''}`}
            aria-label={longDate(iso)} aria-current={iso === todayIso() ? 'date' : undefined}
            onClick={() => onPick(iso)}>{dateOf(iso).getDate()}</button>
        </td>;
      })}</tr>)}</tbody>
    </table>
  </div>;
}

/** A date field that opens the app's calendar. value: YYYY-MM-DD or ''. */
export function DateField({label, value, onValueChange, hint, min, placeholder = 'No date', clearable = true, layout = 'stacked', className = ''}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const pick = iso => {onValueChange(iso); setOpen(false);};
  const today = todayIso();
  return <Field label={label} labelId={`${id}-label`} hint={hint} hintId={`${id}-hint`} layout={layout} className={className}>
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger className="tasks-picker tasks-picker-field" aria-labelledby={`${id}-label ${id}-value`}
        aria-describedby={hint ? `${id}-hint` : undefined}>
        <span id={`${id}-value`} className={`tasks-picker-value${value ? '' : ' is-placeholder'}`}>{value ? longDate(value) : placeholder}</span>
        <CalendarIcon/>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner className="tasks-menu-positioner" sideOffset={6} align="start">
          <Popover.Popup className="tasks-menu tasks-date-popup" aria-label={`Choose ${label.toLowerCase()}`}>
            <Calendar value={value} min={min} onPick={pick}/>
            <div className="tasks-calendar-foot">
              {(!min || today >= min) && <button type="button" className="tasks-text-button" onClick={() => pick(today)}>Today</button>}
              {clearable && value && <button type="button" className="tasks-text-button" onClick={() => pick('')}>Clear</button>}
            </div>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  </Field>;
}
