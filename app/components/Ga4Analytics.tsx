'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { browserGa4 } from '../lib/analytics/ga4-browser';
import type { Ga4Config } from '../lib/analytics/ga4';

export default function Ga4Analytics({ config: { measurementId, origin } }: { config: Ga4Config }) {
  const pathname = usePathname();
  useEffect(() => browserGa4({ measurementId, origin }, window)?.connect(), [measurementId, origin]);
  useEffect(() => { browserGa4({ measurementId, origin }, window)?.sync(); }, [pathname, measurementId, origin]);
  return null;
}
