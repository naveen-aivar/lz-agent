import InfoHint from "./InfoHint.jsx";

// A form field: its label (with an "i" and an "Optional" tag when they apply), the control, and a hint or error.
export function Field({ id, label, info, optional = false, hint, error, children }) {
  return (
    <div className="field">
      <div className="field-label-row">
        <label className="field-label" htmlFor={id}>{label}</label>
        {info ? <InfoHint {...info} label={info.label || label} /> : null}
        {optional ? <span className="field-optional">Optional</span> : null}
      </div>
      {children}
      {error ? <p className="field-error" role="alert">{error}</p> : hint ? <p className="field-hint">{hint}</p> : null}
    </div>
  );
}
