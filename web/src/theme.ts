export type Theme = "dark" | "light";
const KEY = "lz.theme";
const isTheme = (v: unknown): v is Theme => v === "dark" || v === "light";
/** The saved choice, else the system preference. Both are the user's own setting, not a guess about content. */
export function initialTheme(): Theme {
  const saved = localStorage.getItem(KEY);
  if (isTheme(saved)) return saved;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}
export function applyTheme(t: Theme): void {
  document.documentElement.dataset.theme = t;
  localStorage.setItem(KEY, t);
}
