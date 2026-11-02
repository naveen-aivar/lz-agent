/**
 * Aivar wordmark (from the logo file the team supplied). The white parts use currentColor so the
 * mark reads on light and dark backgrounds; the purple accent is the brand colour.
 */
export function AivarLogo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 156 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Aivar"
      className={className}
    >
      <g clipPath="url(#aivar-logo-clip)">
        <path
          d="M8.70547 3.1428H12.3608L13.3811 0H6.4255L3.05293 10.3796L5.72335 12.3189L8.70547 3.1428Z"
          fill="currentColor"
        />
        <path
          d="M24.9321 3.14437L26.0633 6.62298H29.3635L27.2137 0.00799561H16.3007L15.282 3.14276L24.9321 3.14437Z"
          fill="currentColor"
        />
        <path
          d="M3.69062 18.5773L4.82338 15.089L2.14815 13.1448L-7.62939e-05 19.7598L8.829 26.1756L11.4882 24.2426L3.69062 18.5773Z"
          fill="currentColor"
        />
        <path
          d="M30.2647 9.40106H26.9645L29.9466 18.5772L26.9886 20.7254L28.0105 23.8682L33.6373 19.7807L30.2647 9.40106Z"
          fill="currentColor"
        />
        <path
          d="M16.8182 28.1149L13.881 25.9811L11.2251 27.9108L16.8519 32L25.6794 25.5858L24.6527 22.4238L16.8182 28.1149Z"
          fill="#7A68FF"
        />
        <path
          d="M57.8746 7.75L64.4039 24.25H60.2046L55.4371 12.2021L55.2046 11.6143L54.9722 12.2021L50.2046 24.25H46.0044L52.5318 7.75H57.8746Z"
          fill="#7A68FF"
          stroke="#121212"
          strokeWidth="0.5"
        />
        <path
          d="M75.715 7.75L82.2453 24.25H78.0461L71.5158 7.75H75.715Z"
          fill="#7A68FF"
          stroke="#121212"
          strokeWidth="0.5"
        />
        <path
          d="M93.556 7.75L98.3236 19.7979L98.556 20.3857L98.7884 19.7979L103.556 7.75H107.755L101.226 24.25H95.8871L89.3568 7.75H93.556Z"
          fill="currentColor"
          stroke="#121212"
          strokeWidth="0.5"
        />
        <path
          d="M126.736 7.75L133.265 24.25H129.066L124.298 12.2021L124.066 11.6143L123.834 12.2021L119.066 24.25H114.867L121.397 7.75H126.736Z"
          fill="currentColor"
          stroke="#121212"
          strokeWidth="0.5"
        />
        <path
          d="M147.99 7.8092C150.411 7.8092 152.168 8.40233 153.312 9.54553C154.253 10.4868 154.733 11.7542 154.733 13.3727C154.733 14.5713 154.453 15.5718 153.906 16.3873C153.391 17.1557 152.627 17.7732 151.602 18.2399L151.598 18.234L151.402 18.3307L151.397 18.3346L151.501 18.5631L151.308 18.6959L155.068 24.191H150.274L146.945 19.1891L146.871 19.0778H144.438V24.1871H140.259V15.9098L147.774 15.9088C148.488 15.948 149.191 15.7414 149.768 15.318L149.778 15.3092C150.279 14.8964 150.558 14.2734 150.533 13.6256C150.575 12.9687 150.294 12.3295 149.775 11.9196L149.767 11.9137L149.76 11.9088L149.53 11.7682C148.989 11.4648 148.371 11.3247 147.75 11.359H140.259V7.8092H147.99Z"
          fill="currentColor"
          stroke="#121212"
          strokeWidth="0.5"
        />
      </g>
      <defs>
        <clipPath id="aivar-logo-clip">
          <rect width="155.542" height="32" fill="currentColor" />
        </clipPath>
      </defs>
    </svg>
  );
}
