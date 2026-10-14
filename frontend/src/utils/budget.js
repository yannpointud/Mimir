// Pure helper: maps spend-vs-cap ratio to a three-state budget status.
// Defensive on cap <= 0 (returns 'normal' rather than dividing by zero).
export const getBudgetStatus = (spent, cap) => {
  if (!cap || cap <= 0) {
    return 'normal';
  }
  const ratio = spent / cap;
  if (ratio >= 1.0) {
    return 'exceeded';
  }
  if (ratio >= 0.8) {
    return 'warning';
  }
  return 'normal';
};
