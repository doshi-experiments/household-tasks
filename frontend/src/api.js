const base = new URL('./', document.baseURI);
export async function api(path, {method = 'GET', body, signal} = {}) {
  const multipart = body instanceof FormData;
  let response;
  try {
    response = await fetch(new URL(`api/${path}`, base), {
      method, signal, credentials:'same-origin', headers:{'X-Tasks-Request':'1', ...(!multipart && body !== undefined ? {'Content-Type':'application/json'} : {})},
      body:body === undefined ? undefined : multipart ? body : JSON.stringify(body),
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error(method === 'GET' ? 'Connection lost. Try loading this page again.' : 'Connection lost while saving. Reload to check whether it was saved.');
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    const error = new Error(typeof detail === 'string' ? detail : detail?.message || payload?.message || `Request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return payload;
}
export const post = (path, body = {}) => api(path, {method:'POST', body});
export const patch = (path, body = {}) => api(path, {method:'PATCH', body});
export const del = path => api(path, {method:'DELETE'});
