import { useEffect, useState } from 'react';

/**
 * Track whether the viewport is below a mobile breakpoint (default 768px).
 * Re-renders on resize so layout decisions (drawer vs fixed sidebar, compact
 * header buttons) stay in sync with the window width.
 */
export function useIsMobile(breakpoint = 768): boolean {
  const read = () => (typeof window !== 'undefined' ? window.innerWidth < breakpoint : false);
  const [isMobile, setIsMobile] = useState<boolean>(read);

  useEffect(() => {
    const onResize = () => setIsMobile(read());
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [breakpoint]);

  return isMobile;
}
