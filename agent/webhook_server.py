"""
Webhook server for Physics Grading Agent.

Receives JSON array of questions, processes them in parallel using the grading agent,
and sends results to a webhook endpoint.

Run with: python webhook_server.py
Server will listen on port 8080
"""

import asyncio
import json
import logging
import time
from typing import Any
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# Load environment variables
from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Import the agent
from agent import root_agent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
FINAL_WEBHOOK_URL = "https://n8nyti.duckdns.org/webhook/final_grade"
MAX_PARALLEL_TASKS = 4  # Process 4 questions at a time
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
REQUEST_TIMEOUT = 120  # seconds per question

app = FastAPI(title="Physics Grading Webhook Server")


class GradingRequest(BaseModel):
    questions: list[dict[str, Any]]
    callback_url: str | None = None  # Optional override for webhook URL


class GradingResult(BaseModel):
    question_id: int
    order: int
    points_earned: float
    points_possible: float
    feedback: str
    correct_answer: str
    status: str  # "success" or "error"
    error_message: str | None = None


async def grade_single_question(
    question: dict,
    session_service: InMemorySessionService,
    runner: Runner,
    semaphore: asyncio.Semaphore
) -> dict:
    """
    Grade a single question with retry logic.
    """
    order = question.get("order", 0)

    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"Grading question {order} (attempt {attempt + 1}/{MAX_RETRIES})")

                # Format the question for the agent
                agent_input = format_question_for_agent(question)

                # Create a unique session for this question
                user_id = f"grader_{order}_{time.time()}"
                session = await session_service.create_session(
                    app_name="my_agent",
                    user_id=user_id
                )

                # Run the agent with timeout
                response_text = ""
                try:
                    async def run_agent():
                        text = ""
                        async for event in runner.run_async(
                            user_id=user_id,
                            session_id=session.id,
                            new_message=types.Content(
                                role="user",
                                parts=[types.Part(text=agent_input)]
                            )
                        ):
                            if hasattr(event, 'content') and event.content:
                                for part in event.content.parts:
                                    if hasattr(part, 'text') and part.text:
                                        text += part.text
                        return text

                    response_text = await asyncio.wait_for(
                        run_agent(),
                        timeout=REQUEST_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    raise Exception(f"Timeout after {REQUEST_TIMEOUT}s")

                # Parse the agent response
                result = parse_agent_response(response_text, order)
                result["status"] = "success"
                result["error_message"] = None

                logger.info(f"Question {order} graded successfully: {result['points_earned']}/{result['points_possible']}")
                return result

            except Exception as e:
                logger.error(f"Error grading question {order} (attempt {attempt + 1}): {e}")

                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))  # Exponential backoff
                else:
                    # All retries failed
                    return {
                        "question_id": order,
                        "order": order,
                        "points_earned": 0,
                        "points_possible": question.get("points_possible", 3),
                        "feedback": "Arvostelua ei voitu suorittaa teknisen virheen vuoksi.",
                        "correct_answer": "",
                        "status": "error",
                        "error_message": str(e)
                    }


def format_question_for_agent(question: dict) -> str:
    """
    Format a question dict into the JSON format the agent expects.
    """
    question_type = question.get("question_type", "text")

    formatted = {
        "question_text": question.get("question_text", ""),
        "question_type": question_type,
    }

    # Handle different answer formats
    if question_type == "multiple_choice":
        # Multiple choice - use selected_answers
        formatted["choices"] = question.get("choices", [])
        selected = question.get("selected_answers", [])
        formatted["student_answer"] = selected if selected else []
    else:
        # Text question - use answer field
        answer = question.get("answer", "")
        # Extract text from img tag if present
        if "<img" in answer and 'alt="' in answer:
            import re
            alt_match = re.search(r'alt="([^"]*)"', answer)
            if alt_match:
                answer = alt_match.group(1)
        formatted["student_answer"] = answer

    # Add course if available
    if "course" in question:
        formatted["course"] = question["course"]

    return json.dumps(formatted, ensure_ascii=False)


def parse_agent_response(response: str, order: int) -> dict:
    """
    Parse the agent's JSON response.
    IMPORTANT: question_id is ALWAYS set to order to ensure proper syncing.
    """
    try:
        # Try to find JSON in the response
        response = response.strip()

        # Find JSON object in response
        start_idx = response.find('{')
        end_idx = response.rfind('}') + 1

        if start_idx != -1 and end_idx > start_idx:
            json_str = response[start_idx:end_idx]
            result = json.loads(json_str)

            # ALWAYS use order as question_id for proper syncing
            return {
                "question_id": order,  # Always use order, ignore agent's question_id
                "order": order,
                "points_earned": float(result.get("points_earned", 0)),
                "points_possible": float(result.get("points_possible", 3)),
                "feedback": result.get("feedback", ""),
                "correct_answer": result.get("correct_answer", "")
            }
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse agent response: {e}")

    # Return default if parsing fails
    return {
        "question_id": order,
        "order": order,
        "points_earned": 0,
        "points_possible": 3,
        "feedback": "Vastauksen käsittelyssä tapahtui virhe.",
        "correct_answer": ""
    }


