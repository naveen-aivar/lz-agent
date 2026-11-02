import { Toaster as Sonner, toast } from "sonner";

// Messages that say something just happened are toasts at the top right (the unified dashboard's Sonner toaster, coloured
// from the tokens). success (done), warning (it worked but is incomplete) or danger (it failed). A repeat with the same
// title replaces the one on screen instead of stacking. One follow-up button is allowed ({ label, onClick }).
const SHORT_MS = 4000;
const LONG_MS = 9000;

export function showToast({ title, description, variant = "success", action }) {
  const opts = { id: title, description, duration: variant === "success" && !action ? SHORT_MS : LONG_MS, action };
  if (variant === "danger") toast.error(title, opts);
  else if (variant === "warning") toast.warning(title, opts);
  else toast.success(title, opts);
}

export function Toaster() {
  return (
    <Sonner position="top-right" richColors closeButton className="toaster"
      toastOptions={{ classNames: { actionButton: "toast-action" } }}
      style={{
        "--normal-bg": "var(--color-surface)",
        "--normal-text": "var(--color-gray-900)",
        "--normal-border": "var(--color-gray-100)",
        "--success-bg": "var(--color-success-50)",
        "--success-text": "var(--color-success-700)",
        "--success-border": "var(--color-success-700)",
        "--warning-bg": "var(--color-warning-50)",
        "--warning-text": "var(--color-warning-700)",
        "--warning-border": "var(--color-warning-700)",
        "--error-bg": "var(--color-danger-50)",
        "--error-text": "var(--color-danger-700)",
        "--error-border": "var(--color-danger-700)",
        "--border-radius": "var(--radius-md)",
      }} />
  );
}
