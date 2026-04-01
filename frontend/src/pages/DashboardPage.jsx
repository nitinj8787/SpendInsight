import { useState, useEffect } from 'react';
import {
  PieChart, Pie, Cell, Tooltip as PieTooltip, Legend as PieLegend, ResponsiveContainer,
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as LineTooltip, Legend as LineLegend,
} from 'recharts';
import { getAnalytics, getTransactions } from '../api/client';
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

export default function DashboardPage() {
  const [analytics, setAnalytics] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      try {
        const [analyticsRes, txRes] = await Promise.all([
          getAnalytics(),
          getTransactions(),
        ]);
        if (!cancelled) {
          setAnalytics(analyticsRes.data);
          setTransactions(txRes.data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.response?.data?.detail || err.message || 'Failed to load data.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return <div className="dashboard-loading">Loading dashboard…</div>;
  }

  if (error) {
    return <div className="dashboard-error">❌ {error}</div>;
  }

  return (
    <div className="dashboard-page">
      <h1>Dashboard</h1>

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
        {transactions.length === 0 ? (
          <p className="empty-state">
            No transactions yet. <a href="/upload">Upload a file</a> to get started.
          </p>
        ) : (
          <table className="transactions-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Description</th>
                <th>Amount</th>
                <th>Type</th>
                <th>Category</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((tx) => (
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
