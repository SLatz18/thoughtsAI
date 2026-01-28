"""
Document Manager for the Thinking Partner application.

Handles document storage, updates, and rendering.
Manages the structured document that organizes the user's thoughts.

Document Structure:
{
    "sections": [
        {
            "title": "Section Title",
            "content": "Markdown content for this section",
            "subsections": [
                {
                    "title": "Subsection Title",
                    "content": "Subsection content"
                }
            ]
        }
    ]
}
"""

import json
from typing import Optional
from uuid import UUID
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Document,
    get_document,
    create_document,
    update_document,
)
from ai_processor import DocumentUpdate


@dataclass
class Section:
    """Represents a document section."""
    title: str
    content: str = ""
    subsections: list["Section"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "content": self.content,
            "subsections": [s.to_dict() for s in self.subsections]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Section":
        return cls(
            title=data.get("title", ""),
            content=data.get("content", ""),
            subsections=[
                cls.from_dict(s) for s in data.get("subsections", [])
            ]
        )


@dataclass
class StructuredDocument:
    """
    In-memory representation of the structured document.

    Provides methods for adding, updating, and rendering sections.
    """
    sections: list[Section] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sections": [s.to_dict() for s in self.sections]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StructuredDocument":
        return cls(
            sections=[
                Section.from_dict(s) for s in data.get("sections", [])
            ]
        )

    def find_section(self, title: str) -> Optional[Section]:
        """Find a top-level section by title."""
        for section in self.sections:
            if section.title.lower() == title.lower():
                return section
        return None

    def find_or_create_section(self, title: str) -> Section:
        """Find a section or create it if it doesn't exist."""
        section = self.find_section(title)
        if section is None:
            section = Section(title=title)
            self.sections.append(section)
        return section

    def find_subsection(self, section_title: str, subsection_title: str) -> Optional[Section]:
        """Find a subsection within a section."""
        section = self.find_section(section_title)
        if section:
            for subsection in section.subsections:
                if subsection.title.lower() == subsection_title.lower():
                    return subsection
        return None

    def add_section(self, title: str, content: str = "") -> Section:
        """Add a new top-level section."""
        # Check if section already exists
        existing = self.find_section(title)
        if existing:
            # Add content to existing section
            if content:
                if existing.content:
                    existing.content += "\n" + content
                else:
                    existing.content = content
            return existing

        section = Section(title=title, content=content)
        self.sections.append(section)
        return section

    def add_to_section(self, path: str, content: str) -> bool:
        """
        Add content to an existing section or subsection.

        Path format: "Section Title" or "Section Title/Subsection Title"
        """
        parts = path.split("/")

        if len(parts) == 1:
            # Adding to top-level section
            section = self.find_or_create_section(parts[0])
            if section.content:
                section.content += "\n" + content
            else:
                section.content = content
            return True

        elif len(parts) == 2:
            # Adding to subsection
            section = self.find_or_create_section(parts[0])
            subsection = None
            for sub in section.subsections:
                if sub.title.lower() == parts[1].lower():
                    subsection = sub
                    break

            if subsection is None:
                # Create subsection
                subsection = Section(title=parts[1], content=content)
                section.subsections.append(subsection)
            else:
                if subsection.content:
                    subsection.content += "\n" + content
                else:
                    subsection.content = content
            return True

        return False

    def create_subsection(self, path: str, content: str) -> bool:
        """
        Create a new subsection under a section.

        Path format: "Section Title/Subsection Title"
        """
        parts = path.split("/")
        if len(parts) != 2:
            return False

        section = self.find_or_create_section(parts[0])

        # Check if subsection already exists
        for sub in section.subsections:
            if sub.title.lower() == parts[1].lower():
                # Add to existing subsection
                if sub.content:
                    sub.content += "\n" + content
                else:
                    sub.content = content
                return True

        # Create new subsection
        subsection = Section(title=parts[1], content=content)
        section.subsections.append(subsection)
        return True

    def add_action_item(self, content: str) -> bool:
        """Add an action item to the Action Items section."""
        section = self.find_or_create_section("Action Items")
        item = f"- [ ] {content}" if not content.startswith("-") else content
        if section.content:
            section.content += "\n" + item
        else:
            section.content = item
        return True

    def add_blocker(self, content: str) -> bool:
        """Add a blocker to the Blockers & Open Questions section."""
        section = self.find_or_create_section("Blockers & Open Questions")
        item = f"- {content}" if not content.startswith("-") else content
        if section.content:
            section.content += "\n" + item
        else:
            section.content = item
        return True

    def render_markdown(self) -> str:
        """Render the document as markdown."""
        lines = []

        for section in self.sections:
            # Section header
            lines.append(f"## {section.title}")
            lines.append("")

            # Section content
            if section.content:
                lines.append(section.content)
                lines.append("")

            # Subsections
            for subsection in section.subsections:
                lines.append(f"### {subsection.title}")
                lines.append("")
                if subsection.content:
                    lines.append(subsection.content)
                    lines.append("")

        return "\n".join(lines)


class DocumentManager:
    """
    Manages document operations for a session.

    Handles loading, updating, and saving documents to the database.
    Applies AI-generated updates to the structured document.
    """

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.document_id: Optional[UUID] = None
        self.structured_doc: Optional[StructuredDocument] = None

    async def load_or_create_document(
        self,
        document_id: Optional[UUID] = None,
        user_id: str = "default_user"
    ) -> UUID:
        """
        Load an existing document or create a new one.

        Returns the document ID.
        """
        if document_id:
            # Try to load existing document
            doc = await get_document(self.db_session, document_id)
            if doc:
                self.document_id = doc.id
                self.structured_doc = StructuredDocument.from_dict(doc.content or {"sections": []})
                return doc.id

        # Create new document
        doc = await create_document(self.db_session, user_id=user_id)
        self.document_id = doc.id
        self.structured_doc = StructuredDocument()
        return doc.id

    async def apply_updates(self, updates: list[DocumentUpdate]) -> bool:
        """
        Apply a list of document updates.

        Returns True if all updates were applied successfully.
        """
        if self.structured_doc is None:
            return False

        success = True
        for update in updates:
            result = self._apply_single_update(update)
            if not result:
                success = False

        # Save to database after applying updates
        await self._save_document()

        return success

    def _apply_single_update(self, update: DocumentUpdate) -> bool:
        """Apply a single document update."""
        if self.structured_doc is None:
            return False

        action = update.action.lower()

        if action == "add_section":
            self.structured_doc.add_section(update.path, update.content)
            return True

        elif action == "add_to_section":
            return self.structured_doc.add_to_section(update.path, update.content)

        elif action == "create_subsection":
            return self.structured_doc.create_subsection(update.path, update.content)

        elif action == "add_action_item":
            return self.structured_doc.add_action_item(update.content)

        elif action == "add_blocker":
            return self.structured_doc.add_blocker(update.content)

        else:
            # Unknown action, try to add as section content
            return self.structured_doc.add_to_section(update.path, update.content)

    async def _save_document(self) -> None:
        """Save the current document state to the database."""
        if self.document_id is None or self.structured_doc is None:
            return

        content = self.structured_doc.to_dict()
        markdown = self.structured_doc.render_markdown()

        await update_document(
            self.db_session,
            self.document_id,
            content=content,
            markdown=markdown,
            save_version=True
        )

    def get_markdown(self) -> str:
        """Get the current document as markdown."""
        if self.structured_doc is None:
            return ""
        return self.structured_doc.render_markdown()

    def get_structure(self) -> dict:
        """Get the current document structure as dict."""
        if self.structured_doc is None:
            return {"sections": []}
        return self.structured_doc.to_dict()

    async def export_markdown(self) -> str:
        """
        Export the document as clean markdown.

        Includes a header with metadata.
        """
        if self.structured_doc is None:
            return ""

        # Fetch document from DB to get title
        doc = await get_document(self.db_session, self.document_id) if self.document_id else None
        title = doc.title if doc else "My Thinking Session"

        lines = [
            f"# {title}",
            "",
            f"*Exported from Thinking Partner*",
            "",
            "---",
            "",
            self.structured_doc.render_markdown()
        ]

        return "\n".join(lines)
