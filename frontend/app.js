/**
 * Thinking Partner - Minimal Frontend
 * Clean, focused interface for capturing thoughts
 */

// State
const state = {
    isSessionActive: false,
    sessionId: null,
    documentId: null,
    ws: null,
    wsReconnectAttempts: 0,
    maxReconnectAttempts: 5,
    mediaRecorder: null,
    audioStream: null,
    isRecording: false,
    transcript: '',
    interimTranscript: '',
    document: '',
    aiResponses: [],
    showTranscript: false,
};

// DOM Elements
const elements = {
    sessionBtn: document.getElementById('sessionBtn'),
    exportBtn: document.getElementById('exportBtn'),
    textInput: document.getElementById('textInput'),
    documentTitle: document.getElementById('documentTitle'),
    notesContent: document.getElementById('notesContent'),
    aiResponses: document.getElementById('aiResponses'),
    transcriptSection: document.getElementById('transcriptSection'),
    transcriptContent: document.getElementById('transcriptContent'),
    transcriptToggle: document.getElementById('transcriptToggle'),
    hideTranscriptBtn: document.getElementById('hideTranscriptBtn'),
    modeIndicator: document.getElementById('modeIndicator'),
    stopIndicator: document.getElementById('stopIndicator'),
    errorToast: document.getElementById('errorToast'),
    errorMessage: document.getElementById('errorMessage'),
    closeToast: document.getElementById('closeToast'),
    exportModal: document.getElementById('exportModal'),
    modalBackdrop: document.getElementById('modalBackdrop'),
    closeModal: document.getElementById('closeModal'),
    exportPreview: document.getElementById('exportPreview'),
    copyExportBtn: document.getElementById('copyExportBtn'),
    downloadExportBtn: document.getElementById('downloadExportBtn'),
    backBtn: document.getElementById('backBtn'),
};

// WebSocket
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        state.wsReconnectAttempts = 0;
        updateStatus(true);
    };

    state.ws.onclose = () => {
        if (state.isSessionActive && state.wsReconnectAttempts < state.maxReconnectAttempts) {
            state.wsReconnectAttempts++;
            const delay = Math.pow(2, state.wsReconnectAttempts) * 1000;
            setTimeout(connectWebSocket, delay);
        } else if (state.wsReconnectAttempts >= state.maxReconnectAttempts) {
            showError('Connection lost. Please refresh.');
            endSession();
        }
        updateStatus(false);
    };

    state.ws.onerror = () => {
        showError('Connection error');
    };

    state.ws.onmessage = (event) => {
        try {
            handleMessage(JSON.parse(event.data));
        } catch (e) {
            console.error('Parse error:', e);
        }
    };
}

function sendMessage(message) {
    if (state.ws?.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify(message));
    }
}

function handleMessage(message) {
    switch (message.type) {
        case 'session_started':
            state.sessionId = message.session_id;
            state.documentId = message.document_id;
            elements.exportBtn.disabled = false;
            startAudioCapture();
            if (message.document) updateDocument(message.document);
            break;

        case 'session_ended':
            if (message.final_document) updateDocument(message.final_document);
            break;

        case 'transcript':
            handleTranscript(message);
            break;

        case 'ai_response':
            addAIResponse(message.conversation);
            if (message.updated_document) updateDocument(message.updated_document);
            break;

        case 'document':
            updateDocument(message.markdown);
            break;

        case 'error':
            showError(message.message);
            break;
    }
}

// Session Management
async function startSession() {
    if (state.isSessionActive) return;

    try {
        await setupAudioCapture();
    } catch (e) {
        showError('Could not access microphone. You can still type.');
    }

    sendMessage({ type: 'start_session' });
    state.isSessionActive = true;
    elements.sessionBtn.classList.add('recording');
    elements.textInput.disabled = false;
    elements.documentTitle.textContent = 'Capturing thoughts...';
}

