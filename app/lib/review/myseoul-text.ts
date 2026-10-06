// Mirrors machimoa_review.myseoul_has_markup(text) from migration 20261006022909.
// Inert text validation only: callers must continue rendering text, never HTML.
const markupNames = new Set("a abbr acronym address applet area article aside audio b base basefont bdi bdo bgsound big blink blockquote body br button canvas caption center cite code col colgroup command content data datalist dd del details dfn dialog dir div dl dt em embed fieldset figcaption figure font footer form frame frameset h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe image img input ins kbd keygen label legend li link listing main map mark marquee math menu menuitem meta meter multicol nav nextid nobr noembed noframes noscript object ol optgroup option output p param picture plaintext portal pre progress q rb rp rt rtc ruby s samp script search section select shadow slot small source spacer span strike strong style sub summary sup svg table tbody td template textarea tfoot th thead time title tr track tt u ul var video wbr xmp animate animatemotion animatetransform circle clippath defs desc ellipse filter foreignobject g line lineargradient marker mask metadata mpath path pattern polygon polyline radialgradient rect set stop switch symbol text textpath tspan use view feblend fecolormatrix fecomponenttransfer fecomposite feconvolvematrix fediffuselighting fedisplacementmap fedistantlight fedropshadow feflood fefunca fefuncb fefuncg fefuncr fegaussianblur feimage femerge femergenode femorphology feoffset fepointlight fespecularlighting fespotlight fetile feturbulence annotation annotation-xml maction menclose merror mfenced mfrac mglyph mi mlabeledtr mmultiscripts mn mo mover mpadded mphantom mroot mrow ms mspace msqrt mstyle msub msubsup msup mtable mtd mtext mtr munder munderover semantics".split(" "));
// Mirrors the production en_US.UTF-8 POSIX classes (verified against metadata).
// The isolated DB uses en-US-x-icu for parity: C.UTF-8 has different classes.
// JS \s omits NEL and includes BOM, so use the SQL class explicitly.
const space = "[ \t\n\v\f\r\u001c-\u001f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]";
const plainHeading = new RegExp("^<[A-Za-z][A-Za-z0-9]*" + space + "+[^<>\"'=/`]+>$");
const emptyHeading = new RegExp(`^<[A-Za-z][A-Za-z0-9]*${space}+>$`);
const attributes = new RegExp(`${space}(on[a-z]+|xmlns|allowfullscreen|async|autofocus|autoplay|checked|controls|default|defer|disabled|enabled|formnovalidate|hidden|inert|ismap|itemscope|loop|multiple|muted|nomodule|novalidate|open|playsinline|readonly|required|reversed|selected)(${space}|>|$)`, "i");

export function myseoulHasMarkup(value: string): boolean {
  for (const [heading] of value.matchAll(/<[/!A-Za-z][^>]*>/g)) {
    const name = /^<([A-Za-z][A-Za-z0-9]*)/.exec(heading)?.[1].toLowerCase();
    if ((name !== undefined && markupNames.has(name)) || !plainHeading.test(heading)
      || emptyHeading.test(heading) || /[\x00-\x1f\x7f-\x9f]/.test(heading)
      || heading.includes("\\") || attributes.test(heading)) return true;
  }
  return false;
}
