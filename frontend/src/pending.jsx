import React, {useEffect, useState} from 'react';

// A visible "working on it" line for waits with no progress to report.
export function Pending({children, slow = 'Still working. This can take a minute.'}) {
  const [late, setLate] = useState(false);
  useEffect(() => {const timer = setTimeout(() => setLate(true), 8000); return () => clearTimeout(timer);}, []);
  return <p role="status" className="tasks-pending"><span>{children}{late && slow ? ` ${slow}` : ''}</span></p>;
}
