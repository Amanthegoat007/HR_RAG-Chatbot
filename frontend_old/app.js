/* ============================================================================
   HR Knowledge Chatbot — Frontend App Logic
   Handles: login → JWT storage → chat → SSE streaming → source display
   API: POST /auth/login, POST /query (SSE)
   ============================================================================ */

(() => {
    'use strict';

    // ─── State ───
    let authToken = null;
    let userRole = null;
    let isStreaming = false;

    // ─── DOM Refs ───
    const loginScreen = document.getElementById('login-screen');
    const chatScreen = document.getElementById('chat-screen');
    const loginForm = document.getElementById('login-form');
    const loginBtn = document.getElementById('login-btn');
    const loginError = document.getElementById('login-error');
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');
    const sendBtn = document.getElementById('send-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const userBadge = document.getElementById('user-badge');
    const connStatus = document.getElementById('connection-status');

    // ─── Init ───
    function init() {
        // Check for saved token
        const saved = sessionStorage.getItem('hr_auth');
        if (saved) {
            try {
                const data = JSON.parse(saved);
                authToken = data.token;
                userRole = data.role;
                showChat();
            } catch (e) { sessionStorage.removeItem('hr_auth'); }
        }

        // Event listeners
        loginForm.addEventListener('submit', handleLogin);
        chatForm.addEventListener('submit', handleSend);
        logoutBtn.addEventListener('click', handleLogout);

        // Auto-resize textarea
        chatInput.addEventListener('input', () => {
            chatInput.style.height = 'auto';
            chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
            sendBtn.disabled = !chatInput.value.trim();
        });

        // Enter to send, Shift+Enter for newline
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (chatInput.value.trim() && !isStreaming) {
                    chatForm.dispatchEvent(new Event('submit'));
                }
            }
        });

        // Example questions
        document.querySelectorAll('.example-q').forEach(btn => {
            btn.addEventListener('click', () => {
                chatInput.value = btn.dataset.q;
                sendBtn.disabled = false;
                chatForm.dispatchEvent(new Event('submit'));
            });
        });
    }

    // ─── Login ───
    async function handleLogin(e) {
        e.preventDefault();
        const username = document.getElementById('username').value.trim();
        const password = document.getElementById('password').value;

        loginBtn.disabled = true;
        loginBtn.querySelector('.btn-text').textContent = 'Signing in...';
        loginBtn.querySelector('.btn-loader').hidden = false;
        loginError.hidden = true;

        try {
            const res = await fetch('/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Invalid credentials');
            }

            const data = await res.json();
            authToken = data.access_token;
            userRole = data.role;

            sessionStorage.setItem('hr_auth', JSON.stringify({ token: authToken, role: userRole }));
            showChat();
        } catch (err) {
            loginError.textContent = err.message;
            loginError.hidden = false;
        } finally {
            loginBtn.disabled = false;
            loginBtn.querySelector('.btn-text').textContent = 'Sign In';
            loginBtn.querySelector('.btn-loader').hidden = true;
        }
    }

    // ─── Logout ───
    function handleLogout() {
        authToken = null;
        userRole = null;
        sessionStorage.removeItem('hr_auth');
        chatMessages.innerHTML = '';
        loginScreen.classList.add('active');
        chatScreen.classList.remove('active');
        document.getElementById('username').value = '';
        document.getElementById('password').value = '';
    }

    // ─── Show Chat ───
    function showChat() {
        loginScreen.classList.remove('active');
        chatScreen.classList.add('active');
        userBadge.textContent = userRole === 'admin' ? '🔑 Admin' : '👤 User';
        chatInput.focus();
    }

    // ─── Send Message ───
    async function handleSend(e) {
        e.preventDefault();
        const question = chatInput.value.trim();
        if (!question || isStreaming) return;

        // Clear welcome message
        const welcome = chatMessages.querySelector('.welcome-message');
        if (welcome) welcome.remove();

        // Add user bubble
        addMessage('user', question);

        // Reset input
        chatInput.value = '';
        chatInput.style.height = 'auto';
        sendBtn.disabled = true;
        isStreaming = true;

        // Add bot placeholder with typing indicator
        const botMsg = addMessage('bot', '', true);
        const contentEl = botMsg.querySelector('.message-content');

        try {
            await streamQuery(question, contentEl, botMsg);
        } catch (err) {
            contentEl.classList.remove('streaming');
            contentEl.textContent = 'Sorry, something went wrong. Please try again.';
            botMsg.classList.add('error');
            console.error('Query error:', err);
        } finally {
            isStreaming = false;
            sendBtn.disabled = !chatInput.value.trim();
        }
    }

    // ─── Stream Query via SSE ───
    async function streamQuery(question, contentEl, botMsg) {
        // We use fetch + ReadableStream instead of EventSource
        // because EventSource doesn't support POST or custom headers
        const res = await fetch('/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`,
                'Accept': 'text/event-stream',
            },
            body: JSON.stringify({ query: question }),
        });

        if (res.status === 401) {
            handleLogout();
            loginError.textContent = 'Session expired. Please sign in again.';
            loginError.hidden = false;
            return;
        }

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Server error' }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        // Remove typing indicator
        const typingEl = contentEl.querySelector('.typing-indicator');
        if (typingEl) typingEl.remove();
        contentEl.classList.add('streaming');

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullAnswer = '';
        let sources = [];

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Parse SSE events from buffer
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep incomplete last line

            let eventType = '';
            let eventData = '';

            for (const line of lines) {
                if (line.startsWith('event:')) {
                    eventType = line.slice(6).trim();
                } else if (line.startsWith('data:')) {
                    eventData = line.slice(5).trim();

                    if (eventType && eventData) {
                        try {
                            const parsed = JSON.parse(eventData);

                            if (eventType === 'token') {
                                fullAnswer += parsed.token;
                                contentEl.textContent = fullAnswer;
                                scrollToBottom();
                            } else if (eventType === 'sources') {
                                sources = parsed.sources || [];
                            } else if (eventType === 'error') {
                                contentEl.classList.remove('streaming');
                                contentEl.textContent = parsed.error || 'An error occurred.';
                                botMsg.classList.add('error');
                                return;
                            } else if (eventType === 'done') {
                                // Stream complete
                            }
                        } catch (parseErr) {
                            // Ignore parse errors for incomplete data
                        }
                    }
                    eventType = '';
                    eventData = '';
                } else if (line === '') {
                    // End of event block
                    eventType = '';
                    eventData = '';
                }
            }
        }

        // Remove streaming cursor
        contentEl.classList.remove('streaming');

        // Add sources panel if we received any
        if (sources.length > 0) {
            const sourcesHtml = buildSourcesHtml(sources);
            contentEl.insertAdjacentHTML('afterend', sourcesHtml);
        }

        scrollToBottom();
    }

    // ─── Build Sources HTML ───
    function buildSourcesHtml(sources) {
        const items = sources.map(s => {
            const name = s.filename || 'Unknown document';
            const section = s.section ? ` › ${s.section}` : '';
            const page = s.page_number ? ` (p. ${s.page_number})` : '';
            const score = s.score ? `${Math.round(s.score * 100)}%` : '';
            return `
                <div class="source-item">
                    <svg class="source-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/>
                    </svg>
                    <span>${name}${section}${page}</span>
                    ${score ? `<span class="source-score">${score}</span>` : ''}
                </div>`;
        }).join('');

        return `
            <div class="sources-container">
                <div class="sources-title">📚 Sources</div>
                ${items}
            </div>`;
    }

    // ─── Add Message Bubble ───
    function addMessage(role, text, showTyping = false) {
        const msg = document.createElement('div');
        msg.className = `message ${role}`;

        const avatarLabel = role === 'user' ? 'You' : 'AI';
        let contentHtml = text;

        if (showTyping) {
            contentHtml = `
                <div class="typing-indicator">
                    <span></span><span></span><span></span>
                </div>`;
        }

        msg.innerHTML = `
            <div class="message-avatar">${avatarLabel}</div>
            <div class="message-content">${contentHtml}</div>
        `;

        chatMessages.appendChild(msg);
        scrollToBottom();
        return msg;
    }

    // ─── Scroll ───
    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // ─── Start ───
    init();
})();
