"""
Transcription module for the Thinking Partner application.

Supports two transcription providers:
1. OpenAI Whisper (primary) - Reliable batch transcription
2. Deepgram (optional) - Real-time streaming transcription

The module handles audio streaming, transcription, and pause detection.
"""

import os
import asyncio
import json
import base64
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Callable, Optional
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


class TranscriptionResult:
    """Represents a transcription result from the provider."""

    def __init__(
        self,
        text: str,
        is_final: bool = False,
        confidence: float = 1.0,
        timestamp: Optional[datetime] = None
    ):
        self.text = text
        self.is_final = is_final
        self.confidence = confidence
        self.timestamp = timestamp or datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "is_final": self.is_final,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat()
        }


class TranscriptionProvider(ABC):
    """Abstract base class for transcription providers."""

    @abstractmethod
    async def start_stream(self) -> None:
        """Initialize the streaming connection."""
        pass

    @abstractmethod
    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio data to the transcription service."""
        pass

    @abstractmethod
    async def receive_transcripts(self) -> AsyncGenerator[TranscriptionResult, None]:
        """Receive transcription results as an async generator."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the connection."""
        pass


class DeepgramProvider(TranscriptionProvider):
    """
    Deepgram streaming transcription provider.

    Uses Deepgram's WebSocket API for real-time transcription.
    Supports interim results for low-latency display.
    """

    def __init__(self):
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPGRAM_API_KEY environment variable is required")

        self._websocket = None
        self._receive_task = None
        self._transcript_queue: asyncio.Queue[TranscriptionResult] = asyncio.Queue()
        self._is_connected = False

    async def start_stream(self) -> None:
        """
        Initialize WebSocket connection to Deepgram.

        Configuration:
        - model: nova-2 (best accuracy)
        - language: en-US
        - punctuate: true (add punctuation)
        - interim_results: true (get partial transcripts)
        - endpointing: 300ms (detect end of speech)
        - vad_events: true (voice activity detection)
        """
        import websockets

        url = (
            "wss://api.deepgram.com/v1/listen?"
            "model=nova-2&"
            "language=en-US&"
            "punctuate=true&"
            "interim_results=true&"
            "endpointing=300&"
            "vad_events=true&"
            "encoding=linear16&"
            "sample_rate=16000&"
            "channels=1"
        )

        headers = {
            "Authorization": f"Token {self.api_key}"
        }

        self._websocket = await websockets.connect(
            url,
            extra_headers=headers,
            ping_interval=20,
            ping_timeout=10
        )
        self._is_connected = True

        # Start receiving messages in background
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        """Background task to receive and parse Deepgram messages."""
        try:
            async for message in self._websocket:
                data = json.loads(message)

                # Handle transcription results
                if data.get("type") == "Results":
                    channel = data.get("channel", {})
                    alternatives = channel.get("alternatives", [])

                    if alternatives:
                        transcript = alternatives[0].get("transcript", "")
                        confidence = alternatives[0].get("confidence", 1.0)
                        is_final = data.get("is_final", False)

                        if transcript:  # Only queue non-empty transcripts
                            result = TranscriptionResult(
                                text=transcript,
                                is_final=is_final,
                                confidence=confidence
                            )
                            await self._transcript_queue.put(result)

                # Handle speech detection events
                elif data.get("type") == "SpeechStarted":
                    # Could emit an event here if needed
                    pass

                # Handle metadata
                elif data.get("type") == "Metadata":
                    # Connection metadata, can be logged
                    pass

        except Exception as e:
            # Log error and put sentinel to signal closure
            print(f"Deepgram receive error: {e}")
            self._is_connected = False

    async def send_audio(self, audio_data: bytes) -> None:
        """
        Send raw audio data to Deepgram.

        Args:
            audio_data: Raw PCM audio bytes (16-bit, 16kHz, mono)
        """
        if self._websocket and self._is_connected:
            try:
                await self._websocket.send(audio_data)
            except Exception as e:
                print(f"Error sending audio to Deepgram: {e}")
                self._is_connected = False

    async def receive_transcripts(self) -> AsyncGenerator[TranscriptionResult, None]:
        """Yield transcription results as they arrive."""
        while self._is_connected or not self._transcript_queue.empty():
            try:
                result = await asyncio.wait_for(
                    self._transcript_queue.get(),
                    timeout=0.1
                )
                yield result
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

    async def close(self) -> None:
        """Close the Deepgram WebSocket connection."""
        self._is_connected = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._websocket:
            await self._websocket.close()


