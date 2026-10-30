import React, {useEffect, useRef, useState} from 'react';
import {Alert, Button, Dialog, EmptyState, PageHeader, Select, TextField, toast} from '@doshi-experiments/design-system/react';
import {api, del, patch, post} from './api';
import {Pending} from './pending';
import {ItemPrice, PriceSummary, productText} from './prices';

// Built for one-handed use in a store: big tick targets, instant feedback,
// undo instead of confirmation. Refreshes every 30 s for items the bot adds.
// One flat list; every item carries a store, an aisle and a category, which
// the service works out from the title unless someone picks them. The filter
// shows one store (or all) under aisle headings; "New store…" adds a store.
const SHORT = {'Real Canadian Superstore': 'Superstore'};
const short = s => SHORT[s] || s;
const SORTS = [['store', 'Store & aisle'], ['category', 'Category'], ['added', 'Added']];
const NEW = '__new';
const NEW_STORE = [['Not listed?', [[NEW, 'New store…']]]];

const readSaved = (key, fallback) => {
  try {return localStorage.getItem(key) || fallback;} catch {return fallback;}
};
const save = (key, value) => {try {localStorage.setItem(key, value);} catch {/* private window */}};

// "At Home Depot, Garden Centre." for one item; "Superstore: milk, eggs. Home Depot: shrubs." for several.
const placed = items => {
  if (items.length === 1) return `At ${short(items[0].store)}${items[0].aisle ? `, ${items[0].aisle}` : ''}.`;
  const by = new Map();
  for (const i of items) by.set(i.store, [...(by.get(i.store) || []), i.title]);
  return [...by].map(([s, titles]) => `${short(s)}: ${titles.join(', ')}.`).join(' ');
};

