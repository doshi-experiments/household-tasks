import React, {useState} from 'react';
import {Alert, Badge, EmptyState, PageHeader, SegmentedControl} from '@doshi-experiments/design-system/react';
import {patch, post} from './api';
import {useAction, useResource} from './hooks';
import {Pending} from './pending';
import {TaskBoard} from './board';
import {TaskTable} from './table';
import {celebrate} from './celebrate';

export const PRIORITIES = [[1, 'High'], [2, 'Medium'], [3, 'Low']];
export const PRIORITY_WORD = {1:'high', 2:'medium', 3:'low'};
export const PRIORITY_TONE = {1:'warning', 2:'info', 3:undefined};

export function dueText(t) {
  if (t.state === 'overdue') return <span className="tasks-overdue">{t.due_text} <Badge tone="error">{t.days_overdue} day{t.days_overdue === 1 ? '' : 's'} overdue</Badge></span>;
  if (t.state === 'someday') return <span className="tasks-muted">No date</span>;
  return <span className={t.state === 'due' ? 'tasks-due' : ''}>{t.due_text}{t.schedule.due_time ? ` · ${t.schedule.due_time}` : ''}
    {t.snoozed_until && <span className="tasks-snoozed">snoozed</span>}</span>;
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

  // one place for every write, so the board and the table behave the same
  const ops = {
    done: (t, event) => action.run(async () => {
      try {
        const r = await post(`tasks/${t.id}/complete`, {done_by:me, source:'web', occurrence:t.occurrence});
        celebrate(event);
        action.setNotice(r.task.closed ? `Done: ${t.title}.` : `Done: ${t.title}. Next one ${r.task.due_text}.`);
      } catch (e) {
        if (e.status !== 409) throw e;
        action.setNotice(`${t.title} was already done.`);
      }
      await list.reload();
    }, `done:${t.id}`),
    snooze: (t, until) => action.run(async () => {
      try {
        const r = await post(`tasks/${t.id}/snooze`, {done_by:me, source:'web', occurrence:t.occurrence, ...(until ? {until} : {})});
        action.setNotice(`Snoozed ${t.title} until ${r.task.due_text}.`);
      } catch (e) {
        if (e.status !== 409) throw e;
        action.setNotice(`${t.title} was already done.`);
      }
      await list.reload();
    }, `snooze:${t.id}`),
    change: (t, body, quiet) => action.run(async () => {
      await patch(`tasks/${t.id}`, body);
      if (!quiet) action.setNotice(`Updated ${t.title}.`);
      await list.reload();
    }, `change:${t.id}`),
  };

  const overdue = tasks.filter(t => t.state === 'overdue').length;
  const alarms = tasks.filter(t => t.alarm && (t.state === 'due' || t.state === 'overdue')).length;
  const inEach = Object.fromEntries(PERIODS.map(([p]) => [p, tasks.filter(t => inPeriod(t, p)).length]));
  return <div className="tasks-stack">
    <PageHeader title={recurring ? 'Recurring tasks' : 'One-off tasks'}
      description={recurring ? 'Chores that come back on a schedule. Done moves each one to its next date.' : 'Things to do once. Drag cards to reorder or change their priority.'}
      actions={<a className="ds-button" data-variant="primary" href={`#/task/new?from=${kind}`}>New task</a>}/>
    <div className="tasks-toolbar">
      <SegmentedControl label="View" value={view} onValueChange={chooseView} options={[['board', 'Board'], ['table', 'Table']]}/>
      <label className="tasks-period">
        <span>Show</span>
        <select className="ds-select-input" value={period} onChange={e => choosePeriod(e.target.value)}>
          {PERIODS.map(([p, label]) => <option key={p} value={p}>{label} ({inEach[p]})</option>)}
        </select>
      </label>
      {(overdue > 0 || alarms > 0) && <span className="tasks-attention" role="status">
        {overdue > 0 && <Badge tone="error">{overdue} overdue</Badge>}
        {alarms > 0 && <Badge tone="error">{alarms} alarm{alarms === 1 ? '' : 's'} due</Badge>}
      </span>}
      <span className="tasks-muted tasks-toolbar-count">{tasks.length} open</span>
    </div>
    {action.error && <Alert tone="error">{action.error}</Alert>}
    {action.notice && <Alert tone="success">{action.notice}</Alert>}
    {list.error && <Alert tone="error">{list.error}</Alert>}
    {list.loading && !list.data && <Pending>Loading tasks…</Pending>}
    {list.data && !tasks.length && <EmptyState title="Nothing here" description={recurring ? 'No recurring tasks yet. Add one, or tell the Telegram bot something like “water the plants every Saturday”.' : 'No open tasks. Add one, or send it to the Telegram bot.'}/>}
    {list.data && !!tasks.length && !inView.length && <EmptyState title="Nothing due in this period" description="Choose All to see everything."/>}
    {list.data && !!inView.length && (view === 'board'
      ? <TaskBoard tasks={inView} recurring={recurring} ops={ops} action={action}/>
      : <TaskTable tasks={inView} recurring={recurring} boot={boot} ops={ops} action={action} refreshing={list.loading}/>)}
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
