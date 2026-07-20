import { describe, it, expect } from 'vitest';
import { getBudgetStatus } from './AnalyticsPanel';

// Pure helper coverage for the Coûts IA gauge three-state mapping (COST-02).
describe('getBudgetStatus', () => {
  it('returns "normal" when spend is well under the cap', () => {
    expect(getBudgetStatus(7.9, 10)).toBe('normal');
  });

  it('returns "normal" at exactly 79% of the cap', () => {
    expect(getBudgetStatus(0.79, 1)).toBe('normal');
  });

  it('returns "warning" at exactly 80% of the cap (threshold inclusive)', () => {
    expect(getBudgetStatus(0.8, 1)).toBe('warning');
  });

  it('returns "warning" just under 100% of the cap', () => {
    expect(getBudgetStatus(0.99, 1)).toBe('warning');
  });

  it('returns "exceeded" at exactly 100% of the cap', () => {
    expect(getBudgetStatus(1.0, 1)).toBe('exceeded');
  });

  it('returns "exceeded" when spend is over the cap', () => {
    expect(getBudgetStatus(1.5, 1)).toBe('exceeded');
  });

  it('returns "normal" defensively when cap is zero (avoids division by zero)', () => {
    expect(getBudgetStatus(5, 0)).toBe('normal');
  });

  it('returns "normal" defensively when cap is negative', () => {
    expect(getBudgetStatus(5, -10)).toBe('normal');
  });
});
