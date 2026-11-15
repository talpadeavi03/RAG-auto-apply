import re
from pathlib import Path
from typing import List
from src.models import RAGDocument

class ResumeLoader:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)

    def load_and_chunk(self) -> List[RAGDocument]:
        """Loads a resume file (.md, .txt, .pdf) and returns semantic section chunks."""
        if not self.file_path.exists():
            return []

        text = ""
        suffix = self.file_path.suffix.lower()
        if suffix in [".md", ".txt"]:
            with open(self.file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        elif suffix == ".pdf":
            try:
                # If pypdf or pdfplumber is present
                import pypdf
                reader = pypdf.PdfReader(str(self.file_path))
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            except ImportError:
                # Fallback simple text read if plain bytes
                with open(self.file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()

        return self._chunk_sections(text)

    def _chunk_sections(self, text: str) -> List[RAGDocument]:
        """Split resume into semantic sections: summary, experience, skills, projects, education."""
        docs: List[RAGDocument] = []
        
        # Whole resume as master document
        docs.append(RAGDocument(
            doc_id="resume_master",
            source_type="resume",
            title="Complete Resume Master",
            content=text,
            metadata={"filename": self.file_path.name, "type": "master"}
        ))

        # Detect headers like # Experience, ## Skills, etc.
        pattern = r"(?i)(?:^|\n)(#{1,3}\s*|\*{2}\s*|[A-Z\s]{4,}:?\s*\n)(summary|experience|work history|skills|technical skills|projects|education|certifications)"
        sections = re.split(pattern, text)
        
        if len(sections) > 1:
            for i in range(1, len(sections), 2):
                sec_title = sections[i].strip()
                sec_body = sections[i+1].strip() if i+1 < len(sections) else ""
                if sec_body:
                    docs.append(RAGDocument(
                        doc_id=f"resume_sec_{sec_title.lower().replace(' ', '_')}",
                        source_type="resume",
                        title=f"Resume Section: {sec_title.capitalize()}",
                        content=sec_body,
                        metadata={"section": sec_title.lower()}
                    ))
        return docs
