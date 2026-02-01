from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
import json
import logging
import requests
import threading
from .models import Exam, Question, Choice, Answer, ExamSubmission, ChatSession, ChatMessage, ExamRequest, TutorChatSession, TutorChatMessage, CalendarSource, CalendarEvent, QuestionGrade
from datetime import datetime, timedelta
from icalendar import Calendar as ICalendar
from dateutil import rrule
from dateutil.parser import parse as parse_date
import pytz

logger = logging.getLogger(__name__)


def home(request):
    return render(request, 'main/home.html', {})


def maintenance(request):
    return render(request, 'main/maintenance.html', {})


def tutor(request):
    return render(request, 'main/tutor.html', {})


def createExam(request):
    # Exam creation view, which checks for an active exam
    active_exam = Exam.objects.filter(is_active=True).first()

    if active_exam:
        return redirect('exam', exam_id=active_exam.id)

    # Check for pending/processing exam request
    pending_request = ExamRequest.objects.filter(status__in=['pending', 'processing']).first()

    return render(request, 'main/examcreate.html', {
        'pending_request': pending_request
    })


@csrf_exempt
@require_http_methods(["POST"])
def webhook(request):
    # Webhook endpoint to receive exam data from external sources
    logger.info(f"Webhook received from {request.META.get('REMOTE_ADDR')}")

    try:
        try:
            data = json.loads(request.body)
            logger.info(f"JSON parsed successfully")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {str(e)}")
            return JsonResponse({
                'status': 'error',
                'message': 'Invalid JSON format',
                'details': str(e)
            }, status=400)

        if 'questions' not in data or 'config' not in data:
            logger.error("Missing required fields: questions or config")
            return JsonResponse({
                'status': 'error',
                'message': 'Missing required fields: questions or config',
                'received_keys': list(data.keys())
            }, status=400)

        questions_data = data['questions']
        config = data['config']

        logger.info(f"Received {len(questions_data)} questions")

        if 'exam_name' not in config:
            logger.error("Missing exam_name in config")
            return JsonResponse({
                'status': 'error',
                'message': 'Missing exam_name in config',
                'config_keys': list(config.keys())
            }, status=400)

        old_exams_count = Exam.objects.filter(is_active=True).count()
        Exam.objects.filter(is_active=True).update(is_active=False)
        if old_exams_count > 0:
            logger.info(f"Deactivated {old_exams_count} previous exam(s)")

        exam = Exam.objects.create(
            name=config['exam_name'],
            description=config.get('exam_description', ''),
            time_limit=config.get('exam_time', None),
            is_active=True
        )
        logger.info(f"Created exam: '{exam.name}' (ID: {exam.id})")

        text_count = 0
        mc_count = 0

        for idx, q_data in enumerate(questions_data):
            if 'question_type' not in q_data or 'question_text' not in q_data:
                exam.delete()
                logger.error(f"Invalid question data at index {idx}")
                return JsonResponse({
                    'status': 'error',
                    'message': f'Invalid question data at index {idx}',
                    'question_data': q_data
                }, status=400)

            question = Question.objects.create(
                exam=exam,
                question_type=q_data['question_type'],
                question_text=q_data['question_text'],
                order=idx
            )

            if q_data['question_type'] == 'text':
                text_count += 1
                logger.info(f"Q{idx+1}: Text question created")
            elif q_data['question_type'] == 'multiple_choice':
                choices = q_data.get('choices', [])
                if not choices or len(choices) < 2 or len(choices) > 8:
                    exam.delete()
                    logger.error(f"Invalid choices count at Q{idx+1}: {len(choices)}")
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Multiple choice question at index {idx} must have 2-8 choices',
                        'choices_provided': len(choices)
                    }, status=400)

                for choice_idx, choice_text in enumerate(choices):
                    Choice.objects.create(
                        question=question,
                        choice_text=choice_text,
                        order=choice_idx
                    )
                mc_count += 1
                logger.info(f"Q{idx+1}: Multiple choice with {len(choices)} options created")

        logger.info(f"Exam created successfully!")
        logger.info(f"Summary: {text_count} text, {mc_count} multiple choice")

        return JsonResponse({
            'status': 'success',
            'message': 'Exam created successfully!',
            'exam_id': exam.id,
            'exam_name': exam.name,
            'exam_url': f'http://{request.get_host()}/exam/{exam.id}/',
            'questions_count': exam.questions.count(),
            'breakdown': {
                'text_questions': text_count,
                'multiple_choice': mc_count
            },
            'time_limit': exam.time_limit,
            'time_limit_formatted': f"{exam.time_limit // 60} minutes" if exam.time_limit else "No time limit"
        })

    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return JsonResponse({
            'status': 'error',
            'message': f'Server error: {str(e)}',
            'error_type': type(e).__name__
        }, status=500)


