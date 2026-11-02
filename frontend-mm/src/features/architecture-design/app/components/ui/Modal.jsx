import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { portalContainer } from "@/features/architecture-design/adapters/portal.js";

// A centred dialog (focus is kept inside, Escape closes it). size: md | lg | xl. A dialog opened from code rather than from a
// Radix trigger passes onCloseAutoFocus to say where focus goes when it closes.
export function Modal({ open = true, onOpenChange, title, description, size = "md", children, footer, onCloseAutoFocus }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal container={portalContainer()}>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content className={`modal-panel modal-${size}`} onCloseAutoFocus={onCloseAutoFocus}>
          <header className="modal-head">
            <Dialog.Title className="modal-title">{title}</Dialog.Title>
            <Dialog.Close className="icon-btn" aria-label="Close"><X size={16} aria-hidden /></Dialog.Close>
          </header>
          <Dialog.Description className={description ? "modal-desc" : "sr-only"}>{description || title}</Dialog.Description>
          <div className="modal-body">{children}</div>
          {footer ? <footer className="modal-foot">{footer}</footer> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
