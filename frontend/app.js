/**
 * Thinking Partner - Frontend Application
 *
 * Handles:
 * - WebSocket connection to backend
 * - Audio capture from microphone
 * - Real-time UI updates
 * - Document display and export
 *
 * Audio Flow:
 * 1. User grants microphone permission
 * 2. MediaRecorder captures audio in chunks (every 250ms)
 * 3. Audio chunks are base64 encoded and sent via WebSocket
 * 4. Backend transcribes and returns results
 * 5. UI updates with transcript and AI responses
 */

// ============================================================================
// State Management
// ============================================================================

const state = {
    // Session state
    isSessionActive: false,
    sessionId: null,
    documentId: null,

    // WebSocket
    ws: null,
    wsReconnectAttempts: 0,
    maxReconnectAttempts: 5,

    // Audio
    mediaRecorder: null,
    audioStream: null,
    isRecording: false,

    // Content
    transcript: '',
    interimTranscript: '',
    document: '',
    aiResponses: [],

    // UI
    wordCount: 0,
};

// ============================================================================
// DOM Elements
// ============================================================================

const elements = {
    // Buttons
    sessionBtn: document.getElementById('sessionBtn'),
    exportBtn: document.getElementById('exportBtn'),
    sendTextBtn: document.getElementById('sendTextBtn'),
    toggleDocBtn: document.getElementById('toggleDocBtn'),
    copyTranscriptBtn: document.getElementById('copyTranscriptBtn'),
    copyAiBtn: document.getElementById('copyAiBtn'),
    copyDocBtn: document.getElementById('copyDocBtn'),

    // Inputs
    textInput: document.getElementById('textInput'),

    // Status indicators
    sessionStatus: document.getElementById('sessionStatus'),
    recordingIndicator: document.getElementById('recordingIndicator'),
    processingIndicator: document.getElementById('processingIndicator'),
    transcriptBadge: document.getElementById('transcriptBadge'),

    // Content areas
    transcriptContent: document.getElementById('transcriptContent'),
    aiResponseContent: document.getElementById('aiResponseContent'),
    documentContent: document.getElementById('documentContent'),

    // Toast
    errorToast: document.getElementById('errorToast'),
    errorMessage: document.getElementById('errorMessage'),
    closeToast: document.getElementById('closeToast'),

    // Export modal
    exportModal: document.getElementById('exportModal'),
    modalBackdrop: document.getElementById('modalBackdrop'),
    closeModal: document.getElementById('closeModal'),
    exportPreview: document.getElementById('exportPreview'),
    copyExportBtn: document.getElementById('copyExportBtn'),
    downloadExportBtn: document.getElementById('downloadExportBtn'),
};

// ============================================================================
// WebSocket Management
// ============================================================================

/**
 * Connect to the WebSocket server.
 * Handles connection, reconnection, and message routing.
 */
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    console.log('Connecting to WebSocket:', wsUrl);
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        console.log('WebSocket connected');
        state.wsReconnectAttempts = 0;
        updateSessionStatus('connected', 'Connected - Ready to start');
    };

    state.ws.onclose = (event) => {
        console.log('WebSocket closed:', event.code, event.reason);

        if (state.isSessionActive) {
            // Attempt reconnection if session was active
            if (state.wsReconnectAttempts < state.maxReconnectAttempts) {
                state.wsReconnectAttempts++;
                const delay = Math.pow(2, state.wsReconnectAttempts) * 1000;
                console.log(`Reconnecting in ${delay}ms (attempt ${state.wsReconnectAttempts})`);
                updateSessionStatus('reconnecting', `Reconnecting... (${state.wsReconnectAttempts}/${state.maxReconnectAttempts})`);
                setTimeout(connectWebSocket, delay);
            } else {
                showError('Connection lost. Please refresh the page.');
                endSession();
            }
        } else {
            updateSessionStatus('disconnected', 'Disconnected');
        }
    };

    state.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        showError('Connection error. Please check your network.');
    };

    state.ws.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleWebSocketMessage(message);
        } catch (e) {
            console.error('Failed to parse WebSocket message:', e);
        }
    };
}

