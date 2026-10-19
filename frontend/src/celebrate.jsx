import React, {useEffect, useState} from 'react';

// A small, random dog moment when something is marked done: paw prints
// trotting across, a dog popping up with a wagging tail, or a burst of felt
// hearts and bones from the button that was pressed. Never blocks the page
// (pointer-events: none), always under 2 s, and a plain fade with reduced motion.
const KINDS = ['paws', 'dog', 'burst'];
let last = '';

export function celebrate(event) {
  const r = event?.currentTarget?.getBoundingClientRect?.();
  const origin = r ? {x:r.left + r.width / 2, y:r.top + r.height / 2} : {x:innerWidth / 2, y:innerHeight * 0.6};
  const choices = KINDS.filter(k => k !== last);   // never the same one twice in a row
  last = choices[Math.floor(Math.random() * choices.length)];
  dispatchEvent(new CustomEvent('tasks:celebrate', {detail:{kind:last, origin, key:Date.now()}}));
}

const Paw = props => <svg viewBox="0 0 40 40" aria-hidden="true" {...props}>
  <ellipse cx="20" cy="27" rx="9" ry="7.5"/><ellipse cx="9" cy="16" rx="4" ry="5"/><ellipse cx="16" cy="9" rx="4" ry="5.2"/>
  <ellipse cx="24" cy="9" rx="4" ry="5.2"/><ellipse cx="31" cy="16" rx="4" ry="5"/>
</svg>;
const Heart = props => <svg viewBox="0 0 32 32" aria-hidden="true" {...props}><path d="M16 28S3 20.5 3 11.5A6.5 6.5 0 0 1 16 8.4 6.5 6.5 0 0 1 29 11.5C29 20.5 16 28 16 28Z"/></svg>;
const Bone = props => <svg viewBox="0 0 40 20" aria-hidden="true" {...props}>
  <rect x="8" y="6.5" width="24" height="7" rx="3.5"/><circle cx="7" cy="6.5" r="4.5"/><circle cx="7" cy="13.5" r="4.5"/>
  <circle cx="33" cy="6.5" r="4.5"/><circle cx="33" cy="13.5" r="4.5"/>
</svg>;
const Dog = () => <svg viewBox="0 0 160 150" aria-hidden="true" className="tasks-dog">
  <g className="tasks-dog-tail"><path d="M128 112c14-4 22-18 20-32" fill="none" strokeWidth="10" strokeLinecap="round"/></g>
  <path className="tasks-dog-body" d="M34 150c0-36 20-58 46-58s46 22 46 58Z"/>
  <path className="tasks-dog-ear" d="M38 38c-14 6-22 30-14 48 10 0 18-12 22-28Z"/>
  <path className="tasks-dog-ear" d="M122 38c14 6 22 30 14 48-10 0-18-12-22-28Z"/>
  <ellipse className="tasks-dog-head" cx="80" cy="58" rx="44" ry="40"/>
  <ellipse className="tasks-dog-muzzle" cx="80" cy="76" rx="22" ry="16"/>
  <circle className="tasks-dog-eye" cx="62" cy="52" r="5"/><circle className="tasks-dog-eye" cx="98" cy="52" r="5"/>
  <circle className="tasks-dog-shine" cx="64" cy="50" r="1.6"/><circle className="tasks-dog-shine" cx="100" cy="50" r="1.6"/>
  <ellipse className="tasks-dog-nose" cx="80" cy="69" rx="7" ry="5"/>
  <path className="tasks-dog-tongue" d="M74 82c0 10 12 10 12 0Z"/>
</svg>;

export function Celebration() {
  const [shown, setShown] = useState(null);
  useEffect(() => {
    const on = e => setShown(e.detail);
    addEventListener('tasks:celebrate', on);
    return () => removeEventListener('tasks:celebrate', on);
  }, []);
  useEffect(() => {
    if (!shown) return;
    const t = setTimeout(() => setShown(null), 2200);
    return () => clearTimeout(t);
  }, [shown]);
  return <>
    <p className="ds-visually-hidden" role="status">{shown ? 'Done. Nice work.' : ''}</p>
    {shown && <div key={shown.key} className={`tasks-celebrate tasks-celebrate-${shown.kind}`} aria-hidden="true"
      style={{'--x':`${shown.origin.x}px`, '--y':`${shown.origin.y}px`}}>
      {shown.kind === 'paws' && Array.from({length:8}, (_, i) =>
        <Paw key={i} className="tasks-paw" style={{'--i':i, left:`${6 + i * 11.5}%`, bottom:`${12 + (i % 2) * 7 + i * 2}%`}}/>)}
      {shown.kind === 'dog' && <Dog/>}
      {shown.kind === 'burst' && Array.from({length:12}, (_, i) => {
        const angle = (i / 12) * Math.PI * 2 + 0.3;
        const dist = 90 + (i % 3) * 30;
        const Shape = i % 3 === 0 ? Bone : Heart;
        return <Shape key={i} className="tasks-bit" style={{'--dx':`${Math.cos(angle) * dist}px`, '--dy':`${Math.sin(angle) * dist - 40}px`, '--r':`${(i * 47) % 90 - 45}deg`, '--i':i}}/>;
      })}
    </div>}
  </>;
}
