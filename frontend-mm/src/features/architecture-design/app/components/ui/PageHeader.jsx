export function PageHeader({ title, description, actions, children }) {
  return (
    <div className="page-header">
      <div className="page-header-text">
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
        {children}
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </div>
  );
}
