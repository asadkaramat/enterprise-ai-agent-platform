import { useState, useCallback } from 'react';

const STORAGE_KEY = 'agent_platform_api_key';

export function useApiKey() {
  const [apiKey, setApiKeyState] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) ?? ''
  );

  const setApiKey = useCallback((key: string) => {
    localStorage.setItem(STORAGE_KEY, key);
    setApiKeyState(key);
  }, []);

  const clearApiKey = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setApiKeyState('');
  }, []);

  return { apiKey, setApiKey, clearApiKey, hasApiKey: !!apiKey };
}
