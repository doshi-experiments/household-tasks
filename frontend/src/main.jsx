import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Alert, AppearanceControl, Button} from '@doshi-experiments/design-system/react';
import {createAppearanceController} from '@doshi-experiments/design-system/theme';
import '@doshi-experiments/design-system/tokens.css';
import '@doshi-experiments/design-system/components.css';
import './tasks.css';
import {useResource} from './hooks';
import {Pending} from './pending';
import {TasksPage} from './tasks';
import {HomelabPage} from './homelab';
import {TaskForm} from './task-form';
import {ShoppingList} from './shopping';
import {History} from './history';
import {Celebration} from './celebrate';
import {useMe} from './me';

const theme = createAppearanceController({storageKey:'tasks-appearance', cookie:false});
const paintThemeColor = () => document.querySelector('meta[name="theme-color"]')?.setAttribute('content', getComputedStyle(document.documentElement).getPropertyValue('--ds-surface-page').trim());
paintThemeColor();

const TABS = [['one-off', 'One-off'], ['recurring', 'Recurring'], ['homelab', 'Homelab'], ['shopping', 'Shopping'], ['history', 'History']];

function App() {
  const [route, setRoute] = useState(location.hash || '#/one-off');
  const [appearance, setAppearance] = useState(theme.getPreference());
  const [me, setMe] = useMe();
  useEffect(() => theme.subscribe(({preference}) => {setAppearance(preference); paintThemeColor();}), []);
  useEffect(() => {
    const change = () => {setRoute(location.hash || '#/one-off'); document.getElementById('main-content')?.focus({preventScroll:true}); window.scrollTo(0, 0);};
    addEventListener('hashchange', change); return () => removeEventListener('hashchange', change);
  }, []);
  const boot = useResource('bootstrap');
  const [rawPath, query = ''] = route.replace(/^#\//, '').split('?');
  const [path, id] = rawPath.split('/');
  const page = ['one-off', 'recurring', 'homelab', 'task', 'shopping', 'history'].includes(path) ? path : 'one-off';
  // a task page keeps the tab it came from lit
  const from = new URLSearchParams(query).get('from') || 'one-off';
  const current = page === 'task' ? from : page;
  return <div className="tasks-app">
    <header className="tasks-top">
      <a className="tasks-brand" href="#/one-off">Household tasks</a>
      <div className="tasks-top-controls">
        {boot.data && <label className="tasks-me">
          <span>I am</span>
          <select className="ds-select-input" value={me} onChange={e => setMe(e.target.value)}>
            <option value="">Choose…</option>
            {boot.data.people.map(p => <option key={p.id} value={p.name}>{p.name}</option>)}
          </select>
        </label>}
        <AppearanceControl value={appearance} onValueChange={value => theme.setPreference(value)}/>
      </div>
    </header>
    <nav className="ds-tabs tasks-tabs" aria-label="Sections">
      {TABS.map(([key, label]) => <a key={key} className="ds-tab" href={`#/${key}`} aria-current={current === key ? 'page' : undefined}>{label}</a>)}
    </nav>
    <main id="main-content" className="tasks-main" tabIndex={-1}>
      {boot.error && <Alert tone="error" title="Couldn’t reach Tasks" actions={<Button onClick={boot.reload}>Try again</Button>}>{boot.error}</Alert>}
      {boot.loading && !boot.data && <Pending>Loading…</Pending>}
      {boot.data && <>
        {!me && page !== 'history' && <Alert tone="info">Choose who you are under “I am” so what you tick off shows your name.</Alert>}
        {(page === 'one-off' || page === 'recurring') && <TasksPage key={page} kind={page} boot={boot.data} me={me}/>}
        {page === 'homelab' && <HomelabPage boot={boot.data} me={me}/>}
        {page === 'task' && <TaskForm key={id} id={id === 'new' ? null : Number(id)} from={from} boot={boot.data} me={me}/>}
        {page === 'shopping' && <ShoppingList boot={boot.data} me={me}/>}
        {page === 'history' && <History/>}
      </>}
    </main>
    <Celebration/>
  </div>;
}

class ErrorBoundary extends React.Component {
  state = {error:false};
  static getDerivedStateFromError() {return {error:true};}
  render() {return this.state.error ? <main className="tasks-fallback"><Alert tone="error" title="This page couldn’t be shown">Your tasks are safe. Reload to try again.</Alert><Button onClick={() => location.reload()}>Reload</Button></main> : this.props.children;}
}
createRoot(document.getElementById('root')).render(<ErrorBoundary><App/></ErrorBoundary>);
