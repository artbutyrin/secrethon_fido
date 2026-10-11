import { createContext, createElement, useContext } from 'react';
import { useAnalysis } from './useAnalysis';

const AnalysisContext = createContext(null);

export function AnalysisProvider({ children }) {
  const analysis = useAnalysis();
  return createElement(AnalysisContext.Provider, { value: analysis }, children);
}

export function useSharedAnalysis() {
  const value = useContext(AnalysisContext);
  if (!value) throw new Error('useSharedAnalysis must be used inside AnalysisProvider');
  return value;
}
