import { useCallback, useEffect, useRef, useState } from "react";

type ToastTone = "success" | "error";
type ToastState = { message: string; tone: ToastTone; key: number };

export function useToast() {
    const [toast, setToast] = useState<ToastState | null>(null);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const showToast = useCallback((message: string, tone: ToastTone = "success") => {
        if (timerRef.current) clearTimeout(timerRef.current);
        setToast({ message, tone, key: Date.now() });
        timerRef.current = setTimeout(() => setToast(null), 3000);
    }, []);

    useEffect(
        () => () => {
            if (timerRef.current) clearTimeout(timerRef.current);
        },
        []
    );

    const node = toast ? (
        <div className={`toast visible${toast.tone === "error" ? " error" : ""}`} key={toast.key}>
            {toast.message}
        </div>
    ) : (
        <div className="toast" aria-hidden="true" />
    );

    return { showToast, toastNode: node };
}
