import * as T from "@radix-ui/react-tabs";

// Tabs with the keyboard handled (arrow keys, Home, End). `segmented` is the grey-track style used to switch
// between accounts; the default is the underlined style used inside a card.
export const Tabs = T.Root;
export function TabList({ label, segmented = false, children }) {
  return <T.List aria-label={label} className={segmented ? "tabs tabs-segmented" : "tabs"}>{children}</T.List>;
}
export function Tab({ value, children, ...rest }) {
  return <T.Trigger value={value} className="tab" {...rest}>{children}</T.Trigger>;
}
export function TabPanel({ value, children, className = "", forceMount = false, animate = true }) {
  return <T.Content value={value} forceMount={forceMount || undefined} className={`tab-panel${animate ? " animate-fade-in" : ""} ${className}`.trim()}>{children}</T.Content>;
}
