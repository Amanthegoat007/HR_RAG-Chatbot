import logging
from typing import Any

logger = logging.getLogger(__name__)

def build_context_window(conversation_history: list[dict[str, Any]], max_turns: int = 3) -> str:
    """
    Takes the raw conversation history and compresses it into a high-signal
    context string for the LLM prompt.
    """
    if not conversation_history:
        return ""
        
    # We want to keep the N most recent user-assistant pairs
    # A complete pair is 2 messages. So max_turns * 2 messages.
    recent_messages = conversation_history[-(max_turns * 2):]
    
    context_lines = []
    
    for idx, msg in enumerate(recent_messages):
        role = "User" if msg["role"] == "user" else "Assistant"
        content = msg["content"]
        
        # We don't want to blow up the context window with huge past assistant answers.
        # But we do need the gist.
        if role == "Assistant":
            # Just keep the first paragraph or chunk of the assistant response
            # as it usually contains the direct answer.
            paragraphs = [p for p in content.split("\n\n") if p.strip() and "<!--" not in p]
            if paragraphs:
                content = paragraphs[0]
                if len(content) > 300:
                    content = content[:300] + "..."
            else:
                content = content[:150] + "..."
                
        context_lines.append(f"{role}: {content.strip()}")
        
    if not context_lines:
        return ""
        
    return "CONVERSATION HISTORY:\n" + "\n".join(context_lines)
