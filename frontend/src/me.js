import {useState} from 'react';

// Who's using this browser, remembered locally; storage can be unavailable.
const KEY = 'tasks-me';
const read = () => {try {return localStorage.getItem(KEY) || '';} catch {return '';}};
export function useMe() {
  const [me, setMe] = useState(read);
  const update = value => {setMe(value); try {localStorage.setItem(KEY, value);} catch {/* private window */}};
  return [me, update];
}
