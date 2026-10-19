import React, {useEffect, useRef, useState} from 'react';
import {Alert, Button, EmptyState, PageHeader, SegmentedControl} from '@doshi-experiments/design-system/react';
import {api, del, post} from './api';
import {Pending} from './pending';

// Built for one-handed use in a store: big tick targets, instant feedback,
// undo instead of confirmation. Refreshes every 30 s for items the bot adds.
export function ShoppingList({boot, me}) {
  const lists = boot.shopping_lists;
  // The toggle picks the list you're looking at, and new items go on it.
  const [target, setTarget] = useState(() => {
    let saved = '';
    try {saved = localStorage.getItem('tasks-shopping-list') || '';} catch {/* private window */}
    return lists.some(l => l.name === saved) ? saved : lists[0]?.name || 'Groceries';
  });
  const choose = name => {setTarget(name); setUndo(null); try {localStorage.setItem('tasks-shopping-list', name);} catch {/* private window */}};
  const [items, setItems] = useState(null), [bought, setBought] = useState([]), [error, setError] = useState('');
  const [title, setTitle] = useState(''), [undo, setUndo] = useState(null), [showBought, setShowBought] = useState(false);
  const input = useRef(null);
  const load = async () => {
    try {
      const [open, done] = await Promise.all([api('shopping'), api('shopping?bought=1')]);
      setItems(open.items); setBought(done.items.slice(0, 30)); setError('');
    } catch (e) {setError(e.message);}
  };
  useEffect(() => {
    load();
    const timer = setInterval(() => {if (document.visibilityState === 'visible') load();}, 30000);
    const onShow = () => {if (document.visibilityState === 'visible') load();};
    document.addEventListener('visibilitychange', onShow);
    return () => {clearInterval(timer); document.removeEventListener('visibilitychange', onShow);};
  }, []);

  const add = async e => {
    e.preventDefault();
    const text = title.trim();
    if (!text) return;
    setTitle('');
    try {
      const r = await post('shopping', {items:text.split(/\s*,\s*/).filter(Boolean).map(t => ({title:t, list:target, added_by:me, source:'web'}))});
      const dup = r.items.filter(i => i.duplicate).map(i => i.title);
      setError(dup.length ? `Already on the list: ${dup.join(', ')}` : '');
      await load();
    } catch (err) {setError(err.message); setTitle(text);}
    input.current?.focus();
  };
  const buy = async item => {
    setItems(xs => xs.filter(x => x.id !== item.id));
    setUndo(item);
    try {await post(`shopping/${item.id}/buy`, {by:me});} catch (e) {if (e.status !== 409) setError(e.message);}
    load();
  };
  const unbuy = async item => {setUndo(null); await post(`shopping/${item.id}/unbuy`); load();};
  const remove = async item => {setItems(xs => xs.filter(x => x.id !== item.id)); await del(`shopping/${item.id}`); load();};

  return <div className="tasks-stack tasks-shopping">
    <PageHeader title="Shopping" description="Tap an item to tick it off. Add several at once with commas."/>
    <SegmentedControl size="small" label="List" value={target} onValueChange={choose}
      options={lists.map(l => [l.name, `${l.name}${items ? ` (${items.filter(i => i.list === l.name).length})` : ''}`])}/>
    <form className="tasks-quick-add" onSubmit={add}>
      <input ref={input} className="ds-text-input" aria-label={`Add to ${target}`} placeholder={`Add to ${target}…`} value={title} onChange={e => setTitle(e.target.value)} enterKeyHint="done"/>
      <Button size="small" variant="primary" type="submit" disabled={!title.trim()}>Add</Button>
    </form>
    {error && <Alert tone="warning">{error}</Alert>}
    {undo && <Alert tone="success" actions={<Button size="small" onClick={() => unbuy(undo)}>Undo</Button>}>Bought {undo.title}.</Alert>}
    {!items && !error && <Pending>Loading the list…</Pending>}
    {items && !items.some(i => i.list === target) && <EmptyState title={`Nothing on ${target}`} description="Add something above or send it to the Telegram bot."/>}
    {items && lists.filter(l => l.name === target).map(l => {
      const rows = items.filter(i => i.list === l.name);
      return rows.length > 0 && <section key={l.name} className="tasks-stack-tight">
        <ul className="tasks-items">{rows.map(i => <li key={i.id}>
          <button type="button" className="tasks-item" onClick={() => buy(i)} aria-label={`Bought ${i.title}`}>
            <span className="tasks-tick" aria-hidden="true"/><span><span className="tasks-item-title">{i.title}</span>
            {i.notes && <span className="tasks-muted"> · {i.notes}</span>}</span></button>
          <button type="button" className="tasks-item-remove" onClick={() => remove(i)} aria-label={`Remove ${i.title}`}>×</button>
        </li>)}</ul></section>;
    })}
    {bought.some(i => i.list === target) && <section className="tasks-stack-tight">
      <Button size="small" variant="ghost" onClick={() => setShowBought(v => !v)} aria-expanded={showBought}>{showBought ? 'Hide' : 'Show'} recently bought ({bought.filter(i => i.list === target).length})</Button>
      {showBought && <ul className="tasks-items tasks-items-bought">{bought.filter(i => i.list === target).map(i => <li key={i.id}>
        <button type="button" className="tasks-item" onClick={() => unbuy(i)} aria-label={`Put ${i.title} back on the list`}>
          <span className="tasks-tick is-done" aria-hidden="true"/><span><span className="tasks-item-title">{i.title}</span>
          <span className="tasks-muted"> · {i.bought_by || 'someone'}, {i.bought_at.slice(5, 10)}</span></span></button>
      </li>)}</ul>}
    </section>}
  </div>;
}
