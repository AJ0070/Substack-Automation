"""Prompt templates for the Gemini generation pipeline."""

from __future__ import annotations

TOPICS = (
    "Linux",
    "Git",
    "systems programming",
    "HPC",
    "sparse matrices",
    "SIMD",
    "RISC-V",
    "Julia",
    "C/C++",
)

VOICE_RULES = """
Write for a curious beginner who can program a little but is new to the topic.
Use a conversational technical tone, concrete examples, small analogies, and practical takeaways.
Avoid hype, filler, generic AI phrasing, and phrases like "in today's digital world".
Prefer short sections, clear definitions, and examples readers can try locally.
"""


def topic_prompt() -> str:
    return f"""
Pick one beginner-friendly technical blog topic from this domain list:
{", ".join(TOPICS)}.

Return only a compact JSON object with:
- topic: the exact article topic
- audience: the intended beginner audience
- angle: the teaching angle
- keywords: 5 SEO keywords

The topic should be specific enough for a useful 900-1400 word article.
"""


def outline_prompt(topic_json: str) -> str:
    return f"""
Create a practical outline for this technical blog.

Topic metadata:
{topic_json}

{VOICE_RULES}

Return markdown with:
- SEO title
- one-sentence description
- 5 to 7 section headings
- notes for examples or analogies in each section
"""


def section_prompt(topic_json: str, outline: str, section_heading: str) -> str:
    return f"""
Write the article section named: {section_heading}

Topic metadata:
{topic_json}

Full outline:
{outline}

{VOICE_RULES}

Return only markdown for this section. Include examples where helpful.
Do not include the article title unless this section is the introduction.
"""


def article_prompt(topic_json: str, outline: str) -> str:
    return f"""
Write the complete markdown article from this topic metadata and outline.

Topic metadata:
{topic_json}

Outline:
{outline}

{VOICE_RULES}

Requirements:
- 900 to 1400 words
- SEO-friendly H1 title
- beginner explanations
- practical examples
- at least one analogy
- concise closing takeaway
- no robotic AI tone

Return only the complete markdown article.
"""


def polish_prompt(draft: str) -> str:
    return f"""
Polish this markdown article for Substack publication.

Goals:
- Keep the article beginner-friendly and technically accurate.
- Make the title SEO-friendly.
- Keep the voice conversational, not robotic.
- Preserve markdown formatting.
- Add a concise closing takeaway.
- Remove repetition and vague filler.

Return only the final markdown article.

Draft:
{draft}
"""
