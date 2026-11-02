import { useId, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Command } from "cmdk";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { portalContainer } from "@/features/architecture-design/adapters/portal.js";

// Choose one of a list: a button that opens a search box over the list, below the button (the browser's own select list opens over the select and
// hides it). The keyboard drives it: type to narrow the list, arrows to move, Enter to choose, Escape to close. Options can sit under group headings
// and carry a second line. (The unified dashboard's SearchableSelect, in plain JSX and CSS.)
//   options: [{ value, label, description?, group?, keywords? }]    value: the chosen option's value, or "" for none
//   label: what it chooses (read out; shown above unless hideLabel)    mono: set the labels in the code face, for ids

/** Whether every word typed appears somewhere in the text. Plain substrings, so the result is easy to predict. */
export const matchesSearch = (search, text) => {
  const haystack = text.toLowerCase();
  return search.toLowerCase().split(/\s+/).filter(Boolean).every((word) => haystack.includes(word));
};
// Matching items all score the same, so the list keeps the order it was given.
const filter = (value, search, keywords) => (matchesSearch(search, [value, ...(keywords ?? [])].join(" ")) ? 1 : 0);

export default function SearchableSelect({ id, label, hideLabel = false, value, options, onChange, placeholder = "Choose", searchPlaceholder = "Search", emptyText = "Nothing matches that.", mono = false, disabled = false, title, className = "" }) {
  const [open, setOpen] = useState(false);
  const labelId = useId(), valueId = useId(), popupId = useId();
  const selected = options.find((o) => o.value === value);
  const groups = options.reduce((found, o) => {
    const g = found.find((x) => x.heading === o.group);
    if (g) g.items.push(o); else found.push({ heading: o.group, items: [o] });
    return found;
  }, []);
  const choose = (next) => { onChange(next); setOpen(false); };

  return (
    <div className={`ss ${className}`.trim()}>
      <span id={labelId} className={hideLabel ? "sr-only" : "ss-label"}>{label}</span>
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button type="button" id={id} role="combobox" className="ss-trigger" aria-labelledby={`${labelId} ${valueId}`} aria-haspopup="listbox" aria-expanded={open}
            aria-controls={popupId} disabled={disabled} title={title ?? selected?.label}
            onKeyDown={(e) => { if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); setOpen(true); } }}>
            <span id={valueId} className="ss-value">
              {selected ? <span className={`ss-value-text${mono ? " mono" : ""}`}>{selected.label}</span> : <span className="ss-value-text ss-placeholder">{placeholder}</span>}
            </span>
            <ChevronsUpDown size={16} className="ss-chevron" aria-hidden />
          </button>
        </Popover.Trigger>
        <Popover.Portal container={portalContainer()}>
          <Popover.Content id={popupId} aria-label={label} align="start" sideOffset={4} collisionPadding={12} className="ss-popup">
            {/* The search box takes the keys when it opens; the list is only chosen from by them. */}
            <Command loop label={`Search ${label.toLowerCase()}`} filter={filter} defaultValue={selected?.value}>
              <div className="ss-search">
                <Search size={16} aria-hidden />
                <Command.Input placeholder={searchPlaceholder} />
              </div>
              <Command.List className="ss-list">
                <Command.Empty className="ss-empty">{emptyText}</Command.Empty>
                {groups.map((g) => {
                  const items = g.items.map((o) => (
                    <Command.Item key={o.value} value={o.value} keywords={[o.label, o.description ?? "", o.group ?? "", ...(o.keywords ?? [])]} onSelect={() => choose(o.value)} className="ss-item">
                      <span className="ss-item-main">
                        <span className={`ss-item-label${mono ? " mono" : ""}`}>{o.label}</span>
                        {o.description ? <span className="ss-item-desc">{o.description}</span> : null}
                      </span>
                      {o.value === value ? <Check size={16} className="ss-check" aria-hidden /> : null}
                    </Command.Item>
                  ));
                  return g.heading ? <Command.Group key={g.heading} heading={g.heading}>{items}</Command.Group> : items;
                })}
              </Command.List>
            </Command>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
