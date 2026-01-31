"""
AI Processor module for the Thinking Partner application.

Handles integration with Anthropic's Claude API to:
1. Generate conversational responses (clarifying questions, insights)
2. Determine document updates (where to organize new thoughts)

Uses Claude Sonnet 4 for optimal balance of quality and speed.
"""

import os
import json
import asyncio
import re
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

import anthropic
from dotenv import load_dotenv

from prompts import THINKING_PARTNER_SYSTEM_PROMPT, build_thinking_prompt

load_dotenv()


@dataclass
class PendingQuestion:
    """Represents a question asked by the AI that hasn't been answered yet."""
    question: str
    asked_at: datetime = field(default_factory=datetime.utcnow)
    context: str = ""  # What topic/thought prompted this question
    answered: bool = False
    answer: str = ""


@dataclass
class DocumentUpdate:
    """Represents a single document update action."""
    action: str  # add_section, add_to_section, create_subsection, add_action_item, add_blocker
    path: str    # Section path (e.g., "Career Decisions" or "Career Decisions/Options")
    content: str # Markdown content to add

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentUpdate":
        return cls(
            action=data.get("action", "add_section"),
            path=data.get("path", ""),
            content=data.get("content", "")
        )


@dataclass
class AIResponse:
    """
    Response from the AI processor.

    Contains both the conversational response (what to say to the user)
    and document updates (how to organize their thoughts).
    """
    conversation: str
    document_updates: list[DocumentUpdate]
    questions_asked: list[str]  # Questions extracted from the response
    raw_response: str  # Original response for debugging

    @classmethod
    def from_json(cls, json_str: str) -> "AIResponse":
        """Parse AI response from JSON string."""
        try:
            data = json.loads(json_str)
            updates = [
                DocumentUpdate.from_dict(u)
                for u in data.get("document_updates", [])
            ]
            conversation = data.get("conversation", "")
            questions = cls._extract_questions(conversation)
            return cls(
                conversation=conversation,
                document_updates=updates,
                questions_asked=questions,
                raw_response=json_str
            )
        except json.JSONDecodeError as e:
            # If JSON parsing fails, try to extract conversation from raw text
            return cls(
                conversation=f"I understood your thought. {json_str[:500]}",
                document_updates=[],
                questions_asked=[],
                raw_response=json_str
            )

    @staticmethod
    def _extract_questions(text: str) -> list[str]:
        """
        Extract questions from the AI's response.

        Looks for sentences ending with '?' to identify questions.
        """
        if not text:
            return []

        # Split into sentences and find questions
        # Handle common patterns: sentences ending with ?, numbered questions, bullet questions
        questions = []

        # Pattern 1: Direct questions ending with ?
        question_pattern = r'[^.!?\n]*\?'
        matches = re.findall(question_pattern, text)

        for match in matches:
            question = match.strip()
            # Clean up: remove leading numbers, bullets, dashes
            question = re.sub(r'^[\d\.\)\-\*\•]+\s*', '', question)
            if question and len(question) > 10:  # Filter out very short matches
                questions.append(question)

        return questions


