import React, {useEffect, useMemo, useState} from 'react';
import {DndContext, DragOverlay, KeyboardSensor, PointerSensor, TouchSensor, closestCorners, useDroppable,
  useSensor, useSensors} from '@dnd-kit/core';
import {SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy} from '@dnd-kit/sortable';
import {CSS} from '@dnd-kit/utilities';
import {Badge, Button} from '@doshi-experiments/design-system/react';
import {SnoozeButton} from './snooze';
import {PRIORITIES, PRIORITY_WORD, dueText} from './tasks';

const COLUMN = id => `col-${id}`;

function group(tasks) {
  const cols = {1:[], 2:[], 3:[]};
  [...tasks].sort((a, b) => (a.position ?? 0) - (b.position ?? 0)).forEach(t => cols[t.priority in cols ? t.priority : 2].push(t.id));
  return cols;
}

/** High / Medium / Low columns of cards. Drag a card (by its handle, or with the
    keyboard: focus the handle, Space, arrows, Space) to reorder it or move it to
    another priority; the new order is saved for everyone. */
export function TaskBoard({tasks, recurring, ops, action}) {
  const byId = useMemo(() => Object.fromEntries(tasks.map(t => [t.id, t])), [tasks]);
  const [cols, setCols] = useState(() => group(tasks));
  const [dragging, setDragging] = useState(null);
  useEffect(() => {if (!dragging) setCols(group(tasks));}, [tasks]);   // server truth, except mid-drag

  const sensors = useSensors(
    useSensor(PointerSensor, {activationConstraint:{distance:6}}),
    useSensor(TouchSensor, {activationConstraint:{delay:180, tolerance:8}}),
    useSensor(KeyboardSensor, {coordinateGetter:sortableKeyboardCoordinates}));
  const columnOf = id => typeof id === 'string' && id.startsWith('col-') ? Number(id.slice(4))
    : Number(Object.keys(cols).find(k => cols[k].includes(id)));

  const onDragOver = ({active, over}) => {
    if (!over) return;
    const from = columnOf(active.id), to = columnOf(over.id);
    if (!from || !to || from === to) return;
    setCols(c => {
      const target = [...c[to]];
      const at = typeof over.id === 'string' ? target.length : Math.max(0, target.indexOf(over.id));
      target.splice(at, 0, active.id);
      return {...c, [from]:c[from].filter(id => id !== active.id), [to]:target};
    });
  };
  const onDragEnd = ({active, over}) => {
    setDragging(null);
    if (!over) {setCols(group(tasks)); return;}
    const col = columnOf(active.id);
    let ids = cols[col];
    const overIdx = typeof over.id === 'string' ? ids.length - 1 : ids.indexOf(over.id);
    const fromIdx = ids.indexOf(active.id);
    if (overIdx >= 0 && fromIdx !== overIdx) ids = arrayMove(ids, fromIdx, overIdx);
    setCols(c => ({...c, [col]:ids}));
    const i = ids.indexOf(active.id);
    const before = byId[ids[i - 1]]?.position, after = byId[ids[i + 1]]?.position;
    const position = before != null && after != null ? (before + after) / 2
      : before != null ? before + 1024 : after != null ? after - 1024 : 1024;
    const t = byId[active.id];
    if (t.priority === col && position === t.position) return;
    ops.change(t, {priority:PRIORITY_WORD[col], position}, true);
  };

  const active = dragging ? byId[dragging] : null;
  return <DndContext sensors={sensors} collisionDetection={closestCorners} onDragStart={({active}) => setDragging(active.id)}
    onDragOver={onDragOver} onDragEnd={onDragEnd} onDragCancel={() => {setDragging(null); setCols(group(tasks));}}
    accessibility={{screenReaderInstructions:{draggable:'To move a task, press Space, use the arrow keys to move it, then press Space again to drop it or Escape to cancel.'}}}>
    <div className="tasks-board">
      {PRIORITIES.map(([p, label]) => <Column key={p} id={p} label={label} ids={cols[p]}>
        {cols[p].map(id => byId[id] && <SortableCard key={id} task={byId[id]} recurring={recurring} ops={ops} action={action}/>)}
      </Column>)}
    </div>
    <DragOverlay>{active ? <Card task={active} recurring={recurring} overlay/> : null}</DragOverlay>
  </DndContext>;
}

function Column({id, label, ids, children}) {
  const {setNodeRef, isOver} = useDroppable({id:COLUMN(id)});
  return <section className={`tasks-column${isOver ? ' is-over' : ''}`} aria-label={`${label} priority`}>
    <h2 className="tasks-column-head"><span>{label}</span><span className="tasks-muted">{ids.length}</span></h2>
    <SortableContext id={COLUMN(id)} items={ids} strategy={verticalListSortingStrategy}>
      <ol ref={setNodeRef} className="tasks-column-list">{children}{!ids.length && <li className="tasks-column-empty">Drop a task here</li>}</ol>
    </SortableContext>
  </section>;
}

function SortableCard({task, recurring, ops, action}) {
  const {attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging} = useSortable({id:task.id});
  return <li ref={setNodeRef} style={{transform:CSS.Transform.toString(transform), transition}} className={isDragging ? 'is-dragging' : ''}>
    <Card task={task} recurring={recurring} ops={ops} action={action}
      handle={<button type="button" ref={setActivatorNodeRef} className="tasks-handle" aria-label={`Move ${task.title}`} {...attributes} {...listeners}>
        <svg viewBox="0 0 12 18" width="12" height="18" aria-hidden="true"><g fill="currentColor"><circle cx="3" cy="3" r="1.6"/><circle cx="9" cy="3" r="1.6"/><circle cx="3" cy="9" r="1.6"/><circle cx="9" cy="9" r="1.6"/><circle cx="3" cy="15" r="1.6"/><circle cx="9" cy="15" r="1.6"/></g></svg>
      </button>}/>
  </li>;
}

function Card({task:t, recurring, ops, action, handle, overlay}) {
  return <article className={`tasks-card tasks-card-${t.state}${overlay ? ' is-overlay' : ''}`}>
    <div className="tasks-card-top">
      {handle}
      <div className="tasks-card-text">
        <a className="tasks-card-title" href={`#/task/${t.id}?from=${recurring ? 'recurring' : 'one-off'}`}>{t.title}</a>
        <div className="tasks-card-meta">
          {t.state !== 'someday' && dueText(t)}
          <span>{t.category}</span>
          {t.assignee_name && <span>{t.assignee_name}</span>}
        </div>
        {recurring && <div className="tasks-card-meta">{t.schedule_text}</div>}
      </div>
      {t.alarm && <Badge tone="error">Alarm</Badge>}
    </div>
    {!overlay && <div className="tasks-card-actions">
      {t.state !== 'someday' && <SnoozeButton disabled={action.busy} loading={action.pending === `snooze:${t.id}`}
        onSnooze={until => ops.snooze(t, until)}/>}
      <Button variant="primary" loading={action.pending === `done:${t.id}`} disabled={action.busy}
        onClick={e => {const ev = {currentTarget:e.currentTarget}; ops.done(t, ev);}}>Done</Button>
    </div>}
  </article>;
}