def exam(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id)
    questions = exam.questions.prefetch_related('choices').all()

    # Load existing answers
    answers_dict = {}
    for answer in Answer.objects.filter(exam=exam):
        if answer.question.question_type == 'text':
            answers_dict[str(answer.question.id)] = answer.answer_text or ""
        else:
            answers_dict[str(answer.question.id)] = answer.selected_choices or []

    questions_with_answers = []
    for question in questions:
        q_data = {
            'question': question,
            'answer': answers_dict.get(str(question.id), [] if question.question_type == 'multiple_choice' else "")
        }
        questions_with_answers.append(q_data)

    time_remaining = None
    if exam.started_at and exam.time_limit:
        elapsed = (timezone.now() - exam.started_at).total_seconds()
        time_remaining = max(0, exam.time_limit - elapsed)

    context = {
        'exam': exam,
        'questions_with_answers': questions_with_answers,
        'questions': questions,
        'answers_json': json.dumps(answers_dict),
        'started_at': exam.started_at.isoformat() if exam.started_at else None,
        'time_remaining': time_remaining,
    }

    return render(request, 'main/exam.html', context)


@csrf_exempt
@require_http_methods(["POST"])
def save_answer(request):
    # Auto-save answer endpoint
    try:
        data = json.loads(request.body)

        exam_id = data.get('exam_id')
        question_id = data.get('question_id')
        answer_data = data.get('answer')

        logger.info(f"Save answer: Q{question_id}, Data: {answer_data}, Type: {type(answer_data)}")

        if not all([exam_id, question_id]):
            return JsonResponse({
                'status': 'error',
                'message': 'Missing required fields'
            }, status=400)

        exam = get_object_or_404(Exam, id=exam_id)
        question = get_object_or_404(Question, id=question_id, exam=exam)

        answer, created = Answer.objects.get_or_create(
            exam=exam,
            question=question
        )

        if question.question_type == 'text':
            # Handle rich text editor output - extract answerHtml if it's an object
            if isinstance(answer_data, dict) and 'answerHtml' in answer_data:
                answer.answer_text = answer_data['answerHtml']
            else:
                answer.answer_text = answer_data
            answer.selected_choices = None
            logger.info(f"Saved text answer")
        else:
            answer.selected_choices = answer_data if answer_data else []
            answer.answer_text = None
            logger.info(f"Saved multiple choice: {answer.selected_choices}")

        answer.save()

        return JsonResponse({
            'status': 'success',
            'message': 'Answer saved'
        })

    except Exception as e:
        logger.error(f"Error saving answer: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def start_exam(request, exam_id):
    # Start the exam and record start time
    exam = get_object_or_404(Exam, id=exam_id)

    if not exam.started_at:
        exam.started_at = timezone.now()
        exam.save()
        logger.info(f"Exam {exam.id} started at {exam.started_at}")

    return JsonResponse({
        'status': 'success',
        'started_at': exam.started_at.isoformat(),
        'time_limit': exam.time_limit
    })


@csrf_exempt
@require_http_methods(["POST"])
def end_exam(request, exam_id):
    # End the exam and save complete submission
    exam = get_object_or_404(Exam, id=exam_id)

    time_taken = None
    if exam.started_at:
        time_taken = int((timezone.now() - exam.started_at).total_seconds())

    questions_data = []
    for question in exam.questions.all():
        question_dict = {
            'question_text': question.question_text,
            'question_type': question.question_type,
            'order': question.order
        }

        if question.question_type == 'text':
            answer = Answer.objects.filter(exam=exam, question=question).first()
            answer_text = answer.answer_text if answer else ""
            # Handle if answer was stored as JSON object (extract answerHtml)
            if answer_text and isinstance(answer_text, str):
                try:
                    parsed = json.loads(answer_text)
                    if isinstance(parsed, dict) and 'answerHtml' in parsed:
                        answer_text = parsed['answerHtml']
                except (json.JSONDecodeError, TypeError):
                    pass  # Not JSON, use as-is
            question_dict['answer'] = answer_text
        else:
            choices = []
            for choice in question.choices.all():
                choices.append({
                    'choice_text': choice.choice_text,
                    'order': choice.order
                })
            question_dict['choices'] = choices

            answer = Answer.objects.filter(exam=exam, question=question).first()
            if answer and answer.selected_choices:
                selected_texts = []
                for choice_id in answer.selected_choices:
                    choice = Choice.objects.filter(id=choice_id).first()
                    if choice:
                        selected_texts.append(choice.choice_text)
                question_dict['selected_answers'] = selected_texts
            else:
                question_dict['selected_answers'] = []

        questions_data.append(question_dict)

    submission_data = {
        'exam_name': exam.name,
        'exam_description': exam.description,
        'time_limit': exam.time_limit,
        'time_taken': time_taken,
        'submitted_at': timezone.now().isoformat(),
        'questions': questions_data
    }

    ExamSubmission.objects.create(
        exam_name=exam.name,
        exam_description=exam.description,
        time_taken=time_taken,
        submission_data=submission_data
    )

    logger.info(f"   Exam submission saved: {exam.name}")
    logger.info(f"   Questions: {len(questions_data)}")
    logger.info(f"   Time taken: {time_taken}s" if time_taken else "   No time limit")

    # Send submission data to webhook
    webhook_url = 'https://n8nyti.duckdns.org/webhook/39c34d6e-b38a-4353-a562-cbd1e240f322'
    try:
        requests.post(webhook_url, json=submission_data, timeout=10)
        logger.info(f"   Webhook sent successfully")
    except Exception as e:
        logger.error(f"   Webhook error: {str(e)}")

    exam.is_active = False
    exam.save()

    return redirect('home')



def ai_teacher(request):
    sessions = ChatSession.objects.all()
    return render(request, 'main/ai_teacher.html', {'sessions': sessions})


@csrf_exempt
@require_http_methods(["POST"])
def create_chat(request):
    try:
        data = json.loads(request.body)
        model_type = data.get('model_type', 'teacher')
        session = ChatSession.objects.create(model_type=model_type, title='New Chat')
        return JsonResponse({
            'status': 'success',
            'session_id': str(session.session_id),
            'title': session.title,
            'model_type': session.model_type
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def rename_chat(request, session_id):
    try:
        data = json.loads(request.body)
        title = data.get('title')
        session = get_object_or_404(ChatSession, session_id=session_id)
        session.title = title
        session.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def delete_chat(request, session_id):
    try:
        session = get_object_or_404(ChatSession, session_id=session_id)
        session.delete()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def send_message(request):
    try:
        data = json.loads(request.body)
        message = data.get('message')
        session_id = data.get('session_id')

        if not session_id:
            return JsonResponse({'status': 'error', 'message': 'No session_id provided'}, status=400)

        session = get_object_or_404(ChatSession, session_id=session_id)
        
        ChatMessage.objects.create(session=session, sender='user', content=message)

        if session.messages.count() == 1:
            title = message[:50] if len(message) > 50 else message
            session.title = title
            session.save()

        webhook_url = request.build_absolute_uri(f'/api/ai-webhook/{session_id}/')

        if session.model_type == 'exam':
            api_url = "https://n8nyti.duckdns.org/webhook/Ai_exam"
        else:
            api_url = "https://n8nyti.duckdns.org/webhook/Ai_teacher"

        try:
            requests.post(api_url, json={
                "message": message,
                "webhook_url": webhook_url,
                "chat_id": session_id
            }, timeout=10)
        except Exception as e:
            logger.error(f"Failed to call AI: {e}")

        return JsonResponse({'status': 'success', 'session_id': session_id})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def ai_webhook(request, session_id):
    try:
        data = json.loads(request.body)
        answer = data.get('answer')
        
        if answer:
            session = get_object_or_404(ChatSession, session_id=session_id)
            ChatMessage.objects.create(session=session, sender='ai', content=answer)

        return JsonResponse({'status': 'success'})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JsonResponse({'status': 'error'}, status=500)


def get_messages(request, session_id):
    session = get_object_or_404(ChatSession, session_id=session_id)
    messages = session.messages.all()
    data = [{'sender': m.sender, 'content': m.content} for m in messages]
    return JsonResponse({
        'messages': data,
        'title': session.title,
        'model_type': session.model_type
    })


def get_all_chats(request):
    sessions = ChatSession.objects.all()
    data = [{
        'session_id': str(s.session_id),
        'title': s.title,
        'model_type': s.model_type,
        'created_at': s.created_at.isoformat()
    } for s in sessions]
    return JsonResponse({'chats': data})


# ============================================
# TUTOR CHAT VIEWS - Separate database
# ============================================

@csrf_exempt
@require_http_methods(["POST"])
def tutor_create_chat(request):
    """Create a new tutor chat session"""
    try:
        session = TutorChatSession.objects.using('tutor').create(title='New Chat')
        return JsonResponse({
            'status': 'success',
            'session_id': str(session.session_id),
            'title': session.title
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def tutor_rename_chat(request, session_id):
    """Rename a tutor chat session"""
    try:
        data = json.loads(request.body)
        title = data.get('title')
        session = TutorChatSession.objects.using('tutor').get(session_id=session_id)
        session.title = title
        session.save(using='tutor')
        return JsonResponse({'status': 'success'})
    except TutorChatSession.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Session not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def tutor_delete_chat(request, session_id):
    """Delete a tutor chat session"""
    try:
        session = TutorChatSession.objects.using('tutor').get(session_id=session_id)
        session.delete(using='tutor')
        return JsonResponse({'status': 'success'})
    except TutorChatSession.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Session not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def tutor_send_message(request):
    """Send a message in tutor chat (no AI connection yet)"""
    try:
        data = json.loads(request.body)
        message = data.get('message')
        session_id = data.get('session_id')

        if not session_id:
            return JsonResponse({'status': 'error', 'message': 'No session_id provided'}, status=400)

        session = TutorChatSession.objects.using('tutor').get(session_id=session_id)

        # Save user message
        TutorChatMessage.objects.using('tutor').create(session=session, sender='user', content=message)

        # Update title if first message
        if session.messages.using('tutor').count() == 1:
            title = message[:50] if len(message) > 50 else message
            session.title = title
            session.save(using='tutor')

        # Note: No AI webhook call - tutor is not connected yet

        return JsonResponse({'status': 'success', 'session_id': str(session_id)})
    except TutorChatSession.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Session not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def tutor_get_messages(request, session_id):
    """Get all messages for a tutor chat session"""
    try:
        session = TutorChatSession.objects.using('tutor').get(session_id=session_id)
        messages = session.messages.using('tutor').all()
        data = [{'sender': m.sender, 'content': m.content} for m in messages]
        return JsonResponse({
            'messages': data,
            'title': session.title
        })
    except TutorChatSession.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Session not found'}, status=404)


def tutor_get_all_chats(request):
    """Get all tutor chat sessions"""
    sessions = TutorChatSession.objects.using('tutor').all()
    data = [{
        'session_id': str(s.session_id),
        'title': s.title,
        'created_at': s.created_at.isoformat()
    } for s in sessions]
    return JsonResponse({'chats': data})


def _call_exam_webhook_async(api_url, payload, request_id):
    """Background thread to call the exam webhook"""
    try:
        requests.post(api_url, json=payload, timeout=30)
        logger.info(f"Exam request {request_id} sent to AI service")
    except Exception as e:
        logger.error(f"Failed to call exam AI for {request_id}: {e}")
        # Update the request status on failure
        try:
            exam_request = ExamRequest.objects.get(request_id=request_id)
            exam_request.status = 'error'
            exam_request.error_message = f'Failed to contact AI service: {str(e)}'
            exam_request.save()
        except Exception:
            pass


@csrf_exempt
@require_http_methods(["POST"])
def request_exam(request):
    """Create a new exam generation request and send to AI"""
    try:
        data = json.loads(request.body)
        subject = data.get('subject', '').strip()
        num_questions = data.get('num_questions', 5)

        if not subject:
            return JsonResponse({
                'status': 'error',
                'message': 'Subject is required'
            }, status=400)

        # Cancel any existing pending requests
        ExamRequest.objects.filter(status__in=['pending', 'processing']).update(status='error', error_message='Cancelled')

        # Create new request
        exam_request = ExamRequest.objects.create(
            subject=subject,
            num_questions=num_questions,
            status='processing'
        )

        # Build webhook URL for AI response - use ngrok URL for external access
        webhook_url = f'https://gerardo-fogyish-modularly.ngrok-free.dev/api/exam-webhook/{exam_request.request_id}/'

        # Call AI service in background thread (non-blocking)
        api_url = "https://n8nyti.duckdns.org/webhook/exam_build"
        payload = {
            "subject": subject,
            "num_questions": num_questions,
            "webhook_url": webhook_url,
            "request_id": str(exam_request.request_id)
        }

        thread = threading.Thread(
            target=_call_exam_webhook_async,
            args=(api_url, payload, exam_request.request_id)
        )
        thread.daemon = True
        thread.start()

        # Return immediately - don't wait for webhook
        return JsonResponse({
            'status': 'success',
            'request_id': str(exam_request.request_id)
        })

    except Exception as e:
        logger.error(f"Error creating exam request: {e}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def exam_webhook(request, request_id):
    """Receive exam data from AI service"""
    try:
        exam_request = get_object_or_404(ExamRequest, request_id=request_id)

        # Log raw request for debugging
        raw_body = request.body.decode('utf-8') if request.body else ''
        logger.info(f"Exam webhook received for {request_id}, body length: {len(raw_body)}")

        if not raw_body:
            exam_request.status = 'error'
            exam_request.error_message = 'Empty request body'
            exam_request.completed_at = timezone.now()
            exam_request.save()
            return JsonResponse({'status': 'error', 'message': 'Empty request body'}, status=400)

        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError as e:
            exam_request.status = 'error'
            exam_request.error_message = f'Invalid JSON: {str(e)}'
            exam_request.completed_at = timezone.now()
            exam_request.save()
            return JsonResponse({'status': 'error', 'message': f'Invalid JSON: {str(e)}'}, status=400)

        # Check for error response
        if 'answer' in data:
            answer = data['answer']
            if isinstance(answer, str) and answer.startswith('Error'):
                exam_request.status = 'error'
                exam_request.error_message = answer
                exam_request.completed_at = timezone.now()
                exam_request.save()
                return JsonResponse({'status': 'error', 'message': answer})

        # Try to find exam data - support multiple formats
        exam_data = None

        # Format 1: Direct format from agent {"questions": [], "config": {}}
        if 'questions' in data and 'config' in data:
            exam_data = data
        # Format 2: Wrapped in "answer" {"answer": {"questions": [], "config": {}}}
        elif 'answer' in data:
            answer = data['answer']
            if isinstance(answer, str):
                try:
                    exam_data = json.loads(answer)
                except:
                    pass
            elif isinstance(answer, dict):
                exam_data = answer
        # Format 3: Wrapped in "data" {"data": {"questions": [], "config": {}}}
        elif 'data' in data:
            exam_data = data['data']

        if not exam_data or 'questions' not in exam_data or 'config' not in exam_data:
            exam_request.status = 'error'
            exam_request.error_message = f'Invalid format. Keys received: {list(data.keys())}'
            exam_request.completed_at = timezone.now()
            exam_request.save()
            logger.error(f"Invalid exam format. Keys: {list(data.keys())}")
            return JsonResponse({'status': 'error', 'message': 'Missing questions or config'}, status=400)

        # Parse exam data
        try:

            questions_data = exam_data['questions']
            config = exam_data['config']

            # Deactivate old exams
            Exam.objects.filter(is_active=True).update(is_active=False)

            # Create the exam
            exam = Exam.objects.create(
                name=config.get('exam_name', f'Koe: {exam_request.subject[:50]}'),
                description=config.get('exam_description', ''),
                time_limit=config.get('exam_time', None),
                is_active=True
            )

            # Create questions
            for idx, q_data in enumerate(questions_data):
                question = Question.objects.create(
                    exam=exam,
                    question_type=q_data.get('question_type', 'text'),
                    question_text=q_data.get('question_text', ''),
                    order=idx
                )

                if q_data.get('question_type') == 'multiple_choice':
                    choices = q_data.get('choices', [])
                    for choice_idx, choice_text in enumerate(choices):
                        Choice.objects.create(
                            question=question,
                            choice_text=choice_text,
                            order=choice_idx
                        )

            # Update request
            exam_request.status = 'completed'
            exam_request.exam = exam
            exam_request.completed_at = timezone.now()
            exam_request.save()

            logger.info(f"Exam created from request {request_id}: {exam.name}")
            return JsonResponse({'status': 'success', 'exam_id': exam.id})

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            exam_request.status = 'error'
            exam_request.error_message = f'Invalid exam data: {str(e)}'
            exam_request.completed_at = timezone.now()
            exam_request.save()
            logger.error(f"Failed to parse exam data: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    except Exception as e:
        logger.error(f"Exam webhook error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def get_exam_request_status(request, request_id):
    """Check the status of an exam generation request"""
    try:
        exam_request = get_object_or_404(ExamRequest, request_id=request_id)

        response_data = {
            'status': exam_request.status,
            'subject': exam_request.subject,
            'num_questions': exam_request.num_questions,
            'created_at': exam_request.created_at.isoformat()
        }

        if exam_request.status == 'completed' and exam_request.exam:
            response_data['exam_id'] = exam_request.exam.id

        if exam_request.status == 'error':
            response_data['error_message'] = exam_request.error_message

        return JsonResponse(response_data)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def cancel_exam_request(request):
    """Cancel pending exam request"""
    try:
        ExamRequest.objects.filter(status__in=['pending', 'processing']).update(
            status='error',
            error_message='Cancelled by user'
        )
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def exam_history(request):
    """View all previous exam submissions"""
    submissions = ExamSubmission.objects.all()
    return render(request, 'main/exam_history.html', {'submissions': submissions})


def exam_review(request, submission_id):
    """View a specific exam submission with all questions and answers"""
    submission = get_object_or_404(ExamSubmission, id=submission_id)

    # Get grades for this submission, indexed by question order
    grades_dict = {}
    if submission.is_graded:
        for grade in submission.grades.all():
            grades_dict[grade.order] = grade

    return render(request, 'main/exam_review.html', {
        'submission': submission,
        'grades': grades_dict
    })


@csrf_exempt
@require_http_methods(["POST"])
def grading_webhook(request):
    """
    Webhook to receive grading results from external grading system.
    Expects a JSON array of question grades that will be applied to the latest submission.
    """
    logger.info(f"Grading webhook received from {request.META.get('REMOTE_ADDR')}")

    try:
        # Parse the incoming JSON
        try:
            grades_data = json.loads(request.body)
            logger.info(f"Received {len(grades_data)} grade entries")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in grading webhook: {e}")
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

        # Validate that we received a list
        if not isinstance(grades_data, list):
            return JsonResponse({'status': 'error', 'message': 'Expected a list of grades'}, status=400)

        # Get the latest submission (most recently submitted exam)
        latest_submission = ExamSubmission.objects.order_by('-submitted_at').first()

        if not latest_submission:
            logger.error("No exam submissions found to grade")
            return JsonResponse({'status': 'error', 'message': 'No exam submissions found'}, status=404)

        logger.info(f"Applying grades to submission: {latest_submission.id} - {latest_submission.exam_name}")

        # Clear any existing grades for this submission
        QuestionGrade.objects.filter(submission=latest_submission).delete()

        # Process each grade entry
        total_earned = 0
        total_possible = 0

        for grade_entry in grades_data:
            question_id = grade_entry.get('question_id', 0)
            order = grade_entry.get('order', question_id)
            points_earned = grade_entry.get('points_earned', 0)
            points_possible = grade_entry.get('points_possible', 0)
            feedback = grade_entry.get('feedback', '')
            correct_answer = grade_entry.get('correct_answer', '')
            status = grade_entry.get('status', 'success')
            error_message = grade_entry.get('error_message')

            # Create the grade record
            QuestionGrade.objects.create(
                submission=latest_submission,
                question_id=question_id,
                order=order,
                points_earned=points_earned,
                points_possible=points_possible,
                feedback=feedback,
                correct_answer=correct_answer,
                status=status,
                error_message=error_message
            )

            total_earned += points_earned
            total_possible += points_possible

            logger.info(f"  Q{order}: {points_earned}/{points_possible} points")

        # Update the submission with grading status
        latest_submission.is_graded = True
        latest_submission.graded_at = timezone.now()
        latest_submission.total_points_earned = total_earned
        latest_submission.total_points_possible = total_possible
        latest_submission.save()

        logger.info(f"Grading complete: {total_earned}/{total_possible} total points")

        return JsonResponse({
            'status': 'success',
            'submission_id': latest_submission.id,
            'total_earned': total_earned,
            'total_possible': total_possible,
            'percentage': latest_submission.grade_percentage
        })

    except Exception as e:
        logger.error(f"Grading webhook error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


# ============================================
# CALENDAR VIEWS
# ============================================

def calendar_view(request):
    """Main calendar page"""
    sources = CalendarSource.objects.filter(is_active=True)
    return render(request, 'main/calendar.html', {'sources': sources})


@csrf_exempt
@require_http_methods(["GET"])
def calendar_get_events(request):
    """Get all events - no filtering"""
    try:
        # Return ALL events, let frontend handle display
        events = CalendarEvent.objects.all()

        events_data = []
        for event in events:
            events_data.append({
                'id': event.id,
                'title': event.title,
                'description': event.description or '',
                'start': event.start_time.isoformat(),
                'end': event.end_time.isoformat(),
                'allDay': event.all_day,
                'location': event.location or '',
                'color': event.color,
                'sourceId': event.source.id if event.source else None,
                'isManual': event.is_manual
            })

        return JsonResponse({'status': 'success', 'events': events_data})
    except Exception as e:
        logger.error(f"Error getting calendar events: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def calendar_create_event(request):
    """Create a new manual event"""
    try:
        data = json.loads(request.body)

        start_time = parse_date(data['start'])
        end_time = parse_date(data['end']) if data.get('end') else start_time + timedelta(hours=1)

        event = CalendarEvent.objects.create(
            title=data['title'],
            description=data.get('description', ''),
            start_time=start_time,
            end_time=end_time,
            all_day=data.get('allDay', False),
            location=data.get('location', ''),
            color=data.get('color', '#5a9ba8'),
            is_manual=True
        )

        return JsonResponse({
            'status': 'success',
            'event': {
                'id': event.id,
                'title': event.title,
                'start': event.start_time.isoformat(),
                'end': event.end_time.isoformat(),
                'color': event.color
            }
        })
    except Exception as e:
        logger.error(f"Error creating calendar event: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["PUT"])
def calendar_update_event(request, event_id):
    """Update an existing event"""
    try:
        data = json.loads(request.body)
        event = get_object_or_404(CalendarEvent, id=event_id)

        if 'title' in data:
            event.title = data['title']
        if 'description' in data:
            event.description = data['description']
        if 'start' in data:
            event.start_time = parse_date(data['start'])
        if 'end' in data:
            event.end_time = parse_date(data['end'])
        if 'allDay' in data:
            event.all_day = data['allDay']
        if 'location' in data:
            event.location = data['location']
        if 'color' in data:
            event.color = data['color']

        event.save()

        return JsonResponse({
            'status': 'success',
            'event': {
                'id': event.id,
                'title': event.title,
                'start': event.start_time.isoformat(),
                'end': event.end_time.isoformat(),
                'color': event.color
            }
        })
    except Exception as e:
        logger.error(f"Error updating calendar event: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["DELETE"])
def calendar_delete_event(request, event_id):
    """Delete an event"""
    try:
        event = get_object_or_404(CalendarEvent, id=event_id)
        event.delete()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        logger.error(f"Error deleting calendar event: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def calendar_get_sources(request):
    """Get all calendar sources"""
    try:
        sources = CalendarSource.objects.all()
        sources_data = [{
            'id': source.id,
            'name': source.name,
            'url': source.url,
            'color': source.color,
            'isActive': source.is_active,
            'lastSynced': source.last_synced.isoformat() if source.last_synced else None
        } for source in sources]

        return JsonResponse({'status': 'success', 'sources': sources_data})
    except Exception as e:
        logger.error(f"Error getting calendar sources: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def calendar_add_source(request):
    """Add a new calendar source (ICS URL)"""
    try:
        data = json.loads(request.body)

        source = CalendarSource.objects.create(
            name=data['name'],
            url=data['url'],
            color=data.get('color', '#5a9ba8'),
            is_active=True
        )

        # Sync events from the source
        sync_calendar_source(source)

        return JsonResponse({
            'status': 'success',
            'source': {
                'id': source.id,
                'name': source.name,
                'url': source.url,
                'color': source.color,
                'isActive': source.is_active
            }
        })
    except Exception as e:
        logger.error(f"Error adding calendar source: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["PUT"])
def calendar_update_source(request, source_id):
    """Update a calendar source"""
    try:
        data = json.loads(request.body)
        source = get_object_or_404(CalendarSource, id=source_id)

        if 'name' in data:
            source.name = data['name']
        if 'color' in data:
            source.color = data['color']
            # Update all events from this source with the new color
            CalendarEvent.objects.filter(source=source).update(color=data['color'])
        if 'isActive' in data:
            source.is_active = data['isActive']

        source.save()

        return JsonResponse({
            'status': 'success',
            'source': {
                'id': source.id,
                'name': source.name,
                'color': source.color,
                'isActive': source.is_active
            }
        })
    except Exception as e:
        logger.error(f"Error updating calendar source: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["DELETE"])
def calendar_delete_source(request, source_id):
    """Delete a calendar source and all its events"""
    try:
        source = get_object_or_404(CalendarSource, id=source_id)
        # Delete all events from this source
        CalendarEvent.objects.filter(source=source).delete()
        source.delete()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        logger.error(f"Error deleting calendar source: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def calendar_sync_source(request, source_id):
    """Manually sync a calendar source"""
    try:
        source = get_object_or_404(CalendarSource, id=source_id)
        sync_calendar_source(source)
        return JsonResponse({'status': 'success', 'message': 'Calendar synced successfully'})
    except Exception as e:
        logger.error(f"Error syncing calendar source: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def sync_calendar_source(source):
    """Fetch and parse ICS file from source URL - imports ALL events"""
    try:
        response = requests.get(source.url, timeout=30)
        response.raise_for_status()

        cal = ICalendar.from_ical(response.content)

        # Delete old events from this source
        CalendarEvent.objects.filter(source=source).delete()

        events_created = 0

        # Very wide date range for recurring events (5 years back to 5 years forward)
        now = timezone.now()
        start_range = now - timedelta(days=1825)
        end_range = now + timedelta(days=1825)

        for component in cal.walk():
            if component.name == "VEVENT":
                try:
                    uid = str(component.get('uid', ''))
                    summary = str(component.get('summary', 'No Title'))
                    description = str(component.get('description', '')) if component.get('description') else ''
                    location = str(component.get('location', '')) if component.get('location') else ''

                    dtstart = component.get('dtstart')
                    dtend = component.get('dtend')

                    if dtstart:
                        start_dt = dtstart.dt
                        all_day = not hasattr(start_dt, 'hour')

                        # Handle date objects (all-day events)
                        if all_day:
                            start_dt = timezone.make_aware(
                                datetime.combine(start_dt, datetime.min.time()),
                                pytz.UTC
                            )

                        if dtend:
                            end_dt = dtend.dt
                            if not hasattr(end_dt, 'hour'):
                                end_dt = timezone.make_aware(
                                    datetime.combine(end_dt, datetime.min.time()),
                                    pytz.UTC
                                )
                        else:
                            end_dt = start_dt + timedelta(hours=1)

                        # Make timezone aware if not already
                        if timezone.is_naive(start_dt):
                            start_dt = timezone.make_aware(start_dt, pytz.UTC)
                        if timezone.is_naive(end_dt):
                            end_dt = timezone.make_aware(end_dt, pytz.UTC)

                        # Handle recurring events
                        rrule_str = component.get('rrule')
                        if rrule_str:
                            try:
                                rule = rrule.rrulestr(rrule_str.to_ical().decode('utf-8'), dtstart=start_dt)
                                occurrences = list(rule.between(start_range, end_range, inc=True))

                                for occ_start in occurrences:
                                    duration = end_dt - start_dt
                                    occ_end = occ_start + duration

                                    CalendarEvent.objects.create(
                                        title=summary,
                                        description=description,
                                        start_time=occ_start,
                                        end_time=occ_end,
                                        all_day=all_day,
                                        location=location,
                                        color=source.color,
                                        source=source,
                                        external_uid=f"{uid}_{occ_start.isoformat()}",
                                        is_manual=False
                                    )
                                    events_created += 1
                            except Exception as rrule_error:
                                logger.warning(f"Error parsing rrule for event {uid}: {rrule_error}")
                                # Fall back to creating single event
                                CalendarEvent.objects.create(
                                    title=summary,
                                    description=description,
                                    start_time=start_dt,
                                    end_time=end_dt,
                                    all_day=all_day,
                                    location=location,
                                    color=source.color,
                                    source=source,
                                    external_uid=uid,
                                    is_manual=False
                                )
                                events_created += 1
                        else:
                            # Single event - import it regardless of date
                            CalendarEvent.objects.create(
                                title=summary,
                                description=description,
                                start_time=start_dt,
                                end_time=end_dt,
                                all_day=all_day,
                                location=location,
                                color=source.color,
                                source=source,
                                external_uid=uid,
                                is_manual=False
                            )
                            events_created += 1
                except Exception as event_error:
                    logger.warning(f"Error parsing event: {event_error}")
                    continue

        source.last_synced = timezone.now()
        source.save()
        logger.info(f"Calendar source '{source.name}' synced successfully - {events_created} events created")

    except Exception as e:
        logger.error(f"Error syncing calendar source '{source.name}': {str(e)}")
        raise

