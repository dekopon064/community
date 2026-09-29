"use client";

// The server script runs during HTML parsing; client navigations use the
// already-mounted theme controller instead of executing another script.
export default function ThemeBootstrap() {
  return (
    <script
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{
        __html: `(function(){try{var value=localStorage.getItem("machimoa-theme");if(value==="dark")document.documentElement.dataset.theme="dark"}catch(error){}})()`,
      }}
    />
  );
}