export function ShoppingList({boot, me}) {
  const shop = boot.shopping;
  const aislesFor = store => shop.aisles[store] || shop.default_aisles;
  const [store, setStore] = useState(() => readSaved('tasks-shopping-store', shop.defaults.store));
  const [sort, setSort] = useState(() => readSaved('tasks-shopping-sort', 'store'));
  const [items, setItems] = useState(null), [bought, setBought] = useState([]), [error, setError] = useState('');
  const [known, setKnown] = useState(shop.stores);
  const [title, setTitle] = useState(''), [undo, setUndo] = useState(null), [showBought, setShowBought] = useState(false);
  // '' leaves the store, category and aisle to the service (from the title)
  const [addStore, setAddStore] = useState(''), [addCategory, setAddCategory] = useState(''), [addAisle, setAddAisle] = useState('');
  const [asking, setAsking] = useState(null), [storeName, setStoreName] = useState('');
  const [prices, setPrices] = useState(null);
  const input = useRef(null);

  // Every store we know of, plus any a just-added item carries before the
  // next refresh of the store list catches up.
  const stores = [...known];
  for (const i of [...(items || []), ...bought]) if (!stores.includes(i.store)) stores.push(i.store);
  const filterStore = store !== 'all' && !stores.includes(store) ? shop.defaults.store : store;

  const load = async () => {
    try {
      const [open, done, s, p] = await Promise.all([api('shopping'), api('shopping?bought=1'), api('shopping/stores'),
        boot.prices?.enabled ? api('prices') : null]);
      setItems(open.items); setBought(done.items.slice(0, 30)); setKnown(s.stores); setPrices(p); setError('');
    } catch (e) {setError(e.message);}
  };
  // While a price check runs, look again every 10 s so the new prices show when it's done.
  useEffect(() => {
    if (!prices?.running) return undefined;
    const timer = setTimeout(load, 10000);
    return () => clearTimeout(timer);
  }, [prices]);
  const checkPrices = async () => {
    try {
      const r = await post('prices/refresh');
      toast('Checking prices', r.products ? `About ${Math.max(1, Math.round(r.eta_seconds / 60))} min for ${r.products} products.` : 'Nothing on the list is matched to a product yet.');
      setPrices(p => ({...p, running:!!r.products}));
    } catch (e) {toast('Prices not checked', e.message, {tone:'warning'});}
  };
  const move = (item, store) => change(item, {store});
  useEffect(() => {
    load();
    const timer = setInterval(() => {if (document.visibilityState === 'visible') load();}, 30000);
    const onShow = () => {if (document.visibilityState === 'visible') load();};
    document.addEventListener('visibilitychange', onShow);
    return () => {clearInterval(timer); document.removeEventListener('visibilitychange', onShow);};
  }, []);

  const chooseStore = s => {setStore(s); setUndo(null); save('tasks-shopping-store', s);};
  const chooseSort = s => {setSort(s); save('tasks-shopping-sort', s);};
  const pickAddStore = s => {setAddStore(s); setAddAisle('');};
  // A store picker's "New store…" asks for the name, then carries on as if it had been picked.
  const orNew = then => v => {if (v === NEW) {setStoreName(''); setAsking(() => then);} else then(v);};
  const makeStore = async e => {
    e?.preventDefault();
    const name = storeName.trim();
    if (!name) return;
    try {
      const r = await post('shopping/stores', {name});
      setKnown(r.stores); setAsking(null); asking(r.store);
    } catch (err) {setError(err.message); setAsking(null);}
  };

  const add = async e => {
    e.preventDefault();
    const text = title.trim();
    if (!text) return;
    setTitle('');
    try {
      const r = await post('shopping', {items:text.split(/\s*,\s*/).filter(Boolean).map(t => ({
        title:t, store:addStore, category:addCategory, aisle:addAisle, added_by:me, source:'web'}))});
      const dup = r.items.filter(i => i.duplicate).map(i => i.title), fresh = r.items.filter(i => !i.duplicate);
      setError(dup.length ? `Already on the list: ${dup.join(', ')}` : '');
      if (fresh.length) toast(`Added: ${fresh.map(i => i.product ? `${i.title} (${i.product.label})` : i.title).join(', ')}`, placed(fresh));
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
  // Headings follow the sort: aisles (with their store when showing all), categories, or none.
  const heading = sort === 'category' ? i => i.category
    : sort === 'added' ? () => ''
    : i => [filterStore === 'all' && short(i.store), i.aisle || 'No aisle'].filter(Boolean).join(' · ');

  const inStore = i => filterStore === 'all' || i.store === filterStore;
  const rows = (items || []).filter(inStore).sort(order);
  const groups = [];
  for (const i of rows) {
    const key = heading(i);
    if (groups.at(-1)?.key === key) groups.at(-1).items.push(i); else groups.push({key, items:[i]});
  }
  const boughtRows = bought.filter(inStore);
  const count = s => items ? ` (${items.filter(i => i.store === s).length})` : '';
  const storeOptions = stores.map(s => [s, short(s)]);

  const meta = i => <span className="tasks-item-meta">
    <Select label={`Store for ${i.title}`} layout="hidden" variant="quiet" size="small" value={i.store}
      onValueChange={orNew(v => change(i, {store:v}))} options={storeOptions} groups={NEW_STORE}/>
    <Select label={`Aisle for ${i.title}`} layout="hidden" variant="quiet" size="small" value={i.aisle}
      onValueChange={v => change(i, {aisle:v})}
      options={[['', 'No aisle'], ...aislesFor(i.store).map(a => [a, a])]}/>
    <Select label={`Category for ${i.title}`} layout="hidden" variant="quiet" size="small" value={i.category}
      onValueChange={v => change(i, {category:v})} options={shop.item_categories.map(c => [c, c])}/>
  </span>;

  return <div className="tasks-stack tasks-shopping">
    <PageHeader title="Shopping" description="Tap an item to tick it off. Add several at once with commas."/>
    <div className="tasks-shopping-controls">
      <Select label="Store" layout="hidden" size="small" value={filterStore} onValueChange={orNew(chooseStore)}
        options={[['all', `All stores${items ? ` (${items.length})` : ''}`], ...stores.map(s => [s, short(s) + count(s)])]}
        groups={NEW_STORE}/>
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
        onValueChange={orNew(pickAddStore)} options={[['', 'Auto store'], ...storeOptions]} groups={NEW_STORE}/>
      {addStore && <Select label="Aisle for new items" layout="hidden" variant="quiet" size="small" value={addAisle}
        onValueChange={setAddAisle} options={[['', 'Auto aisle'], ...aislesFor(addStore).map(a => [a, a])]}/>}
      <Select label="Category for new items" layout="hidden" variant="quiet" size="small" value={addCategory}
        onValueChange={setAddCategory} options={[['', 'Auto category'], ...shop.item_categories.map(c => [c, c])]}/>
    </div>
    {error && <Alert tone="warning">{error}</Alert>}
    <PriceSummary prices={prices} onCheck={checkPrices}/>
    {undo && <Alert tone="success" actions={<Button size="small" onClick={() => unbuy(undo)}>Undo</Button>}>Bought {undo.title}.</Alert>}
    {!items && !error && <Pending>Loading the list…</Pending>}
    {items && !rows.length && <EmptyState title={filterStore === 'all' ? 'Nothing to buy' : `Nothing to buy at ${short(filterStore)}`}
      description="Add something above or send it to the Telegram bot."/>}
    {rows.length > 0 && <div className="tasks-stack-tight">{groups.map(g => <section key={g.key} className="tasks-aisle">
      {g.key && <h2 className="ds-eyebrow">{g.key}</h2>}
      <ul className="tasks-items">{g.items.map(i => <li key={i.id}>
        <button type="button" className="tasks-item" onClick={() => buy(i)} aria-label={`Bought ${i.title}`}>
          <span className="tasks-tick" aria-hidden="true"/><span><span className="tasks-item-title">{i.title}</span>
          {i.notes && <span className="tasks-muted"> · {i.notes}</span>}
          {i.product && <span className="tasks-item-product">{productText(i.product)}</span>}</span></button>
        <button type="button" className="tasks-item-remove" onClick={() => remove(i)} aria-label={`Remove ${i.title}`}>×</button>
        <ItemPrice item={i} quote={prices?.items?.[i.id]} onMove={move}/>
        {meta(i)}
      </li>)}</ul></section>)}</div>}
    {boughtRows.length > 0 && <section className="tasks-stack-tight">
      <Button size="small" variant="ghost" onClick={() => setShowBought(v => !v)} aria-expanded={showBought}>{showBought ? 'Hide' : 'Show'} recently bought ({boughtRows.length})</Button>
      {showBought && <ul className="tasks-items tasks-items-bought">{boughtRows.map(i => <li key={i.id}>
        <button type="button" className="tasks-item" onClick={() => unbuy(i)} aria-label={`Put ${i.title} back on the list`}>
          <span className="tasks-tick is-done" aria-hidden="true"/><span><span className="tasks-item-title">{i.title}</span>
          <span className="tasks-muted"> · {i.bought_by || 'someone'}, {i.bought_at.slice(5, 10)}</span></span></button>
      </li>)}</ul>}
    </section>}
    <Dialog open={!!asking} onOpenChange={open => {if (!open) setAsking(null);}} title="New store"
      description="It joins every store picker, with a general set of aisles."
      actions={<Button size="small" variant="primary" disabled={!storeName.trim()} onClick={makeStore}>Add store</Button>}>
      <form onSubmit={makeStore}><TextField label="Store name" value={storeName} onValueChange={setStoreName} autoFocus/></form>
    </Dialog>
  </div>;
}
