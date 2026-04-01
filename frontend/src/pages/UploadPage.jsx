import { useState, useCallback } from 'react';
import { uploadFile } from '../api/client';
import './UploadPage.css';

const ACCEPTED_TYPES = '.csv,.pdf';

export default function UploadPage() {
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState('idle'); // idle | uploading | success | error
  const [message, setMessage] = useState('');
  const [importedCount, setImportedCount] = useState(0);
  const [dragging, setDragging] = useState(false);

  const handleFile = (selected) => {
    setFile(selected);
    setStatus('idle');
    setMessage('');
  };

  const handleFileChange = (e) => {
    if (e.target.files[0]) handleFile(e.target.files[0]);
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) handleFile(dropped);
  }, []);

  const handleDragOver = (e) => {
    e.preventDefault();
    setDragging(true);
  };

  const handleDragLeave = () => setDragging(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) return;

    setStatus('uploading');
    setMessage('');

    try {
      const response = await uploadFile(file);
      const count = response.data.length;
      setImportedCount(count);
      setStatus('success');
      setMessage(`Successfully imported ${count} transaction${count !== 1 ? 's' : ''}.`);
      setFile(null);
    } catch (err) {
      setStatus('error');
      const detail = err.response?.data?.detail || err.message || 'Upload failed.';
      setMessage(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
  };

  return (
    <div className="upload-page">
      <h1>Upload Transactions</h1>
      <p className="upload-subtitle">
        Import your bank statement as a <strong>CSV</strong> or <strong>PDF</strong> file.
      </p>

      <form onSubmit={handleSubmit} className="upload-form">
        <div
          className={`drop-zone${dragging ? ' dragging' : ''}${file ? ' has-file' : ''}`}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => document.getElementById('file-input').click()}
        >
          {file ? (
            <span className="file-name">📄 {file.name}</span>
          ) : (
            <span className="drop-hint">
              Drag &amp; drop a CSV or PDF here, or <u>click to browse</u>
            </span>
          )}
          <input
            id="file-input"
            type="file"
            accept={ACCEPTED_TYPES}
            onChange={handleFileChange}
            hidden
          />
        </div>

        <button
          type="submit"
          className="upload-btn"
          disabled={!file || status === 'uploading'}
        >
          {status === 'uploading' ? 'Uploading…' : 'Upload'}
        </button>
      </form>

      {status === 'success' && (
        <div className="alert alert-success">✅ {message}</div>
      )}
      {status === 'error' && (
        <div className="alert alert-error">❌ {message}</div>
      )}

      {status === 'success' && importedCount > 0 && (
        <p className="upload-hint">
          Head to the <a href="/">Dashboard</a> to view your transactions.
        </p>
      )}
    </div>
  );
}
