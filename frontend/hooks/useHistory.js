"use client";

import { useState, useCallback } from "react";

const MAX_HISTORY = 30;

export function useHistory() {
  const [history, setHistory] = useState([]);

  const addEntry = useCallback((entry) => {
    setHistory((prev) => [
      {
        id: Date.now(),
        name: entry.name,
        success: entry.success,
        tokens: entry.token_estimate ?? 0,
        duration: entry.duration_s ?? 0,
        timestamp: Date.now(),
      },
      ...prev,
    ].slice(0, MAX_HISTORY));
  }, []);

  const clearHistory = useCallback(() => setHistory([]), []);

  return { history, addEntry, clearHistory };
}
