import React, {useMemo, useState} from 'react';
import {Button, DataTable} from '@doshi-experiments/design-system/react';
import {SnoozeButton} from './snooze';
import {AlarmToggle, PRIORITIES, PRIORITY_WORD, dueText} from './tasks';
import {Select} from './controls';

const SORTERS = {
  due: t => [t.state === 'someday' ? 1 : 0, t.eff_due || '9999', t.schedule.due_time || ''],
  title: t => [t.title.toLowerCase()],
  category: t => [t.category.toLowerCase(), t.title.toLowerCase()],
  priority: t => [t.priority, t.alarm ? 0 : 1, t.title.toLowerCase()],
  alarm: t => [t.alarm ? 0 : 1, t.priority, t.title.toLowerCase()],
  who: t => [t.assignee_name || '~', t.title.toLowerCase()],
};
const cmp = (a, b) => {for (let i = 0; i < a.length; i++) {if (a[i] < b[i]) return -1; if (a[i] > b[i]) return 1;} return 0;};

function SortHeader({id, label, sort, setSort}) {
  const on = sort.key === id;
  return <th scope="col" aria-sort={on ? (sort.dir > 0 ? 'ascending' : 'descending') : undefined}>
    <button type="button" className="tasks-sort" onClick={() => setSort(on ? {key:id, dir:-sort.dir} : {key:id, dir:1})}>
      {label}
      <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true" className={on ? 'is-on' : ''}>
        <path d={on && sort.dir < 0 ? 'M2 7.5 6 3.5l4 4' : 'M2 4.5l4 4 4-4'} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    </button>
  </th>;
}

/** Click a heading to sort by it; every column but Due has a filter under its
    heading (the period switch above handles dates); category, priority and the
    alarm are edited in place. Filtering never adds rows above the table, so it
    doesn't jump; Clear sits in the filter row. */
export function TaskTable({tasks, recurring, boot, ops, action, refreshing}) {
  const empty = {title:'', category:'', priority:'', alarm:'', who:''};
  const [f, setF] = useState(empty);
  const [sort, setSort] = useState({key:null, dir:1});
  const set = (k, v) => setF(old => ({...old, [k]:v}));
  const shown = useMemo(() => {
    const rows = tasks.filter(t => (!f.title || `${t.title} ${t.notes} ${t.schedule_text}`.toLowerCase().includes(f.title.toLowerCase()))
    && (!f.category || t.category === f.category)
    && (!f.priority || String(t.priority) === f.priority)
    && (!f.alarm || (f.alarm === 'on') === t.alarm)
    && (!f.who || (f.who === 'anyone' ? !t.assignee : t.assignee === f.who)));
    return sort.key ? [...rows].sort((a, b) => sort.dir * cmp(SORTERS[sort.key](a), SORTERS[sort.key](b))) : rows;
  }, [tasks, f, sort]);
  const filtering = Object.values(f).some(Boolean);
  const from = recurring ? 'recurring' : 'one-off';
  const household = boot.categories.filter(c => c.area !== 'homelab'), homelab = boot.categories.filter(c => c.area === 'homelab');
  const categoryOptions = household.map(c => [c.name, c.name]);
  return <DataTable aria-label={recurring ? 'Recurring tasks' : 'One-off tasks'} className={`tasks-table${refreshing ? ' tasks-refreshing' : ''}`}>
    <thead>
      <tr>{[['due', 'Due'], ['title', 'Task'], ['category', 'Category'], ['priority', 'Priority'], ['alarm', 'Alarm'], ['who', 'Who']].map(([id, label]) =>
        <SortHeader key={id} id={id} label={label} sort={sort} setSort={setSort}/>)}
        <th scope="col"><span className="ds-visually-hidden">Actions</span></th></tr>
      <tr className="tasks-filter-row">
        <td className="tasks-muted tasks-filter-note">Dates: “Show” above</td>
        <td><input className="ds-text-input" aria-label="Filter by task" placeholder={recurring ? 'Task, notes or schedule' : 'Task or notes'}
          value={f.title} onChange={e => set('title', e.target.value)}/></td>
        <td><Select label="Filter by category" layout="hidden" size="small" value={f.category} onValueChange={v => set('category', v)}
          options={[['', 'All'], ...categoryOptions]}/></td>
        <td><Select label="Filter by priority" layout="hidden" size="small" value={f.priority} onValueChange={v => set('priority', v)}
          options={[['', 'All'], ...PRIORITIES.map(([p, l]) => [String(p), l])]}/></td>
        <td><Select label="Filter by alarm" layout="hidden" size="small" value={f.alarm} onValueChange={v => set('alarm', v)}
          options={[['', 'All'], ['on', 'On'], ['off', 'Off']]}/></td>
        <td><Select label="Filter by person" layout="hidden" size="small" value={f.who} onValueChange={v => set('who', v)}
          options={[['', 'Everyone'], ...boot.people.map(p => [p.id, p.name]), ['anyone', 'Unassigned']]}/></td>
        <td className="tasks-filter-clear">{filtering && <button type="button" className="tasks-text-button" onClick={() => setF(empty)}
          aria-label={`Clear filters (showing ${shown.length} of ${tasks.length})`}>Clear filters</button>}</td>
      </tr>
    </thead>
    <tbody>
      {shown.map(t => <tr key={t.id}>
        <td>{dueText(t)}</td>
        <td className="tasks-title-cell">
          <a href={`#/task/${t.id}?from=${from}`}>{t.title}</a>
          {recurring && <div className="tasks-muted">{t.schedule_text}</div>}
        </td>
        <td><Select label={`Category for ${t.title}`} layout="hidden" variant="quiet" size="small" value={t.category}
          disabled={action.busy} onValueChange={v => ops.change(t, {category:v})}
          options={categoryOptions} groups={[['Move to Homelab', homelab.map(c => [c.name, c.name])]]}/></td>
        <td><Select label={`Priority for ${t.title}`} layout="hidden" variant="quiet" size="small" value={String(t.priority)}
          disabled={action.busy} onValueChange={v => ops.change(t, {priority:PRIORITY_WORD[v]})}
          options={PRIORITIES.map(([p, l]) => [String(p), l])}/></td>
        <td><AlarmToggle task={t} disabled={action.busy} loading={action.pending === `alarm:${t.id}`} onToggle={on => ops.alarm(t, on)}/></td>
        <td>{t.assignee_name || <span className="tasks-muted">Anyone</span>}</td>
        <td><div className="tasks-actions">
          <Button variant="primary" loading={action.pending === `done:${t.id}`} disabled={action.busy}
            onClick={e => {const ev = {currentTarget:e.currentTarget}; ops.done(t, ev);}}>Done</Button>
          {t.state !== 'someday' && <SnoozeButton disabled={action.busy} loading={action.pending === `snooze:${t.id}`}
            onSnooze={until => ops.snooze(t, until)}/>}
        </div></td>
      </tr>)}
      {!shown.length && <tr><td colSpan={7} className="tasks-table-empty">Nothing matches these filters.</td></tr>}
    </tbody>
  </DataTable>;
}