/**
 * Handle incoming WebSocket messages.
 * Routes messages to appropriate handlers based on type.
 */
function handleWebSocketMessage(message) {
    console.log('WS message:', message.type, message);

    switch (message.type) {
        case 'session_started':
            handleSessionStarted(message);
            break;

        case 'session_ended':
            handleSessionEnded(message);
            break;

        case 'transcript':
            handleTranscript(message);
            break;

        case 'pause_detected':
            handlePauseDetected(message);
            break;

        case 'processing':
            handleProcessingStatus(message);
            break;

        case 'ai_response':
            handleAIResponse(message);
            break;

        case 'document':
            handleDocumentUpdate(message);
            break;

        case 'error':
            showError(message.message);
            break;

        case 'pong':
            // Keep-alive response, ignore
            break;

        default:
            console.warn('Unknown message type:', message.type);
    }
}

/**
 * Send a message through the WebSocket.
 */
function sendMessage(message) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify(message));
    } else {
        console.error('WebSocket not connected');
        showError('Not connected to server');
    }
}

// ============================================================================
// Session Management
// ============================================================================

/**
 * Start a new thinking session.
 */
async function startSession() {
    if (state.isSessionActive) {
        return;
    }

    // Request microphone permission
    try {
        await setupAudioCapture();
    } catch (e) {
        console.error('Microphone setup failed:', e);
        showError('Could not access microphone. You can still type your thoughts.');
    }

    // Send start session message
    sendMessage({ type: 'start_session' });

    // Update UI state
    state.isSessionActive = true;
    elements.sessionBtn.innerHTML = '<span class="icon">⏹️</span> End Session';
    elements.sessionBtn.classList.add('btn-danger');
    elements.sessionBtn.classList.remove('btn-primary');
    elements.textInput.disabled = false;
    elements.sendTextBtn.disabled = false;

    updateSessionStatus('active', 'Session active');
}

/**
 * End the current thinking session.
 */
function endSession() {
    if (!state.isSessionActive && !state.sessionId) {
        return;
    }

    // Stop audio capture
    stopAudioCapture();

    // Send end session message
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        sendMessage({ type: 'end_session' });
    }

    // Reset state
    state.isSessionActive = false;
    state.isRecording = false;

    // Update UI
    elements.sessionBtn.innerHTML = '<span class="icon">🎙️</span> Start Thinking Session';
    elements.sessionBtn.classList.remove('btn-danger');
    elements.sessionBtn.classList.add('btn-primary');
    elements.textInput.disabled = true;
    elements.sendTextBtn.disabled = true;
    elements.recordingIndicator.classList.add('hidden');

    updateSessionStatus('ended', 'Session ended');
}

/**
 * Handle session started confirmation from server.
 */
function handleSessionStarted(message) {
    state.sessionId = message.session_id;
    state.documentId = message.document_id;

    console.log('Session started:', state.sessionId);

    // Enable export button
    elements.exportBtn.disabled = false;

    // Start audio recording
    startAudioCapture();

    // Show recording indicator
    elements.recordingIndicator.classList.remove('hidden');

    // Update document if provided
    if (message.document) {
        updateDocumentDisplay(message.document);
    }

    // Clear previous content
    state.transcript = '';
    state.interimTranscript = '';
    state.aiResponses = [];
    elements.transcriptContent.innerHTML = '<p class="placeholder-text">Your thoughts will appear here as you speak...</p>';
    elements.aiResponseContent.innerHTML = '<p class="placeholder-text">AI responses will appear here...</p>';
}

/**
 * Handle session ended confirmation from server.
 */
function handleSessionEnded(message) {
    console.log('Session ended:', message);

    // Update document with final version
    if (message.final_document) {
        updateDocumentDisplay(message.final_document);
    }

    // Keep export enabled so user can export after session
}

// ============================================================================
// Audio Capture
// ============================================================================

/**
 * Set up audio capture from microphone.
 * Uses MediaRecorder API to capture audio in chunks.
 */
