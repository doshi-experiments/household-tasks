import React, {useState} from 'react';
import {Alert, Badge, EmptyState, PageHeader, SegmentedControl, Select, ToggleButton, toast} from '@doshi-experiments/design-system/react';
import {patch, post} from './api';
import {useAction, useOnChange, useResource} from './hooks';
import {Pending} from './pending';
import {TaskBoard} from './board';
import {TaskTable} from './table';
import {celebrate} from './celebrate';
import {addedToast, doneToast} from './undo';

// Low to High everywhere; the board turns it round once its columns stack on a phone.
export const PRIORITIES = [[3, 'Low'], [2, 'Medium'], [1, 'High']];
export const PRIORITY_WORD = {1:'high', 2:'medium', 3:'low'};
export const PRIORITY_TONE = {1:'warning', 2:'info', 3:undefined};

export function dueText(t) {
  if (t.state === 'overdue') return <span className="tasks-overdue">{t.due_text} <Badge tone="error">{t.days_overdue} day{t.days_overdue === 1 ? '' : 's'} overdue</Badge></span>;
  if (t.state === 'someday') return <span className="tasks-muted">No date</span>;
  return <span className={t.state === 'due' ? 'tasks-due' : ''}>{t.due_text}{t.schedule.due_time ? ` · ${t.schedule.due_time}` : ''}
    {t.snoozed_until && <span className="tasks-snoozed">snoozed</span>}</span>;
}

/** Shows whether a task's alarm is on and switches it: the system's toggle in its
    error tone, so on is tinted with words (never bare red) and off is quiet. */
