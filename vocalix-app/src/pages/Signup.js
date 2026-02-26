import React, { useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/api';
import './Auth.css';

export default function Signup({ onLogin }) {
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [audioBlob, setAudioBlob] = useState(null);
  const [audioUrl, setAudioUrl] = useState(null);
  const [recordingTime, setRecordingTime] = useState(0);
  const mediaRecorder = useRef(null);
  const timerRef = useRef(null);
  const chunks = useRef([]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder.current = new MediaRecorder(stream);
      chunks.current = [];
      mediaRecorder.current.ondataavailable = e => chunks.current.push(e.data);
      mediaRecorder.current.onstop = () => {
        const blob = new Blob(chunks.current, { type: 'audio/wav' });
        setAudioBlob(blob);
        setAudioUrl(URL.createObjectURL(blob));
        stream.getTracks().forEach(t => t.stop());
      };
      mediaRecorder.current.start();
      setRecording(true);
      setRecordingTime(0);
      timerRef.current = setInterval(() => setRecordingTime(t => t + 1), 1000);
    } catch {
      setError('Microphone access denied. Please allow microphone access.');
    }
  };

  const stopRecording = () => {
    mediaRecorder.current?.stop();
    setRecording(false);
    clearInterval(timerRef.current);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!audioBlob) { setError('Please record your voice sample'); return; }
    setLoading(true);
    setError('');
    try {
      const fd = new FormData();
      fd.append('name', form.name);
      fd.append('email', form.email);
      fd.append('password', form.password);
      fd.append('voice_sample', audioBlob, 'voice_sample.wav');
      const r = await api.post('/auth/signup', fd);
      onLogin(r.data.user, r.data.token);
    } catch (err) {
      setError(err.response?.data?.detail || 'Signup failed');
    }
    setLoading(false);
  };

  return (
    <div className="auth-bg">
      <div className="auth-glow" />
      <div className="auth-card fade-up">
        <div className="auth-logo">
          <span className="logo-icon">◈</span>
          <span className="logo-text">Vocalix</span>
        </div>
        <h2 className="auth-title">Create account</h2>
        <p className="auth-sub">Join Vocalix and clone your voice</p>

        {error && <div className="auth-error">{error}</div>}

        <form onSubmit={submit} className="auth-form">
          <div className="field">
            <label>Full Name</label>
            <input className="input" type="text" placeholder="Your name"
              value={form.name} onChange={e => setForm({...form, name: e.target.value})} required />
          </div>
          <div className="field">
            <label>Email</label>
            <input className="input" type="email" placeholder="you@example.com"
              value={form.email} onChange={e => setForm({...form, email: e.target.value})} required />
          </div>
          <div className="field">
            <label>Password</label>
            <input className="input" type="password" placeholder="••••••••"
              value={form.password} onChange={e => setForm({...form, password: e.target.value})} required />
          </div>

          {/* Voice Recording */}
          <div className="voice-section">
            <label className="voice-label">Voice Sample <span className="required">*</span></label>
            <p className="voice-hint">Record 5–10 seconds of your voice. This will be used to clone your voice in messages.</p>
            <div className="voice-recorder">
              {!recording && !audioBlob && (
                <button type="button" className="btn btn-danger record-btn" onClick={startRecording}>
                  <span className="rec-dot" /> Start Recording
                </button>
              )}
              {recording && (
                <button type="button" className="btn btn-danger record-btn recording-active" onClick={stopRecording}>
                  <span className="rec-dot active" /> Stop Recording {recordingTime}s
                </button>
              )}
              {audioBlob && !recording && (
                <div className="voice-preview">
                  <audio controls src={audioUrl} style={{ width: '100%' }} />
                  <button type="button" className="btn btn-ghost re-record" onClick={() => { setAudioBlob(null); setAudioUrl(null); }}>
                    Re-record
                  </button>
                </div>
              )}
            </div>
          </div>

          <button className="btn btn-primary auth-btn" type="submit" disabled={loading || !audioBlob}>
            {loading ? 'Creating account...' : 'Create Account'}
          </button>
        </form>

        <p className="auth-link">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}