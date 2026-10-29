/** Whether a design item came straight from the SOW or was inferred by the agent. */
export function BasisBadge({ basis }: { basis?: string }) {
  if (!basis) return null;
  const explicit = basis === "explicit";
  return <span className={`badge ${explicit ? "badge-green" : "badge-amber"}`} title={explicit ? "Stated in the SOW" : "Inferred by the agent; confirm with the customer"}>{explicit ? "From SOW" : basis === "inferred" ? "Inferred" : basis}</span>;
}
