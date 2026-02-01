# Finnish Student Assistant

An AI-powered educational platform for Finnish high school students, featuring an AI Teacher, exam generation, automated grading, and personalized tutoring.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      DJANGO WEBSITE                              │
│  - AI Teacher chat                                               │
│  - Exam creation & taking (Abitti rich-text editor)             │
│  - Grading display                                               │
│  - Tutor chat                                                    │
│  - Calendar                                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    n8n / AGENT INFRASTRUCTURE                    │
│  - Teacher Agent (Claude + RAG)                                  │
│  - Exam Creator Agent                                            │
│  - Grader Agent                                                  │
│  - Tutor Agent                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
finnish-student-assistant/
├── main/                    # Django app
│   ├── templates/           # HTML templates
│   ├── static/              # CSS, JS, Abitti editor
│   ├── models.py            # Database models
│   ├── views.py             # API endpoints & views
│   └── urls.py              # URL routing
├── mainsite/                # Django project settings
├── agent/                   # AI Agent code
│   ├── agent.py             # Main agent logic
│   ├── api_client.py        # Claude API client
│   └── webhook_server.py    # Webhook handler
└── manage.py
```

## Features

- **AI Teacher**: Chat with an AI teacher that follows Finnish curriculum (LOPS 2021)
- **Exam Generator**: Create custom exams based on subject and difficulty
- **Rich Text Editor**: Abitti-compatible editor with math formula support (MathQuill/MathJax)
- **Automated Grading**: AI-powered grading with feedback and correct answers
- **Tutor**: Personalized help based on exam performance
- **Calendar**: Schedule management with iCal sync

## Setup

### Website (Django)

```bash
# Install dependencies
pip install django requests

# Run migrations
python manage.py migrate

# Start server
python manage.py runserver
```

### Agent

```bash
cd agent
pip install anthropic redis

# Set environment variables
export ANTHROPIC_API_KEY=your_key
export REDIS_URL=redis://localhost:6379

# Run agent
python agent.py
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/send-message/` | POST | Send message to AI Teacher |
| `/api/request-exam/` | POST | Request exam generation |
| `/api/grading-webhook/` | POST | Receive grades from grader |
| `/api/exam-webhook/<id>/` | POST | Receive generated exam |

## Webhooks

The system uses webhooks for async communication:

1. **Exam Creation**: Website → n8n → Exam Creator → Website
2. **Grading**: Website → n8n → Grader → Website
3. **Chat**: Website → n8n → Teacher/Tutor → Website

## License

MIT
