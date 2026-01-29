"""
Thinking Partner - FastAPI Main Application

This is the main entry point for the Thinking Partner backend.
Handles:
- WebSocket connections for real-time audio streaming
- REST endpoints for session and document management
- Coordination between transcription, AI processing, and document updates

WebSocket Flow:
1. Client connects to /ws endpoint
2. Client sends "start_session" message to begin
3. Client streams audio chunks (base64 encoded)
4. Backend transcribes audio and returns transcript chunks
5. Backend detects pauses and triggers AI processing
6. Backend returns AI response and document updates
7. Client sends "end_session" to finish
"""

import os
import json
import asyncio
import base64
from typing import Optional
from uuid import UUID
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import load_dotenv

from database import (
    AsyncSessionLocal,
    init_db,
    create_session,
    end_session,
    get_session,
    update_session_transcript,
    add_conversation,
    get_session_conversations,
    get_document,
    get_user_documents,
)
from transcription import (
    get_transcription_provider,
    TranscriptionProvider,
    TranscriptionResult,
    PauseDetector,
)
from ai_processor import AIProcessor, ConversationContext, AIResponse
from document_manager import DocumentManager

load_dotenv()

# Configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))
PAUSE_THRESHOLD_MS = int(os.getenv("PAUSE_THRESHOLD_MS", 2000))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup: Initialize database
    await init_db()
    print("Database initialized")
    yield
    # Shutdown: Cleanup if needed
    print("Shutting down")


