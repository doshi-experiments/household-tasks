import React, {useEffect, useRef, useState} from 'react';
import {Alert, Button, EmptyState, PageHeader, SegmentedControl, Select} from '@doshi-experiments/design-system/react';
import {api, del, patch, post} from './api';
import {Pending} from './pending';

// Built for one-handed use in a store: big tick targets, instant feedback,
// undo instead of confirmation. Refreshes every 30 s for items the bot adds.
// One flat list; every item carries a store, an aisle and a category. The
// toggle filters by store (new stores appear when the bot first names one).
const SHORT = {'Real Canadian Superstore': 'Superstore'};
const short = s => SHORT[s] || s;
const SORTS = [['store', 'Store & aisle'], ['category', 'Category'], ['added', 'Added']];

const readSaved = (key, fallback) => {
  try {return localStorage.getItem(key) || fallback;} catch {return fallback;}
};
const save = (key, value) => {try {localStorage.setItem(key, value);} catch {/* private window */}};

export function ShoppingList({boot, me}) {
  const shop = boot.shopping;
  const aislesFor = store => shop.aisles[store] || shop.default_aisles;
  const [store, setStore] = useState(() => readSaved('tasks-shopping-store', shop.defaults.store));
  const [sort, setSort] = useState(() => readSaved('tasks-shopping-sort', 'store'));
  const [items, setItems] = useState(null), [bought, setBought] = useState([]), [error, setError] = useState('');
  const [title, setTitle] = useState(''), [undo, setUndo] = useState(null), [showBought, setShowBought] = useState(false);
  const [addStore, setAddStore] = useState(shop.defaults.store), [addCategory, setAddCategory] = useState(shop.defaults.category);
  const [addAisle, setAddAisle] = useState('');
  const input = useRef(null);

  // Every store we know of: the seeded/created ones from bootstrap, plus any
  // a just-added item carries that bootstrap hasn't caught up with yet.
  const stores = [...shop.stores];
  for (const i of [...(items || []), ...bought]) if (!stores.includes(i.store)) stores.push(i.store);
  const filterStore = store !== 'all' && !stores.includes(store) ? shop.defaults.store : store;

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

  const chooseStore = s => {setStore(s); setUndo(null); save('tasks-shopping-store', s); if (s !== 'all') pickAddStore(s);};
  const chooseSort = s => {setSort(s); save('tasks-shopping-sort', s);};
  const pickAddStore = s => {setAddStore(s); setAddAisle('');};

  const add = async e => {
    e.preventDefault();
    const text = title.trim();
    if (!text) return;
    setTitle('');
    try {
      const r = await post('shopping', {items:text.split(/\s*,\s*/).filter(Boolean).map(t => ({
        title:t, store:addStore, category:addCategory, aisle:addAisle, added_by:me, source:'web'}))});
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
  const change = async (item, body) => {
    try {await patch(`shopping/${item.id}`, body);} catch (e) {setError(e.message);}
    load();
  };

  const cmp = keys => (a, b) => {
    for (const key of keys) {
      const [x, y] = [key(a), key(b)];
      if (x !== y) return x < y ? -1 : 1;
    }
    return 0;
  };
  const storeIx = i => {const ix = stores.indexOf(i.store); return ix < 0 ? stores.length : ix;};
  const aisleIx = i => {const ix = aislesFor(i.store).indexOf(i.aisle); return ix < 0 ? 999 : ix;};
  const catIx = i => {const ix = shop.item_categories.indexOf(i.category); return ix < 0 ? 999 : ix;};
  const order = sort === 'category' ? cmp([catIx, storeIx, aisleIx, i => i.position, i => i.id])
    : sort === 'added' ? cmp([i => -i.id])
    : cmp([storeIx, aisleIx, i => i.position, i => i.id]);

  const inStore = i => filterStore === 'all' || i.store === filterStore;
  const rows = (items || []).filter(inStore).sort(order);
  const boughtRows = bought.filter(inStore);
  const count = s => items ? ` (${items.filter(i => i.store === s).length})` : '';

  const meta = i => <span className="tasks-item-meta">
    <Select label={`Store for ${i.title}`} layout="hidden" variant="quiet" size="small" value={i.store}
      onValueChange={v => change(i, {store:v})} options={stores.map(s => [s, short(s)])}/>
    <Select label={`Aisle for ${i.title}`} layout="hidden" variant="quiet" size="small" value={i.aisle}
      onValueChange={v => change(i, {aisle:v})}
      options={[['', 'No aisle'], ...aislesFor(i.store).map(a => [a, a])]}/>
    <Select label={`Category for ${i.title}`} layout="hidden" variant="quiet" size="small" value={i.category}
      onValueChange={v => change(i, {category:v})} options={shop.item_categories.map(c => [c, c])}/>
  </span>;

  return <div className="tasks-stack tasks-shopping">
    <PageHeader title="Shopping" description="Tap an item to tick it off. Add several at once with commas."/>
    <div className="tasks-shopping-controls">
      <SegmentedControl size="small" label="Store" value={filterStore} onValueChange={chooseStore}
        options={[['all', `All${items ? ` (${items.length})` : ''}`], ...stores.map(s => [s, short(s) + count(s)])]}/>
      <Select label="Sort by" layout="hidden" variant="quiet" size="small" value={sort} onValueChange={chooseSort}
        options={SORTS.map(([v, l]) => [v, `Sort: ${l}`])}/>
    </div>
    <form className="tasks-quick-add" onSubmit={add}>
      <input ref={input} className="ds-text-input" aria-label="Add items" placeholder="Add items…"
        value={title} onChange={e => setTitle(e.target.value)} enterKeyHint="done"/>
      <Button size="small" variant="primary" type="submit" disabled={!title.trim()}>Add</Button>
    </form>
    <div className="tasks-add-meta">
      <Select label="Store for new items" layout="hidden" variant="quiet" size="small" value={addStore}
        onValueChange={pickAddStore} options={stores.map(s => [s, short(s)])}/>
      <Select label="Aisle for new items" layout="hidden" variant="quiet" size="small" value={addAisle}
        onValueChange={setAddAisle} options={[['', 'No aisle'], ...aislesFor(addStore).map(a => [a, a])]}/>
      <Select label="Category for new items" layout="hidden" variant="quiet" size="small" value={addCategory}
        onValueChange={setAddCategory} options={shop.item_categories.map(c => [c, c])}/>
    </div>
    {error && <Alert tone="warning">{error}</Alert>}
    {undo && <Alert tone="success" actions={<Button size="small" onClick={() => unbuy(undo)}>Undo</Button>}>Bought {undo.title}.</Alert>}
    {!items && !error && <Pending>Loading the list…</Pending>}
    {items && !rows.length && <EmptyState title={filterStore === 'all' ? 'Nothing to buy' : `Nothing to buy at ${short(filterStore)}`}
      description="Add something above or send it to the Telegram bot."/>}
    {rows.length > 0 && <section className="tasks-stack-tight">
      <ul className="tasks-items">{rows.map(i => <li key={i.id}>
        <button type="button" className="tasks-item" onClick={() => buy(i)} aria-label={`Bought ${i.title}`}>
          <span className="tasks-tick" aria-hidden="true"/><span><span className="tasks-item-title">{i.title}</span>
          {i.notes && <span className="tasks-muted"> · {i.notes}</span>}</span></button>
        <button type="button" className="tasks-item-remove" onClick={() => remove(i)} aria-label={`Remove ${i.title}`}>×</button>
        {meta(i)}
      </li>)}</ul></section>}
    {boughtRows.length > 0 && <section className="tasks-stack-tight">
      <Button size="small" variant="ghost" onClick={() => setShowBought(v => !v)} aria-expanded={showBought}>{showBought ? 'Hide' : 'Show'} recently bought ({boughtRows.length})</Button>
      {showBought && <ul className="tasks-items tasks-items-bought">{boughtRows.map(i => <li key={i.id}>
        <button type="button" className="tasks-item" onClick={() => unbuy(i)} aria-label={`Put ${i.title} back on the list`}>
          <span className="tasks-tick is-done" aria-hidden="true"/><span><span className="tasks-item-title">{i.title}</span>
          <span className="tasks-muted"> · {i.bought_by || 'someone'}, {i.bought_at.slice(5, 10)}</span></span></button>
      </li>)}</ul>}
    </section>}
  </div>;
}
