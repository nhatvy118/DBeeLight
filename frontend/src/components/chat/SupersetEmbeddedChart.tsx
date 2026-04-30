import { useEffect, useRef, useState } from 'react';
import { embedDashboard } from '@superset-ui/embedded-sdk';

type Props = {
  embeddedUuid: string;
  supersetDomain: string;
  initialGuestToken?: string;
  projectId: string;
  /** Optional — when present, the backend can re-wrap this chart and return a
   *  fresh ``embedded_uuid`` if the original wrapper dashboard is gone. */
  chartId?: number;
};

/**
 * Mounts a Superset embedded dashboard via @superset-ui/embedded-sdk.
 *
 * The iframe loads ``/embedded/<uuid>`` without using browser cookies of the
 * Superset domain — authentication is solely via the guest token passed by the
 * SDK over postMessage. This means a developer logged in as admin in another
 * tab does NOT leak edit privileges into the chart iframe; the embed user is
 * always the read-only Gamma role assumed by the token.
 *
 * The SDK calls ``fetchGuestToken`` on mount and again before token expiry.
 * Each mount always mints a fresh token — the prop-passed ``initialGuestToken``
 * is only used on the very first render right after chart creation, never on
 * subsequent reloads (cached tokens go stale after the 5-min TTL and would
 * leave the iframe spinning forever once the chat history reloads).
 */
export default function SupersetEmbeddedChart({
  embeddedUuid,
  supersetDomain,
  initialGuestToken,
  projectId,
  chartId,
}: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const initialUsedRef = useRef<boolean>(false);
  const failureCountRef = useRef<number>(0);
  const [error, setError] = useState<string | null>(null);
  // Backend may swap embeddedUuid out from under us when it auto-recreates a
  // dead wrapper dashboard. Track the active UUID locally so the embed-sdk
  // mount can target the new one.
  const [activeUuid, setActiveUuid] = useState<string>(embeddedUuid);
  // Don't mint until the chart actually scrolls into view. With multiple
  // chart messages in chat history, mounting them all at once means N
  // simultaneous mint requests at page-load — combined with SDK retries on
  // any failure, that easily exceeds Superset's per-second rate limit.
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    setActiveUuid(embeddedUuid);
  }, [embeddedUuid]);

  useEffect(() => {
    const node = mountRef.current;
    if (!node) return;
    if (typeof IntersectionObserver === 'undefined') {
      setIsVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setIsVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: '200px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!isVisible || !mountRef.current) return;

    let cancelled = false;
    failureCountRef.current = 0;
    setError(null);

    async function fetchGuestToken(): Promise<string> {
      if (initialGuestToken && !initialUsedRef.current) {
        initialUsedRef.current = true;
        return initialGuestToken;
      }
      // The SDK retries fetchGuestToken on failure. If the backend is down
      // (502) or returning errors, retries spam the network. Bail after 3
      // consecutive failures so the iframe surfaces an error instead of
      // spinning + flooding the proxy with thousands of requests.
      if (failureCountRef.current >= 3) {
        throw new Error('Guest token fetch giving up after repeated failures');
      }
      const resp = await fetch('/api/superset/guest-token', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          embedded_uuid: activeUuid,
          project_id: projectId,
          ttl_seconds: 300,
          chart_id: chartId,
        }),
      });
      if (!resp.ok) {
        failureCountRef.current += 1;
        throw new Error(`Failed to refresh guest token: ${resp.status}`);
      }
      failureCountRef.current = 0;
      const data = await resp.json();
      // If the backend re-wrapped the chart (because the original dashboard
      // was missing), it returns a different ``embedded_uuid``. Update local
      // state — the useEffect dependency will tear down + re-mount the iframe
      // with the fresh UUID.
      const returnedUuid = typeof data.embedded_uuid === 'string' ? data.embedded_uuid : null;
      if (returnedUuid && returnedUuid !== activeUuid) {
        setActiveUuid(returnedUuid);
      }
      return data.token as string;
    }

    let instance: { unmount: () => void } | null = null;
    embedDashboard({
      id: activeUuid,
      supersetDomain,
      mountPoint: mountRef.current,
      fetchGuestToken,
      // View + download only. Gamma role enforces read-only at the perm layer;
      // these flags shape the dashboard chrome to match.
      dashboardUiConfig: {
        hideTitle: true,
        hideTab: true,
        hideChartControls: false, // shows the download menu
        filters: { expanded: false },
      },
    })
      .then((d) => {
        if (cancelled) {
          // Effect was torn down before init resolved — unmount immediately
          // so the guest-token refresh loop never starts running orphaned.
          d?.unmount?.();
          return;
        }
        instance = d as { unmount: () => void };
      })
      .catch((e) => {
        if (!cancelled) {
          console.error('[SupersetEmbed] Failed to mount:', e);
          setError(
            'Could not load chart. The dashboard may have been deleted or Superset is unreachable.',
          );
        }
      });

    return () => {
      cancelled = true;
      // Calling SDK's unmount() tears down the iframe, postMessage listeners,
      // AND the setTimeout that refreshes the guest token. Without this the
      // refresh loop keeps hitting /api/superset/guest-token after the
      // component unmounts (visible as zombie network requests in DevTools).
      try {
        instance?.unmount();
      } catch (e) {
        console.warn('[SupersetEmbed] unmount failed:', e);
      }
      instance = null;
    };
  }, [isVisible, activeUuid, supersetDomain, projectId, chartId, initialGuestToken]);

  if (error) {
    return (
      <div
        className="w-full flex items-center justify-center text-sm text-gray-500 bg-gray-50 border border-dashed border-gray-300 rounded"
        style={{ height: '500px' }}
      >
        {error}
      </div>
    );
  }

  return (
    <div
      ref={mountRef}
      className="w-full superset-embed-mount"
      style={{ height: '500px' }}
    />
  );
}