async function setupAudioCapture() {
    // Request microphone access
    state.audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: 1,
            sampleRate: 16000,
            echoCancellation: true,
            noiseSuppression: true,
        }
    });

    // Create MediaRecorder
    // Use webm/opus for best compatibility, backend will handle conversion
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

    state.mediaRecorder = new MediaRecorder(state.audioStream, {
        mimeType: mimeType,
        audioBitsPerSecond: 16000,
    });

    // Handle audio data chunks
    state.mediaRecorder.ondataavailable = async (event) => {
        if (event.data.size > 0 && state.isRecording) {
            // Convert blob to base64 and send
            const base64 = await blobToBase64(event.data);
            sendMessage({
                type: 'audio',
                data: base64,
            });
        }
    };

    state.mediaRecorder.onerror = (error) => {
        console.error('MediaRecorder error:', error);
        showError('Audio recording error');
    };
}

/**
 * Start capturing audio.
 */
function startAudioCapture() {
    if (state.mediaRecorder && state.mediaRecorder.state === 'inactive') {
        state.isRecording = true;
        // Capture audio in 250ms chunks for low latency
        state.mediaRecorder.start(250);
        console.log('Audio capture started');
    }
}

/**
 * Stop capturing audio.
 */
function stopAudioCapture() {
    state.isRecording = false;

    if (state.mediaRecorder && state.mediaRecorder.state !== 'inactive') {
        state.mediaRecorder.stop();
        console.log('Audio capture stopped');
    }

    if (state.audioStream) {
        state.audioStream.getTracks().forEach(track => track.stop());
        state.audioStream = null;
    }
}

/**
 * Convert a Blob to base64 string.
 */
function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
            // Remove data URL prefix (e.g., "data:audio/webm;base64,")
            const base64 = reader.result.split(',')[1];
            resolve(base64);
        };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
    });
}

// ============================================================================
// Message Handlers
// ============================================================================

/**
 * Handle transcript updates from server.
 */
function handleTranscript(message) {
    const text = message.text;
    const isFinal = message.is_final;

    if (isFinal) {
        // Add to final transcript
        state.transcript += (state.transcript ? ' ' : '') + text;
        state.interimTranscript = '';
    } else {
        // Update interim transcript
        state.interimTranscript = text;
    }

    // Update UI
    updateTranscriptDisplay();
}

/**
 * Handle pause detected notification.
 */
function handlePauseDetected(message) {
    console.log('Pause detected, processing:', message.transcript);
    // Visual feedback could be added here
}

/**
 * Handle AI processing status updates.
 */
function handleProcessingStatus(message) {
    if (message.status === 'started') {
        elements.processingIndicator.classList.remove('hidden');
    } else {
        elements.processingIndicator.classList.add('hidden');
    }
}

/**
 * Handle AI response from server.
 */
function handleAIResponse(message) {
    // Add to responses list
    state.aiResponses.push({
        conversation: message.conversation,
        timestamp: new Date(),
    });

    // Update AI response display
    updateAIResponseDisplay(message.conversation);

    // Update document
    if (message.updated_document) {
        updateDocumentDisplay(message.updated_document);
    }
}

/**
 * Handle document update from server.
 */
function handleDocumentUpdate(message) {
    updateDocumentDisplay(message.markdown);
}

// ============================================================================
// UI Updates
// ============================================================================

/**
 * Update the session status indicator.
 */
function updateSessionStatus(status, text) {
    const indicator = elements.sessionStatus.querySelector('.status-indicator');
    const label = elements.sessionStatus.querySelector('span');

    indicator.className = 'status-indicator ' + status;
    label.textContent = text;
}

/**
 * Update the transcript display.
 */