export function AlarmToggle({task:t, onToggle, disabled, loading}) {
  return <ToggleButton tone="error" size="small" className="tasks-alarm" pressed={t.alarm} onPressedChange={onToggle}
    disabled={disabled} loading={loading}
    title={t.alarm ? 'Alarm until done is on: tap to turn it off' : 'Turn on “alarm until done”'}
    aria-label={`Alarm until done for ${t.title}`}>
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M8 2.2a4 4 0 0 0-4 4v2.6L2.8 11h10.4L12 8.8V6.2a4 4 0 0 0-4-4ZM6.4 12.8a1.7 1.7 0 0 0 3.2 0"
        fill={t.alarm ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/>
      {!t.alarm && <path d="M2.5 2.5l11 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>}
    </svg>
    <span>{t.alarm ? 'Alarm on' : 'Alarm off'}</span>
  </ToggleButton>;
}

const viewKey = kind => `tasks-view-${kind}`;
const readView = kind => {try {return localStorage.getItem(viewKey(kind)) || 'board';} catch {return 'board';}};
const periodKey = kind => `tasks-period-${kind}`;
const readPeriod = kind => {try {return localStorage.getItem(periodKey(kind)) || (kind === 'recurring' ? 'week' : 'all');} catch {return 'all';}};
export const PERIODS = [['now', 'Due now'], ['week', 'Next 7 days'], ['month', 'This month'], ['all', 'All']];

/** Overdue and due tasks always show; undated ones only under All. */
export function inPeriod(t, period) {
  if (period === 'all' || t.state === 'overdue' || t.state === 'due') return true;
  if (period === 'now' || !t.eff_due) return false;
  const today = new Date(); today.setHours(12, 0, 0, 0);
  const end = period === 'week' ? new Date(today.getTime() + 7 * 864e5)
    : new Date(today.getFullYear(), today.getMonth() + 1, 0, 12);
  return new Date(`${t.eff_due}T12:00:00`) <= end;
}

export function TasksPage({kind, boot, me}) {
  const recurring = kind === 'recurring';
  const [view, setView] = useState(() => readView(kind));
  const [period, setPeriod] = useState(() => readPeriod(kind));
  const list = useResource(`tasks?kind=${recurring ? 'recurring' : 'oneoff'}`);
  const action = useAction();
  const chooseView = v => {setView(v); try {localStorage.setItem(viewKey(kind), v);} catch {/* private window */}};
  const choosePeriod = v => {setPeriod(v); try {localStorage.setItem(periodKey(kind), v);} catch {/* private window */}};
  const tasks = list.data?.tasks || [];
  const inView = tasks.filter(t => inPeriod(t, period));
  useOnChange(list.reload);
  const alreadyDone = t => toast(`${t.title} was already done.`, undefined, {tone:'info'});

  // one place for every write, so the board and the table behave the same
  const ops = {
    done: (t, event) => action.run(async () => {
      try {
        const r = await post(`tasks/${t.id}/complete`, {done_by:me, source:'web', occurrence:t.occurrence});
        celebrate(event);
        doneToast(t, r.task);
      } catch (e) {
        if (e.status !== 409) throw e;
        alreadyDone(t);
      }
      await list.reload();
    }, `done:${t.id}`),
    snooze: (t, until) => action.run(async () => {
      try {
        const r = await post(`tasks/${t.id}/snooze`, {done_by:me, source:'web', occurrence:t.occurrence, ...(until ? {until} : {})});
        toast(`Snoozed: ${t.title}`, `Until ${r.task.due_text}.`);
      } catch (e) {
        if (e.status !== 409) throw e;
        alreadyDone(t);
      }
      await list.reload();
    }, `snooze:${t.id}`),
    alarm: (t, on) => action.run(async () => {
      const r = await patch(`tasks/${t.id}`, {alarm:on});
      const n = r.task;
      toast(`Alarm ${on ? 'on' : 'off'}: ${t.title}`, !on ? undefined
        : n.eff_due ? `It pushes ${n.alarm_at ? `at ${n.alarm_at}` : 'with the evening feed-the-dogs announcement (8:30 PM if that doesn’t play)'} every day from ${n.due_text} until it’s done.`
        : 'It starts once the task has a due date.');
      await list.reload();
    }, `alarm:${t.id}`),
    change: (t, body, quiet) => action.run(async () => {
      await patch(`tasks/${t.id}`, body);
      if (!quiet) toast(`Updated: ${t.title}`);
      await list.reload();
    }, `change:${t.id}`),
    // the plus at the top of a board column: the column's priority, Inbox, and on
    // this tab a schedule read from the words (else every week)
    add: async (col, title, position) => {
      try {
        const r = await post('tasks', {title, category:'Inbox', priority:PRIORITY_WORD[col], position, source:'web', added_by:me,
          ...(recurring ? {read_schedule:true, schedule:{kind:'interval', interval_n:1, interval_unit:'weeks'}} : {})});
        const n = r.task;
        addedToast(n, n.repeats ? `${n.schedule_text}. Next one ${n.due_text}.`
          : !inPeriod(n, period) ? 'It has no date yet, so it shows under All.' : undefined);
      } catch (e) {
        toast('Couldn’t add that task', e.message, {tone:'error'});
        throw e;
      }
      await list.reload();
    },
  };

  const overdue = tasks.filter(t => t.state === 'overdue').length;
  const alarms = tasks.filter(t => t.alarm && (t.state === 'due' || t.state === 'overdue')).length;
  const inEach = Object.fromEntries(PERIODS.map(([p]) => [p, tasks.filter(t => inPeriod(t, p)).length]));
  return <div className="tasks-stack">
    <PageHeader title={recurring ? 'Recurring tasks' : 'One-off tasks'}
      description={recurring ? 'Chores that come back on a schedule. Done moves each one to its next date.' : 'Things to do once. Drag cards to reorder or change their priority.'}
      actions={<a className="ds-button" data-variant="primary" data-size="small" href={`#/task/new?from=${kind}`}>New task</a>}/>
    <div className="tasks-toolbar">
      <SegmentedControl size="small" label="View" value={view} onValueChange={chooseView} options={[['board', 'Board'], ['table', 'Table']]}/>
      <Select label="Show" layout="inline" value={period} onValueChange={choosePeriod} className="tasks-period"
        options={PERIODS.map(([p, label]) => [p, `${label} (${inEach[p]})`])}/>
      {(overdue > 0 || alarms > 0) && <span className="tasks-attention" role="status">
        {overdue > 0 && <Badge tone="error">{overdue} overdue</Badge>}
        {alarms > 0 && <Badge tone="error">{alarms} alarm{alarms === 1 ? '' : 's'} due</Badge>}
      </span>}
      <span className="tasks-muted tasks-toolbar-count">{tasks.length} open</span>
    </div>
    {action.error && <Alert tone="error">{action.error}</Alert>}
    {list.error && <Alert tone="error">{list.error}</Alert>}
    {list.loading && !list.data && <Pending>Loading tasks…</Pending>}
    {/* the board always shows, so its plus buttons can add the first task */}
    {list.data && view === 'board' && <>
      {!tasks.length && <p className="tasks-muted tasks-board-note">{recurring ? 'No recurring tasks yet. Add one with a plus, or tell the Telegram bot something like “water the plants every Saturday”.' : 'No open tasks. Add one with a plus, or send it to the Telegram bot.'}</p>}
      {!!tasks.length && !inView.length && <p className="tasks-muted tasks-board-note">Nothing due in this period. Choose All to see everything.</p>}
      <TaskBoard tasks={inView} recurring={recurring} ops={ops} action={action}/>
    </>}
    {list.data && view === 'table' && <>
      {!tasks.length && <EmptyState title="Nothing here" description={recurring ? 'No recurring tasks yet. Add one, or tell the Telegram bot something like “water the plants every Saturday”.' : 'No open tasks. Add one, or send it to the Telegram bot.'}/>}
      {!!tasks.length && !inView.length && <EmptyState title="Nothing due in this period" description="Choose All to see everything."/>}
      {!!inView.length && <TaskTable tasks={inView} recurring={recurring} boot={boot} ops={ops} action={action} refreshing={list.loading}/>}
    </>}
  </div>;
}

export function isThisWeekend(day) {
  if (!day) return false;
  const now = new Date(); now.setHours(12, 0, 0, 0);
  const wd = now.getDay();                           // Fri 5, Sat 6, Sun 0
  const start = new Date(now);
  start.setDate(now.getDate() + (wd >= 5 ? 5 - wd : wd === 0 ? -2 : 5 - wd));
  const end = new Date(start); end.setDate(start.getDate() + 2);
  const d = new Date(`${day}T12:00:00`);
  return d >= start && d <= end;
}