class AIProcessor:
    """
    Processes user thoughts using Claude AI.

    Responsibilities:
    - Build context from current document and conversation history
    - Send requests to Claude API with appropriate system prompts
    - Parse responses to extract conversation and document updates
    - Handle API errors with retries and fallbacks
    """

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")

        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"  # Claude Sonnet 4
        self.max_tokens = 2048
        self.max_retries = 3
        self.retry_delay_base = 2  # Base delay for exponential backoff

    async def process_thought(
        self,
        new_thought: str,
        current_document: str,
        recent_conversations: list[dict],
        question_context: dict = None,
        document_structure: dict = None,
        full_transcript: str = None
    ) -> AIResponse:
        """
        Process a new thought from the user.

        Args:
            new_thought: The transcribed text from the user
            current_document: Current markdown document content (or structured summary)
            recent_conversations: Recent conversation history
            question_context: Dict with pending and recently answered questions
            document_structure: Structured JSON of document sections (optional, preferred over markdown)
            full_transcript: Complete transcript of the session for context

        Returns:
            AIResponse with conversation reply and document updates
        """
        # Use structured document if available, otherwise fall back to markdown
        doc_context = current_document
        if document_structure:
            doc_context = self._format_document_structure(document_structure)

        # Build the user prompt with context
        user_prompt = build_thinking_prompt(
            current_document=doc_context,
            recent_conversations=recent_conversations,
            new_thought=new_thought,
            question_context=question_context,
            full_transcript=full_transcript
        )

        # Try to get response with retries
        for attempt in range(self.max_retries):
            try:
                response = await self._call_claude(user_prompt)
                return self._parse_response(response)

            except anthropic.APIConnectionError as e:
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay_base ** (attempt + 1)
                    print(f"API connection error, retrying in {delay}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    return self._fallback_response(new_thought, str(e))

            except anthropic.RateLimitError as e:
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay_base ** (attempt + 1)
                    print(f"Rate limited, retrying in {delay}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    return self._fallback_response(new_thought, str(e))

            except anthropic.APIStatusError as e:
                print(f"API error: {e}")
                return self._fallback_response(new_thought, str(e))

            except Exception as e:
                print(f"Unexpected error: {e}")
                return self._fallback_response(new_thought, str(e))

        return self._fallback_response(new_thought, "Max retries exceeded")

    async def _call_claude(self, user_prompt: str) -> str:
        """
        Make the actual API call to Claude.

        Args:
            user_prompt: The formatted user message

        Returns:
            Raw response text from Claude
        """
        message = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=THINKING_PARTNER_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        # Extract text from response
        if message.content and len(message.content) > 0:
            return message.content[0].text
        return ""

    def _format_document_structure(self, structure: dict) -> str:
        """
        Format document structure as a concise summary for the prompt.

        Instead of sending full markdown, sends a structured overview
        so Claude knows what sections exist and their purpose.
        """
        sections = structure.get("sections", [])
        if not sections:
            return "(Empty - this is a new session)"

        lines = ["Current document sections:"]
        for section in sections:
            title = section.get("title", "Untitled")
            content = section.get("content", "")
            subsections = section.get("subsections", [])

            # Create a brief summary of content
            content_preview = ""
            if content:
                # Show first 100 chars or first 2 bullet points
                content_lines = content.strip().split('\n')[:2]
                content_preview = " | ".join(line.strip()[:50] for line in content_lines if line.strip())

            # Format section info
            subsection_names = [s.get("title", "") for s in subsections if s.get("title")]
            if subsection_names:
                lines.append(f"- **{title}** (subsections: {', '.join(subsection_names)})")
            else:
                lines.append(f"- **{title}**")

            if content_preview:
                lines.append(f"  Preview: {content_preview}...")

        return "\n".join(lines)

    def _parse_response(self, response_text: str) -> AIResponse:
        """
        Parse Claude's response into structured AIResponse.

        Handles cases where response might not be valid JSON.
        """
        # Try to extract JSON from the response
        json_str = self._extract_json(response_text)

        if json_str:
            return AIResponse.from_json(json_str)
        else:
            # Couldn't parse JSON, use response as conversation
            return AIResponse(
                conversation=response_text,
                document_updates=[],
                questions_asked=AIResponse._extract_questions(response_text),
                raw_response=response_text
            )

    def _extract_json(self, text: str) -> Optional[str]:
        """
        Extract JSON object from text.

        Handles cases where JSON might be wrapped in markdown code blocks
        or mixed with other text.
        """
        # Try to find JSON in code blocks first
        import re

        # Look for ```json ... ``` blocks
        json_block_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
        match = re.search(json_block_pattern, text)
        if match:
            return match.group(1)

        # Try to find raw JSON object
        json_pattern = r'\{[\s\S]*"conversation"[\s\S]*"document_updates"[\s\S]*\}'
        match = re.search(json_pattern, text)
        if match:
            return match.group(0)

        # Try parsing the whole text as JSON
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        return None

    def _fallback_response(self, thought: str, error: str) -> AIResponse:
        """
        Generate a fallback response when API fails.

        Still tries to be helpful even without AI processing.
        """
        fallback_conversation = (
            "I'm having trouble processing right now, but I heard your thought. "
            "Could you tell me more about what's on your mind? "
            "What feels most important about this?"
        )
        return AIResponse(
            conversation=fallback_conversation,
            document_updates=[
                DocumentUpdate(
                    action="add_to_section",
                    path="Unprocessed Thoughts",
                    content=f"- {thought}"
                )
            ],
            questions_asked=[
                "Could you tell me more about what's on your mind?",
                "What feels most important about this?"
            ],
            raw_response=f"Error: {error}"
        )


class ConversationContext:
    """
    Manages conversation context for a session.

    Keeps track of recent exchanges and pending questions to provide
    context to Claude. Tracks which questions have been answered.
    """

    def __init__(self, max_messages: int = 20):
        self.max_messages = max_messages
        self.messages: list[dict] = []
        self.pending_questions: list[PendingQuestion] = []
        self.answered_questions: list[PendingQuestion] = []

    def add_user_message(self, content: str) -> None:
        """
        Add a user message to the context.

        Also checks if this message answers any pending questions.
        """
        self.messages.append({
            "role": "user",
            "content": content
        })
        self._trim_history()

        # Check if this response might answer pending questions
        self._check_for_answers(content)

    def add_assistant_message(self, content: str, questions: list[str] = None) -> None:
        """
        Add an assistant message to the context.

        Args:
            content: The assistant's response text
            questions: List of questions extracted from the response
        """
        self.messages.append({
            "role": "assistant",
            "content": content
        })
        self._trim_history()

        # Track new questions
        if questions:
            for q in questions:
                self.pending_questions.append(PendingQuestion(
                    question=q,
                    context=content[:100]  # Store brief context
                ))

    def _check_for_answers(self, user_message: str) -> None:
        """
        Check if the user's message might answer any pending questions.

        Uses simple heuristics - if the user's response is substantial
        and comes after questions, mark the oldest pending questions as
        potentially answered.
        """
        if not self.pending_questions:
            return

        # If user provides a substantial response, assume they're answering
        # the most recent questions
        if len(user_message) > 20:
            # Mark up to 3 oldest pending questions as answered
            questions_to_answer = min(3, len(self.pending_questions))
            for _ in range(questions_to_answer):
                if self.pending_questions:
                    q = self.pending_questions.pop(0)
                    q.answered = True
                    q.answer = user_message[:200]  # Store brief answer reference
                    self.answered_questions.append(q)

        # Keep only recent answered questions for context
        if len(self.answered_questions) > 10:
            self.answered_questions = self.answered_questions[-10:]

    def get_recent_messages(self, count: int = 10) -> list[dict]:
        """Get the most recent messages."""
        return self.messages[-count:]

    def get_pending_questions(self) -> list[str]:
        """Get list of questions that haven't been answered yet."""
        return [q.question for q in self.pending_questions]

    def get_recently_answered(self) -> list[dict]:
        """Get recently answered questions with brief context."""
        return [
            {"question": q.question, "answered": True}
            for q in self.answered_questions[-5:]
        ]

    def get_question_context(self) -> dict:
        """
        Get full question context for the prompt.

        Returns dict with pending and recently answered questions.
        """
        return {
            "pending": self.get_pending_questions(),
            "recently_answered": [q.question for q in self.answered_questions[-3:]]
        }

    def clear(self) -> None:
        """Clear all conversation history and questions."""
        self.messages = []
        self.pending_questions = []
        self.answered_questions = []

    def _trim_history(self) -> None:
        """Trim history to max_messages."""
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
