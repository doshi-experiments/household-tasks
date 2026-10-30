import React from 'react';
import {Alert, Badge, Button} from '@doshi-experiments/design-system/react';

// Loblaw prices on the Shopping tab (app/prices.py): one line under each priced
// item, and a summary above the list. Nothing here shows unless prices are on
// and something on the list is matched to a product.
export const money = cents => `$${(cents / 100).toFixed(2)}`;
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const weekday = day => (day ? DAYS[new Date(`${day}T12:00:00`).getDay()] : '');
const unitPrice = q => (q.unit_cents == null || !q.unit ? ''
  : `${money(q.unit_cents)}/${q.unit_qty && q.unit_qty !== 1 ? `${q.unit_qty} ` : ''}${q.unit}`);

// "Natrel 2%, 4 l": what the household calls it, plus the matched size. A product
// Tasks picked itself says so; naming one on Telegram replaces it.
export const productText = p => (p.auto ? 'Picked: ' : '') + [p.label, p.linked && p.size].filter(Boolean).join(', ');

function DealBadge({q}) {
  if (q.deal?.multibuy) return <Badge tone="info">{q.deal.multibuy}</Badge>;
  if (q.on_sale) return <Badge tone="success">{q.sale_ends ? `Sale to ${weekday(q.sale_ends)}` : 'Sale'}</Badge>;
  if (q.points) return <Badge tone="info">{q.points.points.toLocaleString()} pts</Badge>;
  return null;
}

export function ItemPrice({item, quote, onMove}) {
  if (!quote) return null;
  const [cheapest] = quote.stores;
  return <div className="tasks-item-price">
    {quote.stores.map(q => <span key={q.banner} className="tasks-item-store-price">
      {q.short} {money(q.price_cents)}{q === cheapest && unitPrice(q) && <span className="tasks-muted"> ({unitPrice(q)})</span>}
      {' '}<DealBadge q={q}/>
    </span>)}
    {quote.move_to && <>
      <span>Save {money(quote.saving_cents)} at {cheapest.short}</span>
      <Button size="small" variant="ghost" onClick={() => onMove(item, quote.move_to)}
        aria-label={`Move ${item.title} to ${cheapest.short}`}>Move</Button>
    </>}
  </div>;
}

const checkedText = iso => {
  if (!iso) return 'Not checked yet';
  const d = new Date(iso);
  return `Checked ${d.toLocaleString(undefined, {weekday:'short', hour:'numeric', minute:'2-digit'})}`;
};

export function PriceSummary({prices, onCheck}) {
  if (!prices?.enabled) return null;
  const blocked = prices.status?.blocked;
  const failing = prices.stores.filter(s => prices.status?.stores?.[s.banner]?.ok === false);
  if (!prices.priced && !blocked) return null;
  const everywhere = prices.stores.length === 2 ? 'at both stores' : 'at every store';
  return <section className="tasks-prices" aria-label="Prices">
    {blocked && <Alert tone="warning" title="Prices paused">
      Loblaw refused the last check ({blocked.why}). The prices below may be old.</Alert>}
    {!blocked && failing.length > 0 && <Alert tone="warning">
      {failing.map(s => s.short).join(' and ')} didn't answer the last check.</Alert>}
    {prices.priced > 0 && <p>Priced {prices.priced} of {prices.pricable} {prices.pricable === 1 ? 'item' : 'items'}.
      {prices.complete > 0 && <> For the {prices.complete} priced {everywhere}: {prices.stores.filter(s => s.banner in prices.totals)
        .map(s => `${s.short} ${money(prices.totals[s.banner])}`).join(', ')}.</>}</p>}
    {prices.split_saving_cents > 0 && <p><strong>Split the trip: save {money(prices.split_saving_cents)}</strong> by buying each item where it's cheapest.</p>}
    <div className="tasks-prices-check">
      <span className="tasks-muted">{prices.running ? 'Checking prices…' : checkedText(prices.last_refresh)}</span>
      <Button size="small" variant="ghost" disabled={prices.running} onClick={onCheck}>Check prices</Button>
    </div>
  </section>;
}
