import React, {useEffect, useState} from 'react';
import {Alert, Button, Card, CheckboxField, DataTable, DateField, PageHeader, Select, TextField, toast} from '@doshi-experiments/design-system/react';
import {api, del, patch, post} from './api';
import {useAction, useOnChange} from './hooks';
import {Pending} from './pending';
import {ScheduleBuilder} from './schedule-builder';
import {PRIORITY_WORD, dueText} from './tasks';
import {STAGES} from './homelab';
import {celebrate} from './celebrate';
import {addedToast, archivedToast, doneToast} from './undo';

const EMPTY = {title:'', notes:'', category:'Inbox', priority:2, alarm:false, assignee:'', due:'',
  schedule:{kind:'none', rrule:null, interval_n:null, interval_unit:null, flex:'exact', due_time:null}};
const EMPTY_RECURRING = {...EMPTY, schedule:{...EMPTY.schedule, kind:'interval', interval_n:1, interval_unit:'weeks'}};
const EMPTY_HOMELAB = {...EMPTY, category:'New projects', priority:3, stage:'idea'};
const TAB_NAME = {'one-off':'One-off tasks', recurring:'Recurring tasks', homelab:'Homelab'};
const PRIORITY_OPTIONS = [['3', 'Low'], ['2', 'Medium'], ['1', 'High']];
const tabOf = t => t.area === 'homelab' ? 'homelab' : t.repeats ? 'recurring' : 'one-off';

