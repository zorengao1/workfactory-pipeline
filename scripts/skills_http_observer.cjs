// Observe official CLI requests without changing the search algorithm or endpoints.
const original = globalThis.fetch;
globalThis.fetch = async (...args) => {
  const observed = String(args[0]).includes('/api/search?');
  try {
    const response = await original(...args);
    if (observed) {
      const data = await response.clone().json().catch(() => ({}));
      console.error('WF_SEARCH ' + JSON.stringify({
        status: response.status,
        valid_payload: Array.isArray(data.skills),
        retry_after: Number(response.headers.get('retry-after')) || 0,
        skills: Array.isArray(data.skills) ? data.skills : [],
        searchType: data.searchType
      }));
    }
    return response;
  } catch (error) {
    if (observed) console.error('WF_SEARCH ' + JSON.stringify({status: null, error: error.message}));
    throw error;
  }
};