function endSession() {
    if (!state.isSessionActive) return;

    stopAudioCapture();
    if (state.ws?.readyState === WebSocket.OPEN) {
        sendMessage({ type: 'end_session' });
    }

    state.isSessionActive = false;
    elements.sessionBtn.classList.remove('recording');
    elements.textInput.disabled = true;
}

// Audio Capture
async function setupAudioCapture() {
    state.audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: 1,
            sampleRate: 16000,
            echoCancellation: true,
            noiseSuppression: true,
        }
    });

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

    state.mediaRecorder = new MediaRecorder(state.audioStream, {
        mimeType,
        audioBitsPerSecond: 16000,
    });

    state.mediaRecorder.ondataavailable = async (event) => {
        if (event.data.size > 0 && state.isRecording) {
            const base64 = await blobToBase64(event.data);
            sendMessage({ type: 'audio', data: base64 });
        }
    };
}

function startAudioCapture() {
    if (state.mediaRecorder?.state === 'inactive') {
        state.isRecording = true;
        state.mediaRecorder.start(250);
    }
}

function stopAudioCapture() {
    state.isRecording = false;
    if (state.mediaRecorder?.state !== 'inactive') {
        state.mediaRecorder.stop();
    }
    if (state.audioStream) {
        state.audioStream.getTracks().forEach(track => track.stop());
        state.audioStream = null;
    }
}

function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result.split(',')[1]);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
    });
}

// Transcript Handling
function handleTranscript(message) {
    if (message.is_final) {
        state.transcript += (state.transcript ? ' ' : '') + message.text;
        state.interimTranscript = '';
    } else {
        state.interimTranscript = message.text;
    }
    updateTranscriptDisplay();
}

function updateTranscriptDisplay() {
    if (!state.showTranscript) return;

    const final = state.transcript ? `<span>${escapeHtml(state.transcript)}</span>` : '';
    const interim = state.interimTranscript ? `<span class="interim"> ${escapeHtml(state.interimTranscript)}</span>` : '';

    if (final || interim) {
        elements.transcriptContent.innerHTML = final + interim;
    } else {
        elements.transcriptContent.innerHTML = '<p class="placeholder">Your words will appear here...</p>';
    }
}

function toggleTranscript() {
    state.showTranscript = !state.showTranscript;
    elements.transcriptSection.classList.toggle('hidden', !state.showTranscript);
    elements.transcriptToggle.classList.toggle('active', state.showTranscript);
    if (state.showTranscript) {
        updateTranscriptDisplay();
    }
}

// UI Updates
function updateStatus(connected) {
    const dot = elements.modeIndicator.querySelector('.status-dot');
    if (connected) {
        dot.classList.add('active');
    } else {
        dot.classList.remove('active');
    }
}

