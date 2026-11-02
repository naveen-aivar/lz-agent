import InfoHint from "./InfoHint.jsx";

// A white rounded card. `info` is {label, text} and puts the "i" beside the title.
export function Card({ title, info, aside, description, children, className = "", flush = false, style, ...rest }) {
  return (
    <section className={`card ${className}`.trim()} style={style} {...rest}>
      {title || aside ? (
        <header className="card-head">
          <div className="card-head-text">
            <h2 className="card-title">{title}{info ? <InfoHint {...info} /> : null}</h2>
            {description ? <p className="card-desc">{description}</p> : null}
          </div>
          {aside ? <div className="card-aside">{aside}</div> : null}
        </header>
      ) : null}
      <div className={flush ? "card-body card-body-flush" : "card-body"}>{children}</div>
    </section>
  );
}
