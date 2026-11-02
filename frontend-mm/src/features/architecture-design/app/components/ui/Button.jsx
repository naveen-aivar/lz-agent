import { LoaderCircle } from "lucide-react";

// The portal's buttons: pill-shaped, blue for the main action, outlined for the rest.
// `loading` shows a spinner and blocks clicks while an action is on its way.
export function Button({ variant = "primary", size = "md", loading = false, className = "", children, type = "button", ...rest }) {
  return (
    <button type={type} className={`btn btn-${variant} btn-${size} ${className}`.trim()} {...rest}
      disabled={loading || rest.disabled} aria-busy={loading || undefined}>
      {loading ? <LoaderCircle className="spin" size={16} aria-hidden /> : null}
      {children}
    </button>
  );
}

// A link that looks like a button.
export function ButtonLink({ variant = "primary", size = "md", className = "", children, ...rest }) {
  return <a className={`btn btn-${variant} btn-${size} ${className}`.trim()} {...rest}>{children}</a>;
}
