// tone: success | warning | danger | info | muted
export function Badge({ tone = "muted", icon: Icon, children, className = "", ...rest }) {
  return (
    <span className={`badge badge-${tone} ${className}`.trim()} {...rest}>
      {Icon ? <Icon size={12} aria-hidden /> : null}
      {children}
    </span>
  );
}
