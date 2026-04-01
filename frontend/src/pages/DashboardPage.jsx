import { useState, useEffect, useMemo } from 'react';
import {
  PieChart, Pie, Cell, Tooltip as PieTooltip, Legend as PieLegend, ResponsiveContainer,
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as LineTooltip, Legend as LineLegend,
} from 'recharts';
import { getAnalytics, getTransactions, deleteAllTransactions } from '../api/client';
import './DashboardPage.css';

const PIE_COLORS = [
  '#6366f1', '#f59e0b', '#10b981', '#ef4444',
  '#3b82f6', '#ec4899', '#14b8a6', '#f97316',
];

function StatCard({ label, value, colorClass }) {
  return (
    <div className={`stat-card ${colorClass}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}

function formatCurrency(value) {
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(value);
}

const SORT_FIELDS = ['date', 'description', 'amount', 'type', 'category', 'source'];

function SortIndicator({ field, sortField, sortDir }) {
  if (field !== sortField) return <span className="sort-indicator sort-inactive">⇅</span>;
  return (
    <span className="sort-indicator sort-active">
      {sortDir === 'asc' ? '↑' : '↓'}
    </span>
  );
}

export default function DashboardPage() {
  const [analytics, setAnalytics] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [sortField, setSortField] = useState('date');
  const [sortDir, setSortDir] = useState('desc');
  const [deleting, setDeleting] = useState(false);

  async function fetchData(signal) {
    const [analyticsRes, txRes] = await Promise.all([
      getAnalytics(),
      getTransactions(),
    ]);
    if (!signal?.aborted) {
      setAnalytics(analyticsRes.data);
      setTransactions(txRes.data);
    }
  }

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        await fetchData(controller.signal);
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err.response?.data?.detail || err.message || 'Failed to load data.');
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    load();
    return () => controller.abort();
  }, []);

  function handleSort(field) {
    if (field === sortField) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  }

  async function handleDeleteAll() {
    if (!window.confirm('Are you sure you want to delete ALL transactions? This cannot be undone.')) {
      return;
    }
    setDeleting(true);
    try {
      await deleteAllTransactions();
      setTransactions([]);
      setAnalytics(null);
      // Re-fetch analytics so summary cards reset to zero
      try {
        const analyticsRes = await getAnalytics();
        setAnalytics(analyticsRes.data);
      } catch {
        // analytics may return empty-state — not fatal
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Failed to delete data.');
    } finally {
      setDeleting(false);
    }
  }

  const sortedTransactions = useMemo(() => {
    const copy = [...transactions];
    copy.sort((a, b) => {
      let av = a[sortField];
      let bv = b[sortField];
      if (sortField === 'amount') {
        av = parseFloat(av);
        bv = parseFloat(bv);
      } else {
        av = String(av ?? '').toLowerCase();
        bv = String(bv ?? '').toLowerCase();
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return copy;
  }, [transactions, sortField, sortDir]);

  if (loading) {
    return <div className="dashboard-loading">Loading dashboard…</div>;
  }

  if (error) {
    return <div className="dashboard-error">❌ {error}</div>;
  }

  return (
    <div className="dashboard-page">
      <div className="dashboard-header">
        <h1>Dashboard</h1>
        {transactions.length > 0 && (
          <button
            className="btn-delete-all"
            onClick={handleDeleteAll}
            disabled={deleting}
          >
            {deleting ? 'Deleting…' : '🗑 Delete All Data'}
          </button>
        )}
      </div>

      {analytics && (
        <>
          <section className="stat-cards">
            <StatCard
              label="Total Income"
              value={formatCurrency(analytics.total_income)}
              colorClass="green"
            />
            <StatCard
              label="Total Expenses"
              value={formatCurrency(analytics.total_expenses)}
              colorClass="red"
            />
            <StatCard
              label="Savings"
              value={formatCurrency(analytics.savings)}
              colorClass={parseFloat(analytics.savings) >= 0 ? 'green' : 'red'}
            />
          </section>

          {analytics.category_breakdown.length > 0 && (
            <section className="dashboard-section">
              <h2>Spending by Category</h2>
              <div className="chart-container">
                <ResponsiveContainer width="100%" height={320}>
                  <PieChart>
                    <Pie
                      data={analytics.category_breakdown}
                      dataKey="total"
                      nameKey="category"
                      cx="50%"
                      cy="50%"
                      outerRadius={110}
                      label={({ category, percent }) =>
                        `${category} (${(percent * 100).toFixed(0)}%)`
                      }
                    >
                      {analytics.category_breakdown.map((entry, index) => (
                        <Cell
                          key={entry.category}
                          fill={PIE_COLORS[index % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                    <PieTooltip
                      formatter={(value, name) => [formatCurrency(value), name]}
                    />
                    <PieLegend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </section>
          )}

          {analytics.monthly_trends.length > 0 && (
            <section className="dashboard-section">
              <h2>Monthly Trends</h2>
              <div className="chart-container">
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart
                    data={analytics.monthly_trends.map((row) => ({
                      ...row,
                      income: parseFloat(row.income),
                      expenses: parseFloat(row.expenses),
                    }))}
                    margin={{ top: 8, right: 24, left: 16, bottom: 8 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                    <YAxis tickFormatter={(v) => `£${v}`} tick={{ fontSize: 12 }} />
                    <LineTooltip
                      formatter={(value, name) => [formatCurrency(value), name]}
                    />
                    <LineLegend />
                    <Line
                      type="monotone"
                      dataKey="income"
                      stroke="#10b981"
                      strokeWidth={2}
                      dot={{ r: 4 }}
                      activeDot={{ r: 6 }}
                      name="Income"
                    />
                    <Line
                      type="monotone"
                      dataKey="expenses"
                      stroke="#ef4444"
                      strokeWidth={2}
                      dot={{ r: 4 }}
                      activeDot={{ r: 6 }}
                      name="Expenses"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </section>
          )}
        </>
      )}

      <section className="dashboard-section">
        <h2>Recent Transactions</h2>
        {sortedTransactions.length === 0 ? (
          <p className="empty-state">
            No transactions yet. <a href="/upload">Upload a file</a> to get started.
          </p>
        ) : (
          <table className="transactions-table">
            <thead>
              <tr>
                {SORT_FIELDS.map((field) => (
                  <th
                    key={field}
                    className="sortable-th"
                    onClick={() => handleSort(field)}
                  >
                    {field.charAt(0).toUpperCase() + field.slice(1)}
                    <SortIndicator field={field} sortField={sortField} sortDir={sortDir} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedTransactions.map((tx) => (
                <tr key={tx.id}>
                  <td>{tx.date}</td>
                  <td>{tx.description}</td>
                  <td className={tx.type === 'income' ? 'amount-positive' : 'amount-negative'}>
                    {formatCurrency(tx.amount)}
                  </td>
                  <td>{tx.type}</td>
                  <td>{tx.category}</td>
                  <td>{tx.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
