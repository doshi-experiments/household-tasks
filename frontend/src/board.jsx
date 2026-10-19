import React, {useEffect, useMemo, useState} from 'react';
import {DndContext, DragOverlay, KeyboardSensor, PointerSensor, TouchSensor, closestCorners, useDroppable,
  useSensor, useSensors} from '@dnd-kit/core';
import {SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy} from '@dnd-kit/sortable';
import {CSS} from '@dnd-kit/utilities';
import {Button} from '@doshi-experiments/design-system/react';
import {SnoozeButton} from './snooze';
import {AlarmToggle, PRIORITIES, PRIORITY_WORD, dueText} from './tasks';

const COLUMN = id => `col-${id}`;

/** Keyboard dragging: Left and Right jump straight to the neighbouring column
    (the stock getter spends the first press inside the current one); Up and
    Down reorder as usual. */
function columnKeys(event, args) {
  const step = {ArrowRight:1, ArrowLeft:-1}[event.code];
  if (!step) return sortableKeyboardCoordinates(event, args);
  event.preventDefault();
  const c = args.currentCoordinates, r = args.context.collisionRect;
  const lists = [...document.querySelectorAll('.tasks-column-list')].map(el => el.getBoundingClientRect());
  const cx = r ? r.left + r.width / 2 : c.x, cy = r ? r.top + r.height / 2 : c.y;
  const i = lists.findIndex(l => cx >= l.left - 12 && cx <= l.right + 12 && cy >= l.top - 60 && cy <= l.bottom + 60);
  const to = lists[i + step];
  if (i < 0 || !to) return c;
  return {x:to.left + (c.x - lists[i].left), y:Math.max(to.top + 8, Math.min(c.y, to.bottom - 24))};
}

/** Columns of draggable cards. Drag a card (by its handle, or with the
    keyboard: focus the handle, Space, arrows, Space) to reorder it or move it
    to another column; onMove(task, column, position) saves it for everyone.
    columns: [[id, label, ariaLabel]]; columnOf(task) -> id; order sorts a column. */
export function Board({tasks, columns, columnOf, order, onMove, renderCard, className = ''}) {
  const byId = useMemo(() => Object.fromEntries(tasks.map(t => [t.id, t])), [tasks]);
  const group = () => {
    const cols = Object.fromEntries(columns.map(([id]) => [id, []]));
    [...tasks].sort(order).forEach(t => (cols[columnOf(t)] || cols[columns[0][0]]).push(t.id));
    return cols;
  };
  const [cols, setCols] = useState(group);
  const [dragging, setDragging] = useState(null);
  useEffect(() => {if (!dragging) setCols(group());}, [tasks]);   // server truth, except mid-drag

  const sensors = useSensors(
    useSensor(PointerSensor, {activationConstraint:{distance:6}}),
    useSensor(TouchSensor, {activationConstraint:{delay:180, tolerance:8}}),
    useSensor(KeyboardSensor, {coordinateGetter:columnKeys}));
  const colOf = id => typeof id === 'string' && id.startsWith('col-') ? id.slice(4)
    : Object.keys(cols).find(k => cols[k].includes(id));

  const onDragOver = ({active, over}) => {
    if (!over) return;
    const from = colOf(active.id), to = colOf(over.id);
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
    if (!over) {setCols(group()); return;}
    const col = colOf(active.id);
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
    if (String(columnOf(t)) === col && position === t.position) return;
    onMove(t, col, position);
  };

  const active = dragging ? byId[dragging] : null;
  return <DndContext sensors={sensors} collisionDetection={closestCorners} onDragStart={({active}) => setDragging(active.id)}
    onDragOver={onDragOver} onDragEnd={onDragEnd} onDragCancel={() => {setDragging(null); setCols(group());}}
    accessibility={{screenReaderInstructions:{draggable:'To move a task, press Space, use the arrow keys to move it, then press Space again to drop it or Escape to cancel.'}}}>
    <div className={`tasks-board ${className}`}>
      {columns.map(([id, label, aria]) => <Column key={id} id={id} label={label} aria={aria || label} ids={cols[id]}>
        {cols[id].map(tid => byId[tid] && <SortableCard key={tid} task={byId[tid]} renderCard={renderCard}/>)}
      </Column>)}
    </div>
    <DragOverlay>{active ? renderCard(active, {overlay:true}) : null}</DragOverlay>
  </DndContext>;
}

/** High / Medium / Low columns for household tasks. */
export function TaskBoard({tasks, recurring, ops, action}) {
  return <Board tasks={tasks} columns={PRIORITIES.map(([p, label]) => [String(p), label, `${label} priority`])}
    columnOf={t => String(t.priority in {1:1, 2:1, 3:1} ? t.priority : 2)}
    order={(a, b) => (a.position ?? 0) - (b.position ?? 0)}
    onMove={(t, col, position) => ops.change(t, {priority:PRIORITY_WORD[col], position}, true)}
    renderCard={(t, {handle, overlay}) => <Card task={t} recurring={recurring} ops={ops} action={action} handle={handle} overlay={overlay}/>}/>;
}

function Column({id, label, aria, ids, children}) {
  const {setNodeRef, isOver} = useDroppable({id:COLUMN(id)});
  return <section className={`tasks-column${isOver ? ' is-over' : ''}`} aria-label={aria}>
    <h2 className="tasks-column-head"><span>{label}</span><span className="tasks-muted">{ids.length}</span></h2>
    <SortableContext id={COLUMN(id)} items={ids} strategy={verticalListSortingStrategy}>
      <ol ref={setNodeRef} className="tasks-column-list">{children}{!ids.length && <li className="tasks-column-empty">Drop a task here</li>}</ol>
    </SortableContext>
  </section>;
}

function SortableCard({task, renderCard}) {
  const {attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging} = useSortable({id:task.id});
  return <li ref={setNodeRef} style={{transform:CSS.Transform.toString(transform), transition}} className={isDragging ? 'is-dragging' : ''}>
    {renderCard(task, {handle:<button type="button" ref={setActivatorNodeRef} className="tasks-handle" aria-label={`Move ${task.title}`} {...attributes} {...listeners}>
      <svg viewBox="0 0 12 18" width="12" height="18" aria-hidden="true"><g fill="currentColor"><circle cx="3" cy="3" r="1.6"/><circle cx="9" cy="3" r="1.6"/><circle cx="3" cy="9" r="1.6"/><circle cx="9" cy="9" r="1.6"/><circle cx="3" cy="15" r="1.6"/><circle cx="9" cy="15" r="1.6"/></g></svg>
    </button>})}
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
    </div>
    {!overlay && <div className="tasks-card-actions">
      <AlarmToggle task={t} disabled={action.busy} loading={action.pending === `alarm:${t.id}`} onToggle={on => ops.alarm(t, on)}/>
      {t.state !== 'someday' && <SnoozeButton disabled={action.busy} loading={action.pending === `snooze:${t.id}`}
        onSnooze={until => ops.snooze(t, until)}/>}
      <Button variant="primary" loading={action.pending === `done:${t.id}`} disabled={action.busy}
        onClick={e => {const ev = {currentTarget:e.currentTarget}; ops.done(t, ev);}}>Done</Button>
    </div>}
  </article>;
}
