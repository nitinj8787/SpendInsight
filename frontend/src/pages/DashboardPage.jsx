import { useState, useEffect } from 'react';
import { getAnalytics, getTransactions } from '../api/client';
import './DashboardPage.css';

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
              <ul className="category-list">
                {analytics.category_breakdown.map((item) => (
                  <li key={item.category} className="category-item">
                    <span className="category-name">{item.category}</span>
                    <span className="category-amount">{formatCurrency(item.total)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {analytics.monthly_trends.length > 0 && (
            <section className="dashboard-section">
              <h2>Monthly Trends</h2>
              <table className="trends-table">
                <thead>
                  <tr>
                    <th>Month</th>
                    <th>Income</th>
                    <th>Expenses</th>
                    <th>Net</th>
                  </tr>
                </thead>
                <tbody>
                  {analytics.monthly_trends.map((row) => {
                    const net = parseFloat(row.income) - parseFloat(row.expenses);
                    return (
                      <tr key={row.month}>
                        <td>{row.month}</td>
                        <td className="amount-positive">{formatCurrency(row.income)}</td>
                        <td className="amount-negative">{formatCurrency(row.expenses)}</td>
                        <td className={net >= 0 ? 'amount-positive' : 'amount-negative'}>
                          {formatCurrency(net)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
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
