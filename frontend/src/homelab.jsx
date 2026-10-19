import React, {useState} from 'react';
import {Alert, Badge, Button, EmptyState, PageHeader, Select} from '@doshi-experiments/design-system/react';
import {patch, post} from './api';
import {useAction, useResource} from './hooks';
import {Pending} from './pending';
import {Board} from './board';
import {PRIORITY_TONE, dueText} from './tasks';
import {celebrate} from './celebrate';

export const STAGES = [['idea', 'Ideas'], ['next', 'Next up'], ['doing', 'Doing'], ['done', 'Done']];
const DONE_DAYS = 14;
const projectKey = 'tasks-project-homelab';
const readProject = () => {try {return localStorage.getItem(projectKey) || '';} catch {return '';}};

const stageOf = t => t.status === 'done' ? 'done' : t.stage || 'idea';
// Done: newest first. Otherwise priority first, then the order people dragged them into.
const order = (a, b) => a.status === 'done' && b.status === 'done'
  ? (b.last_done_at || '').localeCompare(a.last_done_at || '')
  : (a.priority - b.priority) || ((a.position ?? 0) - (b.position ?? 0));

function doneText(iso) {
  if (!iso) return 'Done';
  const days = Math.round((new Date().setHours(12, 0, 0, 0) - new Date(`${iso.slice(0, 10)}T12:00:00`)) / 864e5);
  return days <= 0 ? 'Done today' : days === 1 ? 'Done yesterday' : `Done ${days} days ago`;
}

/** Software to build, update or host. Columns are progress, not priority, and
    nothing here ever reminds anyone. */
export function HomelabPage({boot, me}) {
  const list = useResource(`tasks?kind=homelab&done_days=${DONE_DAYS}`);
  const action = useAction();
  const [project, setProject] = useState(readProject);
  const chooseProject = v => {setProject(v); try {localStorage.setItem(projectKey, v);} catch {/* private window */}};
  const projects = boot.categories.filter(c => c.area === 'homelab');
  const tasks = list.data?.tasks || [];
  const shown = project ? tasks.filter(t => t.category === project) : tasks;
  const open = tasks.filter(t => t.status === 'open');
  const count = name => open.filter(t => t.category === name).length;

  const ops = {
    done: (t, event) => action.run(async () => {
      try {
        await post(`tasks/${t.id}/complete`, {done_by:me, source:'web'});
        celebrate(event);
        action.setNotice(`Done: ${t.title}.`);
      } catch (e) {
        if (e.status !== 409) throw e;
        action.setNotice(`${t.title} was already done.`);
      }
      await list.reload();
    }, `done:${t.id}`),
    move: (t, stage, position) => action.run(async () => {
      if (stage === 'done') {
        if (t.status !== 'done') {
          await post(`tasks/${t.id}/complete`, {done_by:me, source:'web'});
          celebrate();
          action.setNotice(`Done: ${t.title}.`);
        }
      } else if (t.status === 'done') {
        await patch(`tasks/${t.id}`, {status:'open', stage, position});
        action.setNotice(`Reopened ${t.title}.`);
      } else {
        await patch(`tasks/${t.id}`, {stage, position});
      }
      await list.reload();
    }, `move:${t.id}`),
  };

  return <div className="tasks-stack">
    <PageHeader title="Homelab"
      description="Software to build, update or host. Nothing here sends reminders. Drag a card to the next column as it moves along."
      actions={<a className="ds-button" data-variant="primary" data-size="small" href="#/task/new?from=homelab">New task</a>}/>
    <div className="tasks-toolbar">
      <Select label="Project" layout="inline" value={project} onValueChange={chooseProject} className="tasks-period"
        options={[['', `All projects (${open.length})`], ...projects.map(c => [c.name, `${c.name} (${count(c.name)})`])]}/>
      <span className="tasks-muted tasks-toolbar-count">{open.length} open · done in the last {DONE_DAYS} days shown</span>
    </div>
    {action.error && <Alert tone="error">{action.error}</Alert>}
    {action.notice && <Alert tone="success">{action.notice}</Alert>}
    {list.error && <Alert tone="error">{list.error}</Alert>}
    {list.loading && !list.data && <Pending>Loading homelab tasks…</Pending>}
    {list.data && !tasks.length && <EmptyState title="Nothing here yet"
      description="Add one, or tell the Telegram bot something like “idea: a dashboard that shows the backups”."/>}
    {list.data && !!tasks.length && <Board className="tasks-board-stages" tasks={shown} columns={STAGES}
      columnOf={stageOf} order={order} onMove={ops.move}
      renderCard={(t, {handle, overlay}) => <LabCard task={t} handle={handle} overlay={overlay} ops={ops} action={action}/>}/>}
  </div>;
}

function LabCard({task:t, handle, overlay, ops, action}) {
  const done = t.status === 'done';
  const stage = stageOf(t);
  return <article className={`tasks-card${done ? ' tasks-card-done' : ''}${overlay ? ' is-overlay' : ''}`}>
    <div className="tasks-card-top">
      {handle}
      <div className="tasks-card-text">
        <a className="tasks-card-title" href={`#/task/${t.id}?from=homelab`}>{t.title}</a>
        <div className="tasks-card-meta">
          <span>{t.category}</span>
          {done ? <span>{doneText(t.last_done_at)}</span> : t.eff_due && dueText(t)}
        </div>
      </div>
      {!done && <Badge tone={PRIORITY_TONE[t.priority]}>{t.priority_label}</Badge>}
    </div>
    {!overlay && !done && stage !== 'idea' && <div className="tasks-card-actions">
      <Button size="small" variant="primary" loading={action.pending === `done:${t.id}`} disabled={action.busy}
        onClick={e => {const ev = {currentTarget:e.currentTarget}; ops.done(t, ev);}}>Done</Button>
    </div>}
  </article>;
}