function updateDocument(markdown) {
    state.document = markdown;

    if (markdown?.trim()) {
        // Extract title from first heading or use default
        const titleMatch = markdown.match(/^#\s+(.+)$/m);
        if (titleMatch) {
            elements.documentTitle.textContent = titleMatch[1];
        }

        elements.notesContent.innerHTML = formatMarkdown(markdown);
    } else {
        elements.notesContent.innerHTML = '<p class="placeholder">Organized notes will appear here...</p>';
    }
}

function addAIResponse(response) {
    if (!response) return;

    state.aiResponses.push({
        text: response,
        timestamp: new Date(),
    });

    // Remove placeholder if present
    const placeholder = elements.aiResponses.querySelector('.placeholder');
    if (placeholder) placeholder.remove();

    // Create response element
    const responseEl = document.createElement('div');
    responseEl.className = 'ai-response-item';

    const contentEl = document.createElement('div');
    contentEl.innerHTML = formatMarkdown(response);

    const timeEl = document.createElement('div');
    timeEl.className = 'response-time';
    timeEl.textContent = formatTime(new Date());

    responseEl.appendChild(contentEl);
    responseEl.appendChild(timeEl);
    elements.aiResponses.appendChild(responseEl);

    // Scroll to latest response
    responseEl.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function showError(message) {
    elements.errorMessage.textContent = message;
    elements.errorToast.classList.remove('hidden');
    setTimeout(() => elements.errorToast.classList.add('hidden'), 5000);
}

// Export
async function openExportModal() {
    if (!state.documentId) {
        showError('No document to export');
        return;
    }

    try {
        const response = await fetch(`/api/documents/${state.documentId}/export`);
        if (!response.ok) throw new Error('Failed to fetch');

        const data = await response.json();
        elements.exportPreview.value = data.markdown;
        elements.exportModal.classList.remove('hidden');
        elements.downloadExportBtn.dataset.filename = data.filename;
    } catch (e) {
        showError('Failed to export');
    }
}

function closeExportModal() {
    elements.exportModal.classList.add('hidden');
}

async function copyToClipboard() {
    try {
        await navigator.clipboard.writeText(elements.exportPreview.value);
        elements.copyExportBtn.textContent = 'Copied!';
        setTimeout(() => elements.copyExportBtn.textContent = 'Copy', 2000);
    } catch (e) {
        showError('Failed to copy');
    }
}

function downloadMarkdown() {
    const content = elements.exportPreview.value;
    const filename = elements.downloadExportBtn.dataset.filename || 'notes.md';

    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// Utilities
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatMarkdown(text) {
    if (!text) return '';

    let escaped = escapeHtml(text);

    return escaped
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^# (.+)$/gm, '')  // Remove top-level heading (used for title)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/- \[ \] (.+)$/gm, '<li>$1</li>')
        .replace(/- \[x\] (.+)$/gm, '<li><strong>$1</strong></li>')
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>');
}

function sendTextInput() {
    const text = elements.textInput.value.trim();
    if (!text) return;

    sendMessage({ type: 'text', content: text });
    elements.textInput.value = '';
}

// Event Listeners
elements.sessionBtn.addEventListener('click', () => {
    state.isSessionActive ? endSession() : startSession();
});

elements.exportBtn.addEventListener('click', openExportModal);

elements.textInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendTextInput();
});

elements.closeToast.addEventListener('click', () => {
    elements.errorToast.classList.add('hidden');
});

elements.closeModal.addEventListener('click', closeExportModal);
elements.modalBackdrop.addEventListener('click', closeExportModal);
elements.copyExportBtn.addEventListener('click', copyToClipboard);
elements.downloadExportBtn.addEventListener('click', downloadMarkdown);

elements.transcriptToggle.addEventListener('click', toggleTranscript);
elements.hideTranscriptBtn.addEventListener('click', toggleTranscript);

elements.backBtn.addEventListener('click', () => {
    if (state.isSessionActive) {
        endSession();
    }
    // Reset view
    state.transcript = '';
    state.interimTranscript = '';
    state.document = '';
    state.aiResponses = [];
    elements.documentTitle.textContent = 'New Session';
    elements.aiResponses.innerHTML = '<p class="placeholder">AI responses will appear here as you think out loud...</p>';
    elements.notesContent.innerHTML = '<p class="placeholder">Organized notes will appear here...</p>';
    elements.transcriptContent.innerHTML = '<p class="placeholder">Your words will appear here...</p>';
});

// Keep-alive
setInterval(() => {
    if (state.ws?.readyState === WebSocket.OPEN && state.isSessionActive) {
        sendMessage({ type: 'ping' });
    }
}, 30000);

// Initialize
document.addEventListener('DOMContentLoaded', connectWebSocket);

document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && state.isSessionActive) {
        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
            connectWebSocket();
        }
    }
});

window.addEventListener('beforeunload', (e) => {
    if (state.isSessionActive) {
        e.preventDefault();
        e.returnValue = 'You have an active session. Leave?';
    }
});
