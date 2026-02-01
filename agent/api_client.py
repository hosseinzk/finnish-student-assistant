"""
Simple API client to interact with the PhysicsGrader agent.

Usage:
    python api_client.py "Your question here"

Or import and use in code:
    from api_client import grade_answer
    result = grade_answer('{"question_text": "...", "student_answer": "..."}')
"""

import asyncio
import os
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Import the agent
from agent import root_agent


def grade_answer(question_json: str) -> str:
    """
    Send a grading request to the PhysicsGrader agent.

    Args:
        question_json: JSON string with the question data, e.g.:
            {
                "question_text": "Laske putoamisaika...",
                "question_type": "text",
                "student_answer": "t = 2,5 s",
                "course": "FY1"
            }

    Returns:
        The agent's grading response (JSON string)
    """
    return asyncio.run(_grade_async(question_json))


async def _grade_async(question_json: str) -> str:
    """Async implementation of grading."""

    # Create session service and runner
    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent,
        app_name="my_agent",
        session_service=session_service
    )

    # Create a session
    user_id = "api_user"
    session = await session_service.create_session(
        app_name="my_agent",
        user_id=user_id
    )

    # Run the agent
    response_text = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=question_json)]
        )
    ):
        if hasattr(event, 'content') and event.content:
            for part in event.content.parts:
                if hasattr(part, 'text') and part.text:
                    response_text += part.text

    return response_text


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        question = sys.argv[1]
    else:
        # Example question
        question = '''{
  "question_text": "Kappale putoaa vapaasti 10 metrin korkeudesta. Laske putoamisaika.",
  "question_type": "text",
  "student_answer": "t = 1,4 s",
  "course": "FY1"
}'''

    print("Sending to PhysicsGrader agent...")
    print("-" * 50)
    result = grade_answer(question)
    print(result)
