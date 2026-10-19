import React from 'react';
import {Alert, DataTable, EmptyState, PageHeader} from '@doshi-experiments/design-system/react';
import {useResource} from './hooks';
import {Pending} from './pending';

export function History() {
  const h = useResource('history?limit=200');
  return <div className="tasks-stack">
    <PageHeader title="History" description="What was done or skipped, by whom and from where."/>
    {h.error && <Alert tone="error">{h.error}</Alert>}
    {h.loading && !h.data && <Pending>Loading…</Pending>}
    {h.data && (!h.data.completions.length ? <EmptyState title="Nothing done yet"/> : <DataTable aria-label="History">
      <thead><tr><th>When</th><th>Task</th><th>What</th><th>Who</th><th>Via</th></tr></thead>
      <tbody>{h.data.completions.map(c => <tr key={c.id}>
        <td className="tasks-nowrap">{c.done_at.slice(0, 16).replace('T', ' ')}</td>
        <td><a href={`#/task/${c.task_id}`}>{c.title}</a></td>
        <td>{c.kind === 'done' ? 'Done' : 'Skipped'}{c.nominal_due ? ` (due ${c.nominal_due})` : ''}</td>
        <td>{c.done_by || '—'}</td><td>{c.source}</td></tr>)}</tbody>
    </DataTable>)}
  </div>;
}
