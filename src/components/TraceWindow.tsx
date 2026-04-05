import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

type TraceWindowProps = {
  open: boolean;
  title?: string;
  onClose: () => void;
  onBlocked?: () => void;
  children: ReactNode;
};

const WINDOW_FEATURES =
  'popup=yes,width=540,height=900,resizable=yes,scrollbars=yes';

function copyStylesToWindow(source: Document, target: Document) {
  const nodes = source.querySelectorAll('link[rel="stylesheet"], style');
  for (const n of nodes) {
    target.head.appendChild(n.cloneNode(true));
  }
}

export function TraceWindow({
  open,
  title = 'Paintbrush Trace Monitor',
  onClose,
  onBlocked,
  children,
}: TraceWindowProps) {
  const [externalWindow, setExternalWindow] = useState<Window | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      if (externalWindow && !externalWindow.closed) {
        externalWindow.close();
      }
      setExternalWindow(null);
      containerRef.current = null;
      return;
    }

    if (externalWindow && !externalWindow.closed) {
      externalWindow.focus();
      return;
    }

    const w = window.open('', 'paintbrush-trace-monitor', WINDOW_FEATURES);
    if (!w) {
      onBlocked?.();
      onClose();
      return;
    }

    w.document.title = title;
    w.document.body.innerHTML = '';
    const mount = w.document.createElement('div');
    mount.id = 'trace-monitor-root';
    mount.style.height = '100%';
    w.document.body.style.margin = '0';
    w.document.body.style.background = '#0b1018';
    w.document.body.appendChild(mount);
    copyStylesToWindow(document, w.document);

    const handleBeforeUnload = () => onClose();
    w.addEventListener('beforeunload', handleBeforeUnload);

    containerRef.current = mount;
    setExternalWindow(w);

    return () => {
      w.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [open, title, externalWindow, onClose, onBlocked]);

  useEffect(() => {
    if (!externalWindow) return;
    const timer = window.setInterval(() => {
      if (externalWindow.closed) {
        window.clearInterval(timer);
        setExternalWindow(null);
        containerRef.current = null;
        onClose();
      }
    }, 500);
    return () => window.clearInterval(timer);
  }, [externalWindow, onClose]);

  const portalTarget = useMemo(() => containerRef.current, [containerRef.current]);
  if (!open || !externalWindow || !portalTarget) return null;

  return createPortal(children, portalTarget);
}