class WhisperProvider(TranscriptionProvider):
    """
    OpenAI Whisper transcription provider (primary).

    Uses batch transcription since Whisper doesn't support streaming.
    Accumulates audio and transcribes periodically for near-real-time results.

    Configuration:
    - Transcribes every 1.5 seconds for responsive feedback
    - Minimum audio threshold to avoid empty transcriptions
    - Handles webm/opus audio format from browser MediaRecorder
    """

    def __init__(self, transcribe_interval: float = 1.5):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        self.transcribe_interval = transcribe_interval
        self._audio_buffer = bytearray()
        self._transcript_queue: asyncio.Queue[TranscriptionResult] = asyncio.Queue()
        self._is_active = False
        self._transcribe_task = None
        self._client = None
        # Minimum bytes before attempting transcription (avoid empty audio)
        self._min_audio_bytes = 1000

    async def start_stream(self) -> None:
        """Initialize the Whisper provider."""
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=self.api_key)
        self._is_active = True
        self._audio_buffer = bytearray()

        # Start periodic transcription task
        self._transcribe_task = asyncio.create_task(self._periodic_transcribe())
        print("Whisper transcription provider started")

    async def _periodic_transcribe(self) -> None:
        """
        Periodically transcribe accumulated audio.

        Runs at configured interval if there's enough audio in the buffer.
        """
        import io

        while self._is_active:
            await asyncio.sleep(self.transcribe_interval)

            # Only transcribe if we have enough audio data
            if len(self._audio_buffer) > self._min_audio_bytes:
                # Copy and clear buffer atomically
                audio_data = bytes(self._audio_buffer)
                self._audio_buffer = bytearray()

                # Create audio file in memory
                # The browser sends webm/opus, which Whisper can handle directly
                audio_buffer = io.BytesIO(audio_data)
                audio_buffer.name = "audio.webm"  # Whisper accepts webm format

                try:
                    # Call Whisper API
                    response = await self._client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_buffer,
                        language="en"
                    )

                    if response.text and response.text.strip():
                        result = TranscriptionResult(
                            text=response.text.strip(),
                            is_final=True,
                            confidence=1.0
                        )
                        await self._transcript_queue.put(result)
                        print(f"Whisper transcribed: {response.text[:50]}...")

                except Exception as e:
                    print(f"Whisper transcription error: {e}")
                    # Don't lose the audio - put it back if transcription failed
                    # (only for recoverable errors)

    async def send_audio(self, audio_data: bytes) -> None:
        """
        Accumulate audio data for batch transcription.

        Args:
            audio_data: Raw PCM audio bytes (16-bit, 16kHz, mono)
        """
        if self._is_active:
            self._audio_buffer.extend(audio_data)

    async def receive_transcripts(self) -> AsyncGenerator[TranscriptionResult, None]:
        """Yield transcription results as they're processed."""
        while self._is_active or not self._transcript_queue.empty():
            try:
                result = await asyncio.wait_for(
                    self._transcript_queue.get(),
                    timeout=0.1
                )
                yield result
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

    async def close(self) -> None:
        """Close the Whisper provider."""
        self._is_active = False

        if self._transcribe_task:
            self._transcribe_task.cancel()
            try:
                await self._transcribe_task
            except asyncio.CancelledError:
                pass


class PauseDetector:
    """
    Simple timer-based pause detection.

    Detects when the user has stopped talking based on silence duration.
    Triggers a callback when pause threshold is exceeded.
    """

    def __init__(
        self,
        pause_threshold_ms: int = 2000,
        on_pause: Optional[Callable[[str], None]] = None
    ):
        """
        Initialize pause detector.

        Args:
            pause_threshold_ms: Milliseconds of silence to trigger pause
            on_pause: Callback function called with accumulated transcript
        """
        self.pause_threshold_ms = pause_threshold_ms
        self.on_pause = on_pause

        self._last_transcript_time: Optional[datetime] = None
        self._accumulated_transcript = ""
        self._pause_task: Optional[asyncio.Task] = None
        self._is_active = False

    def start(self) -> None:
        """Start the pause detector."""
        self._is_active = True
        self._accumulated_transcript = ""
        self._last_transcript_time = None

    def stop(self) -> None:
        """Stop the pause detector."""
        self._is_active = False
        if self._pause_task:
            self._pause_task.cancel()

    async def on_transcript(self, result: TranscriptionResult) -> None:
        """
        Process a new transcript result.

        Called whenever new transcription is received.
        Resets the pause timer and accumulates final transcripts.
        """
        if not self._is_active:
            return

        self._last_transcript_time = datetime.utcnow()

        # Accumulate final transcripts
        if result.is_final and result.text:
            if self._accumulated_transcript:
                self._accumulated_transcript += " " + result.text
            else:
                self._accumulated_transcript = result.text

        # Cancel existing pause timer
        if self._pause_task:
            self._pause_task.cancel()
            try:
                await self._pause_task
            except asyncio.CancelledError:
                pass

        # Start new pause timer
        self._pause_task = asyncio.create_task(self._pause_timer())

    async def _pause_timer(self) -> None:
        """
        Timer task that triggers on_pause after threshold.
        """
        try:
            await asyncio.sleep(self.pause_threshold_ms / 1000.0)

            # Pause detected - trigger callback with accumulated transcript
            if self._accumulated_transcript and self.on_pause:
                transcript = self._accumulated_transcript
                self._accumulated_transcript = ""  # Reset for next segment
                await self.on_pause(transcript)

        except asyncio.CancelledError:
            # Timer was cancelled due to new speech
            pass

    def get_accumulated_transcript(self) -> str:
        """Get the current accumulated transcript."""
        return self._accumulated_transcript

    def clear_accumulated(self) -> None:
        """Clear the accumulated transcript."""
        self._accumulated_transcript = ""


def get_transcription_provider() -> TranscriptionProvider:
    """
    Get the configured transcription provider.

    Returns Whisper by default (more reliable), can use Deepgram if configured.
    """
    provider = os.getenv("TRANSCRIPTION_PROVIDER", "whisper").lower()

    if provider == "deepgram":
        try:
            return DeepgramProvider()
        except ValueError:
            # Fall back to Whisper if Deepgram key not configured
            print("Deepgram API key not found, falling back to Whisper")
            return WhisperProvider()
    else:
        # Default to Whisper
        return WhisperProvider()
