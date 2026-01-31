# Thinking Partner

An AI-powered thinking partner web application for busy professionals. Talk through your thoughts via voice, get AI assistance with clarifying questions, and have your thoughts automatically organized into a structured document.

## Features

- **Voice-first interaction**: Speak freely, and your thoughts are transcribed in real-time
- **AI thinking partner**: Claude asks clarifying questions and helps you think deeper
- **Automatic organization**: Thoughts are organized by topic into a structured document
- **Export to Markdown**: Download your organized notes as a markdown file
- **Mobile-responsive**: Works on both desktop and mobile browsers

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Browser)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Audio Capture│  │  WebSocket   │  │    UI Components     │  │
│  │ (MediaRecorder)│ │   Client    │  │ (Transcript, Doc,AI) │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ WebSocket (audio, text, commands)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Backend (FastAPI)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Transcription│  │ AI Processor │  │  Document Manager    │  │
│  │   (Deepgram)  │  │   (Claude)   │  │  (Storage, Updates)  │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│                    ┌──────────────────┐                         │
│                    │    PostgreSQL    │                         │
│                    │  (Sessions, Docs)│                         │
│                    └──────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Docker and Docker Compose (for PostgreSQL)
- API Keys:
  - [Anthropic API Key](https://console.anthropic.com/) (required)
  - [Deepgram API Key](https://console.deepgram.com/) (for voice transcription)
  - [OpenAI API Key](https://platform.openai.com/) (optional, fallback for Whisper)

### 1. Clone and Setup

```bash
# Clone the repository
git clone <repository-url>
cd thoughtsAI

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your API keys
# Required:
#   ANTHROPIC_API_KEY=sk-ant-your-key-here
# For voice (at least one):
#   DEEPGRAM_API_KEY=your-deepgram-key-here
#   OPENAI_API_KEY=sk-your-openai-key-here
```

### 3. Start Database

```bash
# Start PostgreSQL with Docker
docker-compose up -d

# Verify it's running
docker-compose ps
```

### 4. Run the Application

```bash
# From the backend directory
cd backend
python main.py
```

The application will be available at `http://localhost:8000`

## Usage

1. **Open the app** in your browser (works best in Chrome/Edge for audio support)
2. **Click "Start Thinking Session"** to begin
3. **Allow microphone access** when prompted
4. **Start talking** - your words will be transcribed in real-time
5. **Pause naturally** - the AI will process your thought and respond with clarifying questions
6. **Continue thinking** - keep talking, the AI will organize your thoughts
7. **Check "Organized Notes"** - see how your thoughts are being structured
8. **Click "End Session"** when done
9. **Export** - click the export button to download your notes as markdown

### Tips for Best Results

- Speak naturally, as if explaining to a colleague
- Pause for 2+ seconds between thoughts to trigger AI processing
- If voice doesn't work, use the text input box as fallback
- Review the organized document periodically to see how thoughts are grouped

## Project Structure

```
thoughtsAI/
├── backend/
│   ├── main.py              # FastAPI app, WebSocket endpoint
│   ├── transcription.py     # Deepgram/Whisper integration
│   ├── ai_processor.py      # Claude API integration
│   ├── document_manager.py  # Document storage and updates
│   ├── database.py          # PostgreSQL models and operations
│   ├── prompts.py           # Claude system prompts
│   └── init.sql             # Database schema
├── frontend/
│   ├── index.html           # Main UI
│   ├── app.js               # WebSocket, audio capture, UI
│   └── styles.css           # Responsive styling
├── .env.example             # Environment template
├── docker-compose.yml       # PostgreSQL setup
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude |
| `DEEPGRAM_API_KEY` | No* | Deepgram API key for transcription |
| `OPENAI_API_KEY` | No* | OpenAI API key for Whisper fallback |
| `PORT` | No | Server port (default: 8000) |
| `HOST` | No | Server host (default: 0.0.0.0) |
| `PAUSE_THRESHOLD_MS` | No | Pause detection threshold (default: 2000) |
| `TRANSCRIPTION_PROVIDER` | No | "deepgram" or "whisper" (default: deepgram) |

*At least one transcription API key is required for voice input

### Transcription Providers

**Deepgram (Recommended)**
- Real-time streaming transcription
- Low latency (~300ms)
- Best for continuous speech

**OpenAI Whisper (Fallback)**
- Batch transcription every 2 seconds
- Higher latency but more robust
- Good for noisy environments

## API Endpoints

### REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve frontend |
| `/health` | GET | Health check |
| `/api/documents` | GET | List all documents |
| `/api/documents/{id}` | GET | Get specific document |
| `/api/documents/{id}/export` | GET | Export document as markdown |

### WebSocket Protocol

Connect to `/ws` and send JSON messages:

```javascript
// Start session
{ "type": "start_session" }
// or with existing document
{ "type": "start_session", "document_id": "uuid" }

// Send audio (base64 encoded)
{ "type": "audio", "data": "base64..." }

// Send text directly
{ "type": "text", "content": "My thought..." }

// End session
{ "type": "end_session" }

// Get current document
{ "type": "get_document" }

// Keep-alive
{ "type": "ping" }
```

Server responses:

```javascript
// Session started
{ "type": "session_started", "session_id": "...", "document_id": "..." }

// Transcript update
{ "type": "transcript", "text": "...", "is_final": true }

// AI response
{ "type": "ai_response", "conversation": "...", "document_updates": [...], "updated_document": "..." }

// Processing status
{ "type": "processing", "status": "started" | "completed" }

// Error
{ "type": "error", "message": "..." }
```

## Development

### Running in Development Mode

```bash
# Backend with auto-reload
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Or using Python directly
python main.py
```

### Database Management

```bash
# View database logs
docker-compose logs postgres

# Connect to database
docker-compose exec postgres psql -U postgres -d thinking_partner

# Reset database
docker-compose down -v
docker-compose up -d
```

### Testing Without Voice

If you don't have an OpenAI API key for Whisper, you can still test:
1. Start the application
2. Click "Start Thinking Session"
3. Use the text input box to type your thoughts
4. The AI will still respond and organize your thoughts

## Deploying to Railway

### One-Click Deploy

1. Fork this repository to your GitHub account
2. Go to [Railway](https://railway.app) and sign in with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your forked repository
5. Railway will auto-detect the configuration

### Configure Environment Variables

In your Railway project, add these environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `OPENAI_API_KEY` | Yes | Your OpenAI API key (for Whisper) |
| `TRANSCRIPTION_PROVIDER` | No | Set to "whisper" (default) |

### Add PostgreSQL Database

1. In your Railway project, click "New" → "Database" → "PostgreSQL"
2. Railway will automatically set the `DATABASE_URL` environment variable
3. The app will auto-create tables on first run

### Deploy

Railway will automatically deploy when you push to your repository.

Your app will be available at: `https://your-project-name.up.railway.app`

### Important Notes for Production

- Railway provides HTTPS automatically (required for microphone access)
- The free tier includes 500 hours/month and $5 credit
- WebSocket connections are fully supported
- Monitor logs in Railway dashboard for debugging

## Troubleshooting

### "Microphone not working"
- Ensure you've granted microphone permission in browser
- Use HTTPS in production (required for microphone access)
- Try refreshing the page and allowing access again

### "WebSocket connection failed"
- Check that the backend is running
- Verify no firewall is blocking WebSocket connections
- Check browser console for specific errors

### "AI not responding"
- Verify your Anthropic API key is correct
- Check backend logs for API errors
- Ensure you have API credits available

### "Transcription not working"
- Verify your OpenAI API key is set correctly
- Check that audio is being captured (recording indicator should pulse)
- Look for Whisper errors in browser console or server logs
- Try switching to text input mode as a fallback

## Limitations (M1 MVP)

- Single user (no authentication)
- No document editing (view/export only)
- Basic pause detection (timer-based, not VAD)
- No offline support
- No mobile app (web only)

## License

MIT License - see LICENSE file for details