function updateTranscriptDisplay() {
    const finalHtml = state.transcript
        ? `<p class="transcript-text">${escapeHtml(state.transcript)}</p>`
        : '';

    const interimHtml = state.interimTranscript
        ? `<p class="transcript-interim">${escapeHtml(state.interimTranscript)}</p>`
        : '';

    if (finalHtml || interimHtml) {
        elements.transcriptContent.innerHTML = finalHtml + interimHtml;
    } else {
        elements.transcriptContent.innerHTML = '<p class="placeholder-text">Your thoughts will appear here as you speak...</p>';
    }

    // Update word count
    const words = state.transcript.split(/\s+/).filter(w => w.length > 0);
    state.wordCount = words.length;
    elements.transcriptBadge.textContent = `${state.wordCount} word${state.wordCount !== 1 ? 's' : ''}`;

    // Auto-scroll to bottom
    elements.transcriptContent.scrollTop = elements.transcriptContent.scrollHeight;
}

/**
 * Update the AI response display.
 */
function updateAIResponseDisplay(response) {
    // Create response element
    const responseEl = document.createElement('div');
    responseEl.className = 'ai-response-item';
    responseEl.innerHTML = `
        <div class="response-content">${formatMarkdown(response)}</div>
        <div class="response-time">${formatTime(new Date())}</div>
    `;

    // Remove placeholder if present
    const placeholder = elements.aiResponseContent.querySelector('.placeholder-text');
    if (placeholder) {
        placeholder.remove();
    }

    // Add new response
    elements.aiResponseContent.appendChild(responseEl);

    // Auto-scroll to bottom
    elements.aiResponseContent.scrollTop = elements.aiResponseContent.scrollHeight;
}

/**
 * Update the document display.
 */
function updateDocumentDisplay(markdown) {
    state.document = markdown;

    if (markdown && markdown.trim()) {
        elements.documentContent.innerHTML = `<div class="markdown-content">${formatMarkdown(markdown)}</div>`;
    } else {
        elements.documentContent.innerHTML = '<p class="placeholder-text">Your thoughts will be organized here as sections...</p>';
    }
}

/**
 * Show an error toast.
 */
function showError(message) {
    elements.errorMessage.textContent = message;
    elements.errorToast.classList.remove('hidden');

    // Auto-hide after 5 seconds
    setTimeout(() => {
        elements.errorToast.classList.add('hidden');
    }, 5000);
}

// ============================================================================
// Export Functionality
// ============================================================================

/**
 * Open the export modal.
 */
async function openExportModal() {
    if (!state.documentId) {
        showError('No document to export');
        return;
    }

    try {
        // Fetch export data from API
        const response = await fetch(`/api/documents/${state.documentId}/export`);
        if (!response.ok) {
            throw new Error('Failed to fetch document');
        }

        const data = await response.json();
        elements.exportPreview.value = data.markdown;
        elements.exportModal.classList.remove('hidden');

        // Store filename for download
        elements.downloadExportBtn.dataset.filename = data.filename;

    } catch (e) {
        console.error('Export error:', e);
        showError('Failed to load document for export');
    }
}

/**
 * Close the export modal.
 */
function closeExportModal() {
    elements.exportModal.classList.add('hidden');
}

/**
 * Copy export content to clipboard.
 */
async function copyToClipboard() {
    try {
        await navigator.clipboard.writeText(elements.exportPreview.value);
        elements.copyExportBtn.innerHTML = '<span class="icon">✓</span> Copied!';
        setTimeout(() => {
            elements.copyExportBtn.innerHTML = '<span class="icon">📋</span> Copy to Clipboard';
        }, 2000);
    } catch (e) {
        showError('Failed to copy to clipboard');
    }
}

/**
 * Download the document as a markdown file.
 */
