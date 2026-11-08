import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

/**
 * Toast（DESIGN.md 6.32）：深綠底白字，數秒後自動消失，`role="status"`。
 * 包在 `ToastProvider` 裡，元件用 `useToast().show("文字")`。
 */
const ToastContext = createContext<{ show: (text: string) => void }>({ show: () => {} });

export const TOAST_MS = 3000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [text, setText] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const show = useCallback((next: string) => {
    setText(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setText(null), TOAST_MS);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      {/* 區域一直在，內容變了螢幕閱讀器才會念 */}
      <div role="status" aria-live="polite">
        {text && (
          <p
            data-testid="toast"
            className="fixed top-4 left-1/2 z-60 m-0 w-max max-w-[min(560px,calc(100vw-2rem))] -translate-x-1/2 rounded-chip bg-toast px-5 py-3 t-body text-white shadow-toast md:top-28"
          >
            {text}
          </p>
        )}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
