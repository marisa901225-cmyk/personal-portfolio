import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const fetchExpensesMock = vi.fn().mockResolvedValue([
  {
    id: 1,
    user_id: 1,
    date: '2025-01-05',
    amount: -12000,
    category: '식비',
    merchant: 'Merchant A',
    method: 'Card',
    is_fixed: false,
    memo: null,
    created_at: '2025-01-05T00:00:00',
    updated_at: '2025-01-05T00:00:00',
    deleted_at: null,
  },
  {
    id: 2,
    user_id: 1,
    date: '2025-01-06',
    amount: -9000,
    category: '식비',
    merchant: 'Merchant B',
    method: 'Card',
    is_fixed: false,
    memo: null,
    created_at: '2025-01-06T00:00:00',
    updated_at: '2025-01-06T00:00:00',
    deleted_at: '2025-01-07T00:00:00',
  },
]);

const fetchCategoriesMock = vi.fn().mockResolvedValue([]);

vi.mock('@/shared/api/client', () => {
  return {
    ApiClient: class {
      fetchExpenses = fetchExpensesMock;
      fetchCategories = fetchCategoriesMock;
      deleteExpense = vi.fn().mockResolvedValue({ status: 'ok' });
      restoreExpense = vi.fn().mockResolvedValue({});
      updateExpense = vi.fn().mockResolvedValue({});
      uploadExpenseFile = vi.fn().mockResolvedValue({});
      triggerLearning = vi.fn().mockResolvedValue({ added: 0, updated: 0 });
    },
  };
});

import { ExpensesDashboard } from '../components/ExpensesDashboard';

describe('ExpensesDashboard', () => {
  it('toggles visibility of deleted expenses', async () => {
    render(<ExpensesDashboard serverUrl="http://localhost" apiToken="token" />);

    // 기본적으로 삭제되지 않은 항목(Merchant A)만 표시
    expect(await screen.findByText('Merchant A')).toBeInTheDocument();
    expect(screen.queryByText('Merchant B')).not.toBeInTheDocument();

    // 토글 체크박스 클릭
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);

    // 삭제된 항목(Merchant B)도 표시됨
    expect(await screen.findByText('Merchant B')).toBeInTheDocument();
  });
});