function downloadMarkdown() {
    const content = elements.exportPreview.value;
    const filename = elements.downloadExportBtn.dataset.filename || 'thinking-session.md';

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

// ============================================================================
// Utility Functions
// ============================================================================

/**
 * Escape HTML special characters.
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Basic markdown formatting.
 * SECURITY: Escapes HTML first to prevent XSS attacks.
 */
function formatMarkdown(text) {
    if (!text) return '';

    // SECURITY: Escape HTML first to prevent XSS
    let escaped = escapeHtml(text);

    return escaped
        // Headers (using escaped &gt; etc won't match, so we use word boundaries)
        .replace(/^### (.+)$/gm, '<h4>$1</h4>')
        .replace(/^## (.+)$/gm, '<h3>$1</h3>')
        .replace(/^# (.+)$/gm, '<h2>$1</h2>')
        // Bold
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        // Italic
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        // Code
        .replace(/`(.+?)`/g, '<code>$1</code>')
        // Checkboxes
        .replace(/- \[ \] (.+)$/gm, '<div class="checkbox"><input type="checkbox" disabled> $1</div>')
        .replace(/- \[x\] (.+)$/gm, '<div class="checkbox"><input type="checkbox" checked disabled> $1</div>')
        // Bullet points
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        // Wrap consecutive list items
        .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
        // Paragraphs (double newlines)
        .replace(/\n\n/g, '</p><p>')
        // Single newlines to breaks
        .replace(/\n/g, '<br>');
}

/**
 * Format time for display.
 */
function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ============================================================================
// Text Input Handling
// ============================================================================

/**
 * Send text input as a thought.
 */
function sendTextInput() {
    const text = elements.textInput.value.trim();
    if (!text) return;

    sendMessage({
        type: 'text',
        content: text,
    });

    elements.textInput.value = '';
}

// ============================================================================
// Event Listeners
// ============================================================================

// Session button
elements.sessionBtn.addEventListener('click', () => {
    if (state.isSessionActive) {
        endSession();
    } else {
        startSession();
    }
});

// Export button
elements.exportBtn.addEventListener('click', openExportModal);

// Text input
elements.textInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        sendTextInput();
    }
});

elements.sendTextBtn.addEventListener('click', sendTextInput);

// Toast close
elements.closeToast.addEventListener('click', () => {
    elements.errorToast.classList.add('hidden');
});

// Export modal
elements.closeModal.addEventListener('click', closeExportModal);
elements.modalBackdrop.addEventListener('click', closeExportModal);
elements.copyExportBtn.addEventListener('click', copyToClipboard);
elements.downloadExportBtn.addEventListener('click', downloadMarkdown);

// Toggle document view
elements.toggleDocBtn.addEventListener('click', () => {
    const panel = document.querySelector('.document-section');
    panel.classList.toggle('collapsed');
    elements.toggleDocBtn.querySelector('span').textContent =
        panel.classList.contains('collapsed') ? '📄' : '📑';
});

// Copy buttons for each panel
async function copyPanelContent(button, content) {
    try {
        await navigator.clipboard.writeText(content);
        const originalText = button.querySelector('span').textContent;
        button.querySelector('span').textContent = '✓';
        button.classList.add('copied');
        setTimeout(() => {
            button.querySelector('span').textContent = originalText;
            button.classList.remove('copied');
        }, 1500);
    } catch (e) {
        showError('Failed to copy to clipboard');
    }
}

elements.copyTranscriptBtn.addEventListener('click', () => {
    copyPanelContent(elements.copyTranscriptBtn, state.transcript || 'No transcript yet');
});

elements.copyAiBtn.addEventListener('click', () => {
    // Get all AI responses as text
    const responses = state.aiResponses.map(r => r.conversation).join('\n\n---\n\n');
    copyPanelContent(elements.copyAiBtn, responses || 'No AI responses yet');
});

elements.copyDocBtn.addEventListener('click', () => {
    copyPanelContent(elements.copyDocBtn, state.document || 'No notes yet');
});

// Keep-alive ping every 30 seconds
setInterval(() => {
    if (state.ws && state.ws.readyState === WebSocket.OPEN && state.isSessionActive) {
        sendMessage({ type: 'ping' });
    }
}, 30000);

// ============================================================================
// Initialization
// ============================================================================

// Connect to WebSocket on page load
document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
});

// Handle page visibility changes
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && state.isSessionActive) {
        // Reconnect if needed when page becomes visible
        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
            connectWebSocket();
        }
    }
});

// Warn before leaving with active session
window.addEventListener('beforeunload', (e) => {
    if (state.isSessionActive) {
        e.preventDefault();
        e.returnValue = 'You have an active session. Are you sure you want to leave?';
    }
});
