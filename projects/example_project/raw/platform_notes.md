# Platform Notes

## Tools Considered

### Text Extraction
- **PyPDF2 / pypdf**: Pure Python, good for simple PDFs
- **pdfplumber**: Better for tables and structured PDFs
- **pymupdf (fitz)**: Fast, feature-rich, handles more PDF types

### Chunking Strategies
- **Fixed-size chunks**: Simple, predictable, easy to implement
- **Semantic chunks**: Better for meaning, requires NLP models
- **Paragraph-based**: Good middle ground for prose content

### Storage Formats
- **JSON**: Human-readable, easy to parse, good for structured metadata
- **JSONL**: Line-delimited JSON, great for streaming large datasets
- **Markdown**: Human-readable output, good for summaries and previews

## Decision Log

| Decision | Choice | Reason |
|----------|--------|--------|
| PDF library | pypdf | Pure Python, no system dependencies |
| Chunk size | 300–500 words | Balance between context and granularity |
| Output format | JSON + JSONL + MD | Covers structured data and human-readable outputs |
| Storage | File-based | Local-first, no database required for MVP |

## Notes on PDF Handling

Most PDFs from online courses use embedded fonts and may have formatting artefacts.
The pipeline should:
1. Extract raw text as-is
2. Clean up whitespace and line breaks in the cleaning step
3. Flag PDFs with low text yield (possible scanned images)
