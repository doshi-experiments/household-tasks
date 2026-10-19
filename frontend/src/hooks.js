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
export function useAction() {
  const [pending, setPending] = useState(null), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const lock = useRef(false);
  const run = async (fn, key = 'action') => {
    if (lock.current) return;
    lock.current = true; setPending(key); setError(''); setNotice('');
    try {return await fn();} catch (e) {setError(e.message);} finally {lock.current = false; setPending(null);}
  };
  return {busy:pending !== null, pending, error, notice, setError, setNotice, run};
}
