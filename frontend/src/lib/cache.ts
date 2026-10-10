// Answers kept between visits to a page (as cache.screener in web/app.js),
// dropped after a trade or a watchlist change (SiftUI.invalidate()).
const store = new Map<string, unknown>();
export const cached = <T>(key: string): T | undefined => store.get(key) as T | undefined;
export const keep = <T>(key: string, value: T): T => { store.set(key, value); return value; };
export const invalidate = (): void => store.clear();
