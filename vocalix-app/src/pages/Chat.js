import React, { useState, useEffect, useRef } from 'react';
import api from '../api/api';
import './Chat.css';

const LANGUAGES = ['english', 'hindi', 'malayalam'];

export default function Chat({ user, onLogout }) {
  const [friends, setFriends] = useState([]);
  const [selectedFriend, setSelectedFriend] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState('');
  const [sourceLang, setSourceLang] = useState('english');
  const [targetLang, setTargetLang] = useState('english');
  const [cloneVoice, setCloneVoice] = useState(false);
  const [searchEmail, setSearchEmail] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [sending, setSending] = useState(false);
  const [searching, setSearching] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const messagesEnd = useRef(null);

  useEffect(() => { loadFriends(); }, []);
  useEffect(() => { if (selectedFriend) loadMessages(); }, [selectedFriend]);
  useEffect(() => { messagesEnd.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const loadFriends = async () => {
    const r = await api.get('/friends');
    setFriends(r.data);
  };

  const loadMessages = async () => {
    const r = await api.get(`/messages/${selectedFriend.id}`);
    setMessages(r.data);
  };

  const searchUsers = async () => {
    if (!searchEmail.trim()) return;
    setSearching(true);
    const r = await api.get(`/users/search?email=${searchEmail}`);
    setSearchResults(r.data);
    setSearching(false);
  };

  const addFriend = async (friendId) => {
    await api.post(`/friends/add/${friendId}`);
    await loadFriends();
    setShowSearch(false);
    setSearchEmail('');
    setSearchResults([]);
  };

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!text.trim() || !selectedFriend) return;
    setSending(true);
    try {
      const fd = new FormData();
      fd.append('receiver_id', selectedFriend.id);
      fd.append('text', text);
      fd.append('source_lang', sourceLang);
      fd.append('target_lang', targetLang);
      fd.append('clone_voice', cloneVoice ? 'true' : 'false');
      const r = await api.post('/messages/send', fd);
      setMessages(prev => [...prev, r.data]);
      setText('');
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to send message');
    }
    setSending(false);
  };

  return (
    <div className="chat-layout">
      {/* Sidebar */}
      <div className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <span className="logo-icon">◈</span>
            <span className="logo-text">Vocalix</span>
          </div>
          <div className="user-info">
            <div className="user-avatar">{user.name[0].toUpperCase()}</div>
            <div className="user-details">
              <span className="user-name">{user.name}</span>
              <span className="user-email">{user.email}</span>
            </div>
          </div>
          <button className="btn btn-ghost logout-btn" onClick={onLogout}>Sign out</button>
        </div>

        <div className="friends-header">
          <span>Messages</span>
          <button className="icon-btn" onClick={() => setShowSearch(!showSearch)} title="Add friend">+</button>
        </div>

        {/* Search Panel */}
        {showSearch && (
          <div className="search-panel fade-up">
            <div className="search-row">
              <input className="input" placeholder="Search by email..."
                value={searchEmail} onChange={e => setSearchEmail(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && searchUsers()} />
              <button className="btn btn-primary" onClick={searchUsers} disabled={searching}>
                {searching ? '...' : 'Search'}
              </button>
            </div>
            {searchResults.map(u => (
              <div key={u.id} className="search-result">
                <div className="result-avatar">{u.name[0].toUpperCase()}</div>
                <div className="result-info">
                  <span className="result-name">{u.name}</span>
                  <span className="result-email">{u.email}</span>
                </div>
                <button className="btn btn-primary" style={{fontSize:'0.8rem', padding:'0.4rem 0.8rem'}}
                  onClick={() => addFriend(u.id)}>Add</button>
              </div>
            ))}
            {searchResults.length === 0 && searchEmail && !searching && (
              <p className="no-results">No users found</p>
            )}
          </div>
        )}

        {/* Friends List */}
        <div className="friends-list">
          {friends.length === 0 && (
            <div className="no-friends">
              <p>No friends yet</p>
              <p className="no-friends-hint">Search for friends by email</p>
            </div>
          )}
          {friends.map(f => (
            <div key={f.id}
              className={`friend-item ${selectedFriend?.id === f.id ? 'active' : ''}`}
              onClick={() => setSelectedFriend(f)}>
              <div className="friend-avatar">{f.name[0].toUpperCase()}</div>
              <div className="friend-info">
                <span className="friend-name">{f.name}</span>
                <span className="friend-email">{f.email}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="chat-main">
        {!selectedFriend ? (
          <div className="chat-empty">
            <div className="empty-icon">◈</div>
            <h2>Select a conversation</h2>
            <p>Choose a friend from the sidebar to start chatting</p>
          </div>
        ) : (
          <>
            {/* Chat Header */}
            <div className="chat-header">
              <div className="chat-header-info">
                <div className="friend-avatar large">{selectedFriend.name[0].toUpperCase()}</div>
                <div>
                  <div className="chat-header-name">{selectedFriend.name}</div>
                  <div className="chat-header-email">{selectedFriend.email}</div>
                </div>
              </div>
            </div>

            {/* Messages */}
            <div className="messages-area">
              {messages.map(msg => (
                <MessageBubble key={msg.id} msg={msg} isMe={msg.sender_id === user.id} />
              ))}
              <div ref={messagesEnd} />
            </div>

            {/* Input Area */}
            <div className="input-area">
              {/* Language + Clone controls */}
              <div className="controls-row">
                <div className="lang-group">
                  <label>From</label>
                  <select className="lang-select" value={sourceLang} onChange={e => setSourceLang(e.target.value)}>
                    {LANGUAGES.map(l => <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>)}
                  </select>
                </div>
                <span className="lang-arrow">→</span>
                <div className="lang-group">
                  <label>To</label>
                  <select className="lang-select" value={targetLang} onChange={e => setTargetLang(e.target.value)}>
                    {LANGUAGES.map(l => <option key={l} value={l}>{l.charAt(0).toUpperCase() + l.slice(1)}</option>)}
                  </select>
                </div>
                <div className="clone-toggle">
                  <label className="toggle-label">
                    <input type="checkbox" checked={cloneVoice} onChange={e => setCloneVoice(e.target.checked)} />
                    <span className="toggle-slider" />
                    <span className="toggle-text">Voice Clone</span>
                  </label>
                </div>
              </div>

              {/* Message Input */}
              <form onSubmit={sendMessage} className="message-form">
                <textarea className="message-input input" placeholder="Type a message..."
                  value={text} onChange={e => setText(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(e); }}}
                  rows={1} />
                <button className="btn btn-primary send-btn" type="submit" disabled={sending || !text.trim()}>
                  {sending ? (cloneVoice ? '🎙️' : '...') : '↑'}
                </button>
              </form>

              {cloneVoice && (
                <p className="clone-notice">
                  🎙️ Voice clone is ON — your message will be sent as audio in your cloned voice
                </p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function MessageBubble({ msg, isMe }) {
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef(null);

  const playAudio = () => {
    if (!msg.audio_base64) return;
    if (!audioRef.current) {
      const blob = b64toBlob(msg.audio_base64, 'audio/wav');
      const url = URL.createObjectURL(blob);
      audioRef.current = new Audio(url);
      audioRef.current.onended = () => setPlaying(false);
    }
    if (playing) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setPlaying(false);
    } else {
      audioRef.current.play();
      setPlaying(true);
    }
  };

  return (
    <div className={`message-row ${isMe ? 'me' : 'them'}`}>
      {!isMe && <div className="msg-avatar">{msg.sender_name?.[0]?.toUpperCase()}</div>}
      <div className={`bubble ${isMe ? 'bubble-me' : 'bubble-them'}`}>
        <div className="bubble-text">{msg.text}</div>
        {msg.message_type === 'voice' && msg.audio_base64 && (
          <button className={`play-btn ${playing ? 'playing' : ''}`} onClick={playAudio}>
            {playing ? '⏸' : '▶'} Voice Message
          </button>
        )}
        <div className="bubble-meta">
          {msg.source_lang !== msg.target_lang && (
            <span className="lang-badge">{msg.source_lang} → {msg.target_lang}</span>
          )}
          <span className="msg-time">{formatTime(msg.created_at)}</span>
        </div>
      </div>
    </div>
  );
}

function b64toBlob(b64, type) {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type });
}

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}