export function TaskForm({id, from = 'one-off', boot, me}) {
  const [form, setForm] = useState(id ? null : from === 'recurring' ? EMPTY_RECURRING : from === 'homelab' ? EMPTY_HOMELAB : EMPTY), [task, setTask] = useState(null), [history, setHistory] = useState([]);
  const [loadError, setLoadError] = useState(''), [doneOn, setDoneOn] = useState('');
  const action = useAction();
  const load = async () => {
    try {
      const r = await api(`tasks/${id}`);
      const t = r.task;
      setTask(t); setHistory(r.completions);
      setForm({title:t.title, notes:t.notes, category:t.category, priority:t.priority, alarm:t.alarm, assignee:t.assignee || '', stage:t.stage || 'idea',
        due:t.due || '', schedule:{...t.schedule}});
    } catch (e) {setLoadError(e.message);}
  };
  useEffect(() => {if (id) load();}, [id]);
  useOnChange(() => {if (id) load();});
  if (loadError) return <Alert tone="error" title="Couldn’t open this task">{loadError}</Alert>;
  if (!form) return <Pending>Loading task…</Pending>;
  const set = patchObj => setForm(f => ({...f, ...patchObj}));
  // the chosen category decides the kind of task: homelab ones have a stage and never remind
  const household = boot.categories.filter(c => c.area !== 'homelab'), projects = boot.categories.filter(c => c.area === 'homelab');
  const lab = projects.some(c => c.name === form.category);

  const save = () => action.run(async () => {
    const body = lab
      ? {title:form.title, notes:form.notes, category:form.category, priority:PRIORITY_WORD[form.priority], stage:form.stage || 'idea'}
      : {title:form.title, notes:form.notes, category:form.category, priority:PRIORITY_WORD[form.priority], alarm:form.alarm,
        assignee:form.assignee || null, schedule:form.schedule};
    // Changing the date moves the next occurrence; leave it out unless it changed.
    if (!lab && (!task || form.due !== (task.due || ''))) body.due = form.due || null;
    if (task && task.status === 'done' && lab) delete body.stage;   // a finished task keeps its stage until reopened
    const r = task ? await patch(`tasks/${task.id}`, body) : await post('tasks', {...body, source:'web', added_by:me});
    // Saving closes the task: back to its tab, with a toast to confirm.
    const moved = task && tabOf(r.task) !== tabOf(task);
    const note = moved ? `Moved to ${TAB_NAME[tabOf(r.task)]}.` : r.task.repeats ? `Next one ${r.task.due_text}.` : undefined;
    if (task) toast(`Saved: ${r.task.title}`, note); else addedToast(r.task, note);
    location.hash = `#/${!task || moved ? tabOf(r.task) : from}`;
  }, 'save');
  const complete = event => action.run(async () => {
    const ev = {currentTarget:event?.currentTarget};
    try {
      const r = await post(`tasks/${task.id}/complete`, {done_by:me, source:'web', occurrence:task.occurrence,
        ...(doneOn ? {done_at:`${doneOn}T12:00:00`} : {})});
      celebrate(ev);
      doneToast(task, r.task);
    } catch (e) {if (e.status !== 409) throw e; toast(`${task.title} was already done.`, undefined, {tone:'info'});}
    setDoneOn(''); await load();
  }, 'complete');
  const skip = () => action.run(async () => {
    const r = await post(`tasks/${task.id}/skip`, {done_by:me, source:'web', occurrence:task.occurrence});
    toast(`Skipped: ${task.title}`, `Next one ${r.task.due_text}.`); await load();
  }, 'skip');
  const reopen = () => action.run(async () => {
    await patch(`tasks/${task.id}`, {status:'open'}); toast(`Reopened: ${task.title}`); await load();
  }, 'reopen');
  // no "are you sure": the toast's Undo brings it back as it was
  const archive = () => action.run(async () => {
    await del(`tasks/${task.id}`); archivedToast(task, task.status); location.hash = `#/${from}`;
  }, 'archive');

  const open = task?.status === 'open';
  return <div className="tasks-stack">
    <PageHeader eyebrow={<a href={`#/${from}`}>← {TAB_NAME[from] || 'Tasks'}</a>} title={task ? task.title : from === 'recurring' ? 'New recurring task' : from === 'homelab' ? 'New homelab task' : 'New task'}
      description={task && (lab ? <>{task.status === 'open' ? STAGES.find(([s]) => s === (task.stage || 'idea'))[1] : `Status: ${task.status}`} · {task.category}</>
        : <>{task.status === 'open' ? dueText(task) : `Status: ${task.status}`}{task.repeats ? ` · ${task.schedule_text}` : ''}</>)}/>
    {action.error && <Alert tone="error">{action.error}</Alert>}
    {open && <Card><div className="tasks-row">
      <div className="tasks-inline">
        <DateField label="Done on (optional)" value={doneOn} onValueChange={setDoneOn} placeholder="Now" hint="Leave empty for now."/>
      </div>
      <div className="tasks-actions">
        <Button size="small" variant="primary" loading={action.pending === 'complete'} disabled={action.busy} onClick={e => complete(e)}>Mark done</Button>
        {task.repeats && <Button size="small" loading={action.pending === 'skip'} disabled={action.busy} onClick={skip}>Skip this one</Button>}
      </div>
    </div></Card>}
    {task?.status === 'done' && <Card><div className="tasks-row">
      <span>This one is done.</span>
      <Button size="small" loading={action.pending === 'reopen'} disabled={action.busy} onClick={reopen}>Reopen</Button>
    </div></Card>}
    <Card className="tasks-stack-tight">
      <TextField label="Task" value={form.title} onValueChange={title => set({title})} required/>
      {lab ? <div className="tasks-grid">
        <Select label="Project" value={form.category} onValueChange={category => set({category})}
          options={projects.map(c => [c.name, c.name])} groups={[['Move to household', household.map(c => [c.name, c.name])]]}/>
        <Select label="Priority" value={String(form.priority)} onValueChange={v => set({priority:Number(v)})} options={PRIORITY_OPTIONS}
          hint="High: something running is broken or at risk. Medium: improves something you use. Low: an idea or something new."/>
        {task?.status !== 'done' && <Select label="Stage" value={form.stage || 'idea'} onValueChange={stage => set({stage})}
          options={STAGES.filter(([s]) => s !== 'done')}/>}
      </div> : <><div className="tasks-grid">
        <Select label="Category" value={form.category} onValueChange={category => set({category})}
          options={household.map(c => [c.name, c.name])} groups={[['Move to Homelab', projects.map(c => [c.name, c.name])]]}/>
        <Select label="Priority" value={String(form.priority)} onValueChange={v => set({priority:Number(v)})} options={PRIORITY_OPTIONS}
          hint={form.priority === 1 ? 'High also gets a daily push once it’s overdue.' : 'Shows in the morning and evening summaries.'}/>
        <Select label="Who" value={form.assignee} onValueChange={assignee => set({assignee})} hint="Assigned tasks notify that person; others notify everyone."
          options={[['', 'Anyone'], ...boot.people.map(p => [p.id, p.name])]}/>
        <DateField label={form.schedule.kind === 'none' ? 'Due date' : 'Next due'} value={form.due || ''} onValueChange={due => set({due})}
          placeholder={form.schedule.kind === 'none' ? 'Someday' : 'Today'}
          hint={form.schedule.kind === 'none' ? 'Leave empty for “someday”.' : task ? 'Change it to move the next one.' : 'Leave empty to start today.'}/>
      </div>
      <CheckboxField label="Alarm until done" checked={form.alarm} onCheckedChange={alarm => set({alarm})}
            hint="A critical push every day until someone marks it done: with the evening feed-the-dogs announcement (8:30 PM if that doesn’t play), or at the task’s own time if you set one other than 5:30 PM. Also read out with the announcement."/>
      <ScheduleBuilder value={form.schedule} onChange={schedule => set({schedule})} anchor={form.due || task?.schedule.anchor_date}/>
      </>}
      <label className="tasks-textarea"><span className="ds-field-label">Notes</span>
        <textarea className="ds-text-input" rows={3} value={form.notes} onChange={e => set({notes:e.target.value})}/></label>
      <div className="tasks-actions">
        <Button size="small" variant="primary" loading={action.pending === 'save'} disabled={action.busy || !form.title.trim()} onClick={save}>{task ? 'Save changes' : 'Add task'}</Button>
        {task && task.status !== 'archived' && <Button size="small" variant="ghost" loading={action.pending === 'archive'} disabled={action.busy} onClick={archive}>Archive</Button>}
      </div>
    </Card>
    {task && !!history.length && <section><h2>History</h2><DataTable aria-label="History">
      <thead><tr><th>When</th><th>What</th><th>Who</th><th>Via</th></tr></thead>
      <tbody>{history.map(h => <tr key={h.id}><td className="tasks-nowrap">{h.done_at.slice(0, 16).replace('T', ' ')}</td>
        <td>{h.kind === 'done' ? 'Done' : 'Skipped'}{h.nominal_due ? ` (due ${h.nominal_due})` : ''}</td><td>{h.done_by || '—'}</td><td>{h.source}</td></tr>)}</tbody>
    </DataTable></section>}
  </div>;
}