app = FastAPI(
    title="Thinking Partner",
    description="AI-powered thinking partner for busy professionals",
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static files (frontend)
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


# ============================================================================
# Dependency Injection
# ============================================================================

async def get_db() -> AsyncSession:
    """Get database session dependency."""
    async with AsyncSessionLocal() as session:
        yield session


# ============================================================================
# Pydantic Models for API
# ============================================================================

class SessionResponse(BaseModel):
    id: str
    document_id: Optional[str]
    status: str


class DocumentResponse(BaseModel):
    id: str
    title: str
    markdown: str
    structure: dict


class ExportResponse(BaseModel):
    markdown: str
    filename: str


# ============================================================================
# REST Endpoints
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main frontend page."""
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Thinking Partner API</h1><p>Frontend not found.</p>")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "thinking-partner"}


@app.get("/api/documents")
async def list_documents(
    user_id: str = "default_user",
    db: AsyncSession = Depends(get_db)
):
    """List all documents for a user."""
    documents = await get_user_documents(db, user_id)
    return [
        {
            "id": str(doc.id),
            "title": doc.title,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        }
        for doc in documents
    ]


@app.get("/api/documents/{document_id}")
async def get_document_api(
    document_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific document by ID."""
    doc = await get_document(db, UUID(document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResponse(
        id=str(doc.id),
        title=doc.title,
        markdown=doc.markdown or "",
        structure=doc.content or {"sections": []}
    )


@app.get("/api/documents/{document_id}/export")
async def export_document(
    document_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Export a document as markdown."""
    doc = await get_document(db, UUID(document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Build export markdown
    title = doc.title or "My Thinking Session"
    markdown = f"# {title}\n\n*Exported from Thinking Partner*\n\n---\n\n{doc.markdown or ''}"

    # Generate filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    filename = f"{safe_title.strip().replace(' ', '_')}.md"

    return ExportResponse(markdown=markdown, filename=filename)


# ============================================================================
# WebSocket Session Handler
# ============================================================================

class SessionHandler:
    """
    Handles a single WebSocket session.

    Manages the lifecycle of:
    - Audio streaming and transcription
    - Pause detection
    - AI processing
    - Document updates
    """

    def __init__(
        self,
        websocket: WebSocket,
        db_session: AsyncSession
    ):
        self.websocket = websocket
        self.db_session = db_session

        # Session state
        self.session_id: Optional[UUID] = None
        self.document_id: Optional[UUID] = None
        self.is_active = False
        self.full_transcript = ""

        # Components
        self.transcription_provider: Optional[TranscriptionProvider] = None
        self.pause_detector: Optional[PauseDetector] = None
        self.ai_processor: Optional[AIProcessor] = None
        self.document_manager: Optional[DocumentManager] = None
        self.conversation_context: Optional[ConversationContext] = None

        # Background tasks
        self.transcript_task: Optional[asyncio.Task] = None

    async def start_session(self, document_id: Optional[str] = None) -> dict:
        """
        Start a new thinking session.

        Creates database records and initializes all components.
        """
        # Initialize document manager
        self.document_manager = DocumentManager(self.db_session)
        doc_uuid = UUID(document_id) if document_id else None
        self.document_id = await self.document_manager.load_or_create_document(doc_uuid)

        # Create session in database
        session = await create_session(
            self.db_session,
            document_id=self.document_id
        )
        self.session_id = session.id

        # Initialize AI processor
        self.ai_processor = AIProcessor()
        self.conversation_context = ConversationContext()

        # Initialize pause detector
        self.pause_detector = PauseDetector(
            pause_threshold_ms=PAUSE_THRESHOLD_MS,
            on_pause=self._on_pause_detected
        )
        self.pause_detector.start()

        # Initialize transcription provider
        try:
            self.transcription_provider = get_transcription_provider()
            await self.transcription_provider.start_stream()

            # Start transcript receiving task
            self.transcript_task = asyncio.create_task(self._receive_transcripts())
        except Exception as e:
            print(f"Failed to start transcription: {e}")
            # Continue without transcription - can still type thoughts

        self.is_active = True

        return {
            "type": "session_started",
            "session_id": str(self.session_id),
            "document_id": str(self.document_id),
            "document": self.document_manager.get_markdown(),
        }

    async def end_session(self) -> dict:
        """
        End the current session.

        Saves final state and cleans up resources.
        """
        self.is_active = False

        # Stop pause detector
        if self.pause_detector:
            self.pause_detector.stop()

        # Close transcription
        if self.transcription_provider:
            await self.transcription_provider.close()

        # Cancel transcript task
        if self.transcript_task:
            self.transcript_task.cancel()
            try:
                await self.transcript_task
            except asyncio.CancelledError:
                pass

        # Save final transcript
        if self.session_id:
            await update_session_transcript(
                self.db_session,
                self.session_id,
                self.full_transcript
            )
            await end_session(self.db_session, self.session_id)

        # Get final document
        markdown = self.document_manager.get_markdown() if self.document_manager else ""

        return {
            "type": "session_ended",
            "session_id": str(self.session_id) if self.session_id else None,
            "document_id": str(self.document_id) if self.document_id else None,
            "final_transcript": self.full_transcript,
            "final_document": markdown,
        }

    async def process_audio(self, audio_data: bytes) -> None:
        """
        Process incoming audio data.

        Sends audio to transcription provider.
        """
        if self.transcription_provider and self.is_active:
            await self.transcription_provider.send_audio(audio_data)

    async def process_text_input(self, text: str) -> None:
        """
        Process direct text input (for testing or typing mode).

        Bypasses transcription and goes directly to AI processing.
        """
        if not self.is_active:
            return

        # Add to transcript
        self.full_transcript += f" {text}" if self.full_transcript else text

        # Send transcript update to client
        await self._send_message({
            "type": "transcript",
            "text": text,
            "is_final": True,
        })

        # Process with AI
        await self._process_with_ai(text)

    async def _receive_transcripts(self) -> None:
        """
        Background task to receive and process transcripts.

        Receives transcription results and forwards to pause detector.
        """
        if not self.transcription_provider:
            return

        try:
            async for result in self.transcription_provider.receive_transcripts():
                if not self.is_active:
                    break

                # Send transcript to client
                await self._send_message({
                    "type": "transcript",
                    "text": result.text,
                    "is_final": result.is_final,
                })

                # Update full transcript with final results
                if result.is_final:
                    self.full_transcript += f" {result.text}" if self.full_transcript else result.text

                # Feed to pause detector
                if self.pause_detector:
                    await self.pause_detector.on_transcript(result)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error receiving transcripts: {e}")
            await self._send_message({
                "type": "error",
                "message": f"Transcription error: {str(e)}",
            })

    async def _on_pause_detected(self, transcript: str) -> None:
        """
        Callback when pause is detected.

        Triggers AI processing of the accumulated transcript.
        """
        if not self.is_active or not transcript.strip():
            return

        await self._send_message({
            "type": "pause_detected",
            "transcript": transcript,
        })

        await self._process_with_ai(transcript)

    async def _process_with_ai(self, thought: str) -> None:
        """
        Process a thought with the AI.

        Gets conversation response and document updates.
        Includes question tracking context for smarter responses.
        """
        if not self.ai_processor or not self.document_manager:
            return

        # Notify client processing started
        await self._send_message({
            "type": "processing",
            "status": "started",
        })

        try:
            # Get current document structure (more efficient than full markdown)
            current_doc = self.document_manager.get_markdown()
            doc_structure = self.document_manager.get_structure()
            recent_convos = self.conversation_context.get_recent_messages() if self.conversation_context else []

            # Get question tracking context
            question_context = None
            if self.conversation_context:
                question_context = self.conversation_context.get_question_context()

            # Process with AI - include question context and document structure
            response = await self.ai_processor.process_thought(
                new_thought=thought,
                current_document=current_doc,
                recent_conversations=recent_convos,
                question_context=question_context,
                document_structure=doc_structure
            )

            # Update conversation context with extracted questions
            if self.conversation_context:
                self.conversation_context.add_user_message(thought)
                self.conversation_context.add_assistant_message(
                    response.conversation,
                    questions=response.questions_asked
                )

            # Save conversation to database
            if self.session_id:
                await add_conversation(self.db_session, self.session_id, "user", thought)
                await add_conversation(self.db_session, self.session_id, "assistant", response.conversation)

            # Apply document updates
            if response.document_updates:
                await self.document_manager.apply_updates(response.document_updates)

            # Send response to client (include pending questions for visibility)
            pending_questions = self.conversation_context.get_pending_questions() if self.conversation_context else []
            await self._send_message({
                "type": "ai_response",
                "conversation": response.conversation,
                "document_updates": [
                    {
                        "action": u.action,
                        "path": u.path,
                        "content": u.content,
                    }
                    for u in response.document_updates
                ],
                "updated_document": self.document_manager.get_markdown(),
                "pending_questions": pending_questions,
            })

        except Exception as e:
            print(f"AI processing error: {e}")
            await self._send_message({
                "type": "error",
                "message": f"AI processing error: {str(e)}",
            })

        finally:
            await self._send_message({
                "type": "processing",
                "status": "completed",
            })

    async def _send_message(self, message: dict) -> None:
        """Send a JSON message to the WebSocket client."""
        try:
            await self.websocket.send_json(message)
        except Exception as e:
            print(f"Error sending WebSocket message: {e}")


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint for thinking sessions.

    Protocol:
    - Client connects and sends {"type": "start_session"} or {"type": "start_session", "document_id": "..."}
    - Client streams audio as {"type": "audio", "data": "<base64>"} or sends text {"type": "text", "content": "..."}
    - Server responds with transcript updates, AI responses, and document updates
    - Client sends {"type": "end_session"} to finish
    """
    await websocket.accept()

    # Create database session for this WebSocket connection
    async with AsyncSessionLocal() as db_session:
        handler = SessionHandler(websocket, db_session)

        try:
            while True:
                # Receive message from client
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "start_session":
                    # Start a new session
                    document_id = data.get("document_id")
                    response = await handler.start_session(document_id)
                    await websocket.send_json(response)

                elif msg_type == "audio":
                    # Process audio chunk
                    audio_b64 = data.get("data", "")
                    if audio_b64:
                        audio_bytes = base64.b64decode(audio_b64)
                        await handler.process_audio(audio_bytes)

                elif msg_type == "text":
                    # Process direct text input
                    content = data.get("content", "")
                    if content:
                        await handler.process_text_input(content)

                elif msg_type == "end_session":
                    # End the session
                    response = await handler.end_session()
                    await websocket.send_json(response)
                    break

                elif msg_type == "get_document":
                    # Get current document state
                    if handler.document_manager:
                        await websocket.send_json({
                            "type": "document",
                            "markdown": handler.document_manager.get_markdown(),
                            "structure": handler.document_manager.get_structure(),
                        })

                elif msg_type == "ping":
                    # Keep-alive ping
                    await websocket.send_json({"type": "pong"})

                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    })

        except WebSocketDisconnect:
            print(f"WebSocket disconnected: {handler.session_id}")
            # Clean up session
            if handler.is_active:
                await handler.end_session()

        except Exception as e:
            print(f"WebSocket error: {e}")
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                })
            except:
                pass


# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=True,
        log_level="info",
    )
