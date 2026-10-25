import {useCallback, useEffect, useRef, useState} from 'react';
import {api} from './api';
export function useResource(path) {
  const [state, setState] = useState({data:null, error:'', loading:true});
  const generation = useRef(0);
  const reload = useCallback(async () => {
    const current = ++generation.current;
    setState(old => ({...old, loading:true, error:''}));
    try {const data = await api(path); if (current === generation.current) setState({data, loading:false, error:''}); return data;}
    catch (error) {if (current === generation.current) setState(old => ({...old, loading:false, error:error.message}));}
  }, [path]);
  useEffect(() => {reload(); return () => {generation.current++;};}, [reload]);
  return {...state, reload};
}
// One mutation per view at a time; never retry a write automatically.
// `key` names the control that started it: that control shows it's working
// (loading={action.pending===key}) while the rest of the view only locks.
// Confirmations are toasts; errors stay on the page.
export function useAction() {
  const [pending, setPending] = useState(null), [error, setError] = useState('');
  const lock = useRef(false);
  const run = async (fn, key = 'action') => {
    if (lock.current) return;
    lock.current = true; setPending(key); setError('');
    try {return await fn();} catch (e) {setError(e.message);} finally {lock.current = false; setPending(null);}
  };
  return {busy:pending !== null, pending, error, setError, run};
}
// A toast's Undo changes tasks behind the page's back: views that show them reload.
export const changed = () => dispatchEvent(new CustomEvent('tasks:changed'));
export function useOnChange(fn) {
  const latest = useRef(fn);
  latest.current = fn;
  useEffect(() => {
    const on = () => latest.current();
    addEventListener('tasks:changed', on); return () => removeEventListener('tasks:changed', on);
  }, []);
}
export function useMedia(query) {
  const [matches, setMatches] = useState(() => matchMedia(query).matches);
  useEffect(() => {
    const list = matchMedia(query), on = () => setMatches(list.matches);
    on(); list.addEventListener('change', on); return () => list.removeEventListener('change', on);
  }, [query]);
  return matches;
}
