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
from typing import Optional
from dataclasses import dataclass

import anthropic
from dotenv import load_dotenv

from prompts import THINKING_PARTNER_SYSTEM_PROMPT, build_thinking_prompt

load_dotenv()


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
            return cls(
                conversation=data.get("conversation", ""),
                document_updates=updates,
                raw_response=json_str
            )
        except json.JSONDecodeError as e:
            # If JSON parsing fails, try to extract conversation from raw text
            return cls(
                conversation=f"I understood your thought. {json_str[:500]}",
                document_updates=[],
                raw_response=json_str
            )


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
        recent_conversations: list[dict]
    ) -> AIResponse:
        """
        Process a new thought from the user.

        Args:
            new_thought: The transcribed text from the user
            current_document: Current markdown document content
            recent_conversations: Recent conversation history

        Returns:
            AIResponse with conversation reply and document updates
        """
        # Build the user prompt with context
        user_prompt = build_thinking_prompt(
            current_document=current_document,
            recent_conversations=recent_conversations,
            new_thought=new_thought
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
        return AIResponse(
            conversation=(
                "I'm having trouble processing right now, but I heard your thought. "
                "Could you tell me more about what's on your mind? "
                "What feels most important about this?"
            ),
            document_updates=[
                DocumentUpdate(
                    action="add_to_section",
                    path="Unprocessed Thoughts",
                    content=f"- {thought}"
                )
            ],
            raw_response=f"Error: {error}"
        )


class ConversationContext:
    """
    Manages conversation context for a session.

    Keeps track of recent exchanges to provide context to Claude.
    Limits history to prevent context window overflow.
    """

    def __init__(self, max_messages: int = 20):
        self.max_messages = max_messages
        self.messages: list[dict] = []

    def add_user_message(self, content: str) -> None:
        """Add a user message to the context."""
        self.messages.append({
            "role": "user",
            "content": content
        })
        self._trim_history()

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message to the context."""
        self.messages.append({
            "role": "assistant",
            "content": content
        })
        self._trim_history()

    def get_recent_messages(self, count: int = 10) -> list[dict]:
        """Get the most recent messages."""
        return self.messages[-count:]

    def clear(self) -> None:
        """Clear all conversation history."""
        self.messages = []

    def _trim_history(self) -> None:
        """Trim history to max_messages."""
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
