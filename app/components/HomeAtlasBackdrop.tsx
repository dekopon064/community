export default function HomeAtlasBackdrop() {
  return (
    <>
      <svg
        className="pointer-events-none absolute inset-0 -z-10 hidden h-full w-full lg:block"
        viewBox="0 0 1440 828"
        preserveAspectRatio="none"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <filter
            id="home-atlas-desktop-feather"
            x="-15%"
            y="-15%"
            width="130%"
            height="130%"
          >
            <feGaussianBlur stdDeviation="1" />
          </filter>
          <mask
            id="home-atlas-desktop-mineral"
            maskUnits="userSpaceOnUse"
            x="0"
            y="0"
            width="1440"
            height="828"
          >
            <path
              fill="#fff"
              filter="url(#home-atlas-desktop-feather)"
              d="M-60-60H387C406-40 423-18 435 0C534 88 576 191 543 299C513 398 512 508 590 631C625 687 690 753 724 828C760 872 792 900 810 888H-60Z"
            />
          </mask>
        </defs>
        <rect
          width="1440"
          height="828"
          fill="var(--color-mineral)"
          mask="url(#home-atlas-desktop-mineral)"
        />
      </svg>

      <svg
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[232px] w-full lg:hidden"
        viewBox="0 0 390 232"
        preserveAspectRatio="none"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <linearGradient id="home-atlas-hero-halo" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--color-mineral)" stopOpacity="0.82" />
            <stop offset="0.55" stopColor="var(--color-mineral)" stopOpacity="0.45" />
            <stop offset="1" stopColor="var(--color-mineral)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path
          fill="url(#home-atlas-hero-halo)"
          d="M-24 6C73-16 205-9 414 49V145C336 190 241 224 141 220C65 217 14 194-24 166Z"
        />
      </svg>
    </>
  );
}
