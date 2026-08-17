"""HTML to Markdown converter for WordPress post content."""

import html
import re
from typing import Tuple


class HtmlToMarkdownConverter:
    """Converts HTML content to clean, readable Markdown with error-tolerant fallback."""

    @classmethod
    def convert(cls, html_content: str) -> Tuple[str, bool]:
        """
        Convert HTML string to Markdown.
        Returns: (markdown_text, is_successful)
        """
        if not html_content or not html_content.strip():
            return "", True

        try:
            text = html_content

            # Remove scripts, styles, head, and comments
            text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
            text = re.sub(r"<(script|style|head)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)

            # Headings
            for i in range(6, 0, -1):
                pattern = rf"<h{i}[^>]*>(.*?)</h{i}>"
                prefix = "#" * i + " "
                text = re.sub(
                    pattern,
                    lambda m: f"\n\n{prefix}{cls._clean_inline(m.group(1))}\n\n",
                    text,
                    flags=re.DOTALL | re.IGNORECASE,
                )

            # Blockquotes
            text = re.sub(
                r"<blockquote[^>]*>(.*?)</blockquote>",
                lambda m: "\n\n" + "\n".join(f"> {line.strip()}" for line in cls._clean_inline(m.group(1)).split("\n") if line.strip()) + "\n\n",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )

            # Code blocks (<pre><code>...</code></pre>)
            text = re.sub(
                r"<pre[^>]*><code[^>]*>(.*?)</code></pre>",
                lambda m: f"\n\n```\n{html.unescape(m.group(1).strip())}\n```\n\n",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )

            # Inline code
            text = re.sub(
                r"<code[^>]*>(.*?)</code>",
                lambda m: f"`{html.unescape(m.group(1).strip())}`",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )

            # Images: <img ... src="..." alt="..." ...>
            text = re.sub(
                r'<img\b[^>]*src=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']*)["\'][^>]*>',
                r"![\2](\1)",
                text,
                flags=re.IGNORECASE,
            )
            # Images with alt before src
            text = re.sub(
                r'<img\b[^>]*alt=["\']([^"\']*)["\'][^>]*src=["\']([^"\']+)["\'][^>]*>',
                r"![\1](\2)",
                text,
                flags=re.IGNORECASE,
            )
            # Remaining img tags with src
            text = re.sub(
                r'<img\b[^>]*src=["\']([^"\']+)["\'][^>]*>',
                r"![](\1)",
                text,
                flags=re.IGNORECASE,
            )

            # Links: <a href="...">text</a>
            text = re.sub(
                r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                lambda m: f"[{cls._clean_inline(m.group(2))}]({m.group(1)})",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )

            # Bold
            text = re.sub(r"<(strong|b)[^>]*>(.*?)</\1>", r"**\2**", text, flags=re.DOTALL | re.IGNORECASE)

            # Italic
            text = re.sub(r"<(em|i)[^>]*>(.*?)</\1>", r"*\2*", text, flags=re.DOTALL | re.IGNORECASE)

            # List items
            text = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: f"- {cls._clean_inline(m.group(1))}\n", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"</?(ul|ol)[^>]*>", "\n", text, flags=re.IGNORECASE)

            # Paragraphs and line breaks
            text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
            text = re.sub(r"<p[^>]*>(.*?)</p>", lambda m: f"\n\n{cls._clean_inline(m.group(1))}\n\n", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<div[^>]*>(.*?)</div>", lambda m: f"\n{cls._clean_inline(m.group(1))}\n", text, flags=re.DOTALL | re.IGNORECASE)

            # Strip all other remaining HTML tags
            text = re.sub(r"<[^>]+>", "", text)

            # Unescape HTML entities
            text = html.unescape(text)

            # Normalize multiple empty lines
            text = re.sub(r"\n{3,}", "\n\n", text).strip()

            return text, True

        except Exception:
            # Fallback to simple tag stripped text if regex fails
            try:
                fallback = re.sub(r"<[^>]+>", "", html_content)
                return html.unescape(fallback).strip(), False
            except Exception:
                return html_content, False

    @staticmethod
    def _clean_inline(content: str) -> str:
        clean = re.sub(r"\s+", " ", content)
        return clean.strip()
