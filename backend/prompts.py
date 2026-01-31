"""
Claude system prompts for the Thinking Partner application.

Contains the system prompts used to guide Claude's behavior as a thinking partner.
The AI serves dual purposes:
1. Conversational: Ask clarifying questions, help the user think deeper
2. Document: Organize thoughts into a structured markdown document
"""

THINKING_PARTNER_SYSTEM_PROMPT = """You are an expert thinking partner for busy professionals. Your role is to help people think through their ideas, decisions, and challenges by:

1. **Asking probing questions** that help them think deeper and uncover hidden assumptions
2. **Identifying blockers** - things that might be holding them back or need resolution
3. **Organizing their thoughts** into a coherent, structured document

When the user shares their thoughts, you must provide TWO things:

## CONVERSATIONAL RESPONSE
- ALWAYS engage with the SUBSTANCE of what they said - never respond with generic filler like "take your time" or "tell me more about what's on your mind"
- Even if a thought seems incomplete or trails off, there IS content to engage with - engage with IT
- Ask 1-2 focused, clarifying questions that push their thinking forward on the SPECIFIC topic they raised
- Keep questions concise and direct (busy professionals don't have time for fluff)
- Identify assumptions they might be making about THIS specific situation
- Point out gaps in their reasoning or missing information
- Be supportive but intellectually honest - challenge weak thinking
- Don't just validate - add value by surfacing what they haven't considered
- NEVER ask what they're thinking about or what the context is - they just told you. Engage with what they said.

## DOCUMENT UPDATES
- Organize their thoughts into the structured document
- Decide if this is a new topic or adds to an existing section
- Create clear, hierarchical organization (Topics > Subtopics > Details)
- Extract action items when mentioned
- Note blockers and decisions to be made
- Keep the document concise but comprehensive

IMPORTANT: Your response must be valid JSON in this exact format:
{
    "conversation": "Your response here with clarifying questions...",
    "document_updates": [
        {
            "action": "add_section" | "add_to_section" | "create_subsection" | "add_action_item" | "add_blocker",
            "path": "Section Name" or "Section Name/Subsection Name",
            "content": "The markdown content to add"
        }
    ]
}

### Document Update Actions:
- **add_section**: Create a new top-level section (e.g., "Career Decisions", "Project Ideas")
- **add_to_section**: Add content to an existing section
- **create_subsection**: Create a subsection under an existing section
- **add_action_item**: Add an item to the "Action Items" section (create if doesn't exist)
- **add_blocker**: Add an item to the "Blockers & Open Questions" section (create if doesn't exist)

### Guidelines for Document Organization:
- Group related thoughts together, not chronologically
- Use clear, descriptive section names
- Keep bullet points concise
- Highlight key decisions, insights, and next steps
- Maintain a logical flow within sections

Remember: You're helping a busy professional think clearly. Be valuable, be concise, be direct."""


def build_thinking_prompt(
    current_document: str,
    recent_conversations: list[dict],
    new_thought: str,
    question_context: dict = None,
    full_transcript: str = None
) -> str:
    """
    Build the user message for Claude with context.

    Args:
        current_document: The current markdown document content
        recent_conversations: List of recent conversation messages
        new_thought: The new transcript from the user
        question_context: Dict with pending and recently answered questions
        full_transcript: The complete transcript of the session so far

    Returns:
        Formatted prompt string
    """
    # Format recent conversation history
    conversation_history = ""
    if recent_conversations:
        for msg in recent_conversations[-6:]:  # Last 6 messages (3 exchanges)
            role = "User" if msg["role"] == "user" else "Assistant"
            conversation_history += f"{role}: {msg['content']}\n\n"

    # Format question tracking context
    question_section = ""
    if question_context:
        pending = question_context.get("pending", [])
        answered = question_context.get("recently_answered", [])

        if pending:
            question_section += "## Your Pending Questions (awaiting user response)\n"
            for i, q in enumerate(pending, 1):
                question_section += f"{i}. {q}\n"
            question_section += "\n"

        if answered:
            question_section += "## Recently Answered Questions\n"
            for q in answered:
                question_section += f"- {q} (answered)\n"
            question_section += "\n"

    # Include full transcript for context if available
    transcript_section = ""
    if full_transcript and full_transcript.strip():
        # Truncate if too long, keeping most recent
        if len(full_transcript) > 2000:
            transcript_section = f"## Full Session Transcript (truncated)\n...{full_transcript[-2000:]}\n\n"
        else:
            transcript_section = f"## Full Session Transcript\n{full_transcript}\n\n"

    prompt = f"""## Current Document Structure
{current_document if current_document else "(Empty - this is a new session)"}

## Recent Conversation
{conversation_history if conversation_history else "(Starting fresh conversation)"}

{transcript_section}{question_section}## New Thought from User
{new_thought}

IMPORTANT:
- The user is speaking their thoughts out loud via voice transcription
- Engage with the ACTUAL CONTENT of what they said - do NOT ask "what would you like to think through?" or similar
- If they're discussing a topic (like organizing tasks, making decisions, etc.), engage with THAT topic
- Provide your response as JSON with "conversation" (your response/follow-up questions) and "document_updates" (how to update the document)."""

    return prompt


# Example initial document structure for reference
INITIAL_DOCUMENT_STRUCTURE = {
    "sections": []
}

# Example of what a populated document might look like
EXAMPLE_DOCUMENT_STRUCTURE = {
    "sections": [
        {
            "title": "Career Decisions",
            "content": "",
            "subsections": [
                {
                    "title": "Current Situation",
                    "content": "- Working at TechCorp for 3 years\n- Feeling stagnant in current role"
                },
                {
                    "title": "Options Being Considered",
                    "content": "- Stay and push for promotion\n- Look for new opportunities"
                }
            ]
        },
        {
            "title": "Action Items",
            "content": "- [ ] Update resume\n- [ ] Talk to mentor about career path",
            "subsections": []
        },
        {
            "title": "Blockers & Open Questions",
            "content": "- What's the timeline for the promotion cycle?\n- Need to research market salary ranges",
            "subsections": []
        }
    ]
}
