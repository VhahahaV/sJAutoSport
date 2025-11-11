export const czqDebugStart = (label: string): number => {
  const now = performance.now();
  console.log(`#CZQ_DEBUG ${label} start ${now.toFixed(1)}ms`);
  return now;
};

export const czqDebugEnd = (label: string, start: number): number => {
  const now = performance.now();
  const elapsed = now - start;
  console.log(`#CZQ_DEBUG ${label} ${elapsed.toFixed(1)}ms`);
  return now;
};

export const czqDebugLog = (label: string): void => {
  const now = performance.now();
  console.log(`#CZQ_DEBUG ${label} ${now.toFixed(1)}ms`);
};