async def process_all_questions(questions: list[dict], callback_url: str) -> dict:
    """
    Process all questions in parallel batches and send results to webhook.
    """
    start_time = time.time()
    logger.info(f"Starting to grade {len(questions)} questions")

    # Create session service and runner
    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent,
        app_name="my_agent",
        session_service=session_service
    )

    # Semaphore to limit concurrent tasks
    semaphore = asyncio.Semaphore(MAX_PARALLEL_TASKS)

    # Create tasks for all questions
    tasks = [
        grade_single_question(q, session_service, runner, semaphore)
        for q in questions
    ]

    # Run all tasks concurrently (limited by semaphore)
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle any exceptions that weren't caught
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Unhandled exception for question {i}: {result}")
            processed_results.append({
                "question_id": i,
                "order": questions[i].get("order", i),
                "points_earned": 0,
                "points_possible": 3,
                "feedback": "Tekninen virhe arvioinnissa.",
                "correct_answer": "",
                "status": "error",
                "error_message": str(result)
            })
        else:
            processed_results.append(result)

    # Sort by order to ensure proper sequence
    processed_results.sort(key=lambda x: x["order"])

    # Verify order integrity - ensure question_id matches position
    for idx, result in enumerate(processed_results):
        expected_order = result["order"]
        # Ensure question_id always matches order
        result["question_id"] = expected_order
        logger.debug(f"Result {idx}: question_id={result['question_id']}, order={result['order']}")

    # Double-check: verify all orders are sequential starting from 0
    orders = [r["order"] for r in processed_results]
    expected_orders = list(range(len(processed_results)))
    if orders != expected_orders:
        logger.warning(f"Order mismatch! Got {orders}, expected {expected_orders}")
        # Re-assign question_ids based on sorted position if there are gaps
        for idx, result in enumerate(processed_results):
            result["question_id"] = result["order"]

    elapsed_time = time.time() - start_time
    logger.info(f"Graded {len(questions)} questions in {elapsed_time:.2f}s")

    # Prepare final payload
    final_payload = {
        "results": processed_results,
        "metadata": {
            "total_questions": len(questions),
            "successful": sum(1 for r in processed_results if r.get("status") == "success"),
            "failed": sum(1 for r in processed_results if r.get("status") == "error"),
            "processing_time_seconds": round(elapsed_time, 2),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
    }

    # Send to webhook with retries
    webhook_success = False
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    callback_url,
                    json=final_payload,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                webhook_success = True
                logger.info(f"Results sent to webhook successfully: {response.status_code}")
                break
        except Exception as e:
            logger.error(f"Failed to send to webhook (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)

    final_payload["webhook_sent"] = webhook_success
    return final_payload


@app.post("/grade")
async def grade_questions(questions: list[dict], background_tasks: BackgroundTasks):
    """
    Receive questions and start grading in background.
    Returns immediately with acknowledgment.
    """
    if not questions:
        raise HTTPException(status_code=400, detail="No questions provided")

    logger.info(f"Received {len(questions)} questions for grading")

    # Process in background
    background_tasks.add_task(
        process_all_questions,
        questions,
        FINAL_WEBHOOK_URL
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": f"Grading {len(questions)} questions",
            "questions_received": len(questions)
        }
    )


@app.post("/grade/sync")
async def grade_questions_sync(questions: list[dict]):
    """
    Receive questions and wait for grading to complete.
    Returns full results.
    """
    if not questions:
        raise HTTPException(status_code=400, detail="No questions provided")

    logger.info(f"Received {len(questions)} questions for synchronous grading")

    result = await process_all_questions(questions, FINAL_WEBHOOK_URL)
    return result


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "physics-grading-webhook"}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "Physics Grading Webhook Server",
        "endpoints": {
            "POST /grade": "Submit questions for async grading (returns immediately)",
            "POST /grade/sync": "Submit questions for sync grading (waits for results)",
            "GET /health": "Health check"
        },
        "config": {
            "max_parallel_tasks": MAX_PARALLEL_TASKS,
            "max_retries": MAX_RETRIES,
            "webhook_url": FINAL_WEBHOOK_URL
        }
    }


if __name__ == "__main__":
    logger.info("Starting Physics Grading Webhook Server...")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info"
    )
