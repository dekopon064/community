// Presentation-only palette. Image analysis and persistence are separate work.
export const homeCardPalette = Object.freeze({
  default: Object.freeze({ main: '#E8E8F3', peek: '#F0F0F7' }),
  orange: Object.freeze({ main: '#FFF0E5', peek: '#FFF5EF' }),
  yellow: Object.freeze({ main: '#FBF3D9', peek: '#FDF8E8' }),
  green: Object.freeze({ main: '#E1EFEC', peek: '#ECF6F2' }),
  blue: Object.freeze({ main: '#E5E8F8', peek: '#EFF1FC' }),
  purple: Object.freeze({ main: '#EEE5F6', peek: '#F5EFFA' }),
  red: Object.freeze({ main: '#F6E4EC', peek: '#FBEEF3' }),
});

export type HomeTone = keyof typeof homeCardPalette;

export function homeCardColors(tone: unknown, imageAvailable: boolean) {
  const key: HomeTone = imageAvailable && typeof tone === 'string' && Object.hasOwn(homeCardPalette, tone)
    ? tone as HomeTone : 'default';
  const colors = homeCardPalette[key];
  return { tone: key, style: { '--home-card-main': colors.main, '--home-card-peek': colors.peek } };
}
