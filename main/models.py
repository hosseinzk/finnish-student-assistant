from django.db import models
from django.utils import timezone
import uuid

class Exam(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    time_limit = models.IntegerField(blank=True, null=True, help_text="Time limit in seconds")
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(blank=True, null=True, help_text="When the exam was started")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Question(models.Model):
    QUESTION_TYPES = [
        ('text', 'Text Question'),
        ('multiple_choice', 'Multiple Choice'),
    ]

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='questions')
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    question_text = models.TextField()
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Q{self.order}: {self.question_text[:50]}"


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    choice_text = models.CharField(max_length=500)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.choice_text


class Answer(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    answer_text = models.TextField(blank=True, null=True, help_text="For text questions")
    selected_choices = models.JSONField(blank=True, null=True, help_text="List of choice IDs for multiple choice")
    timestamp = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['exam', 'question']

    def __str__(self):
        return f"Answer for {self.question} in {self.exam}"


class ExamSubmission(models.Model):
    exam_name = models.CharField(max_length=255)
    exam_description = models.TextField(blank=True, null=True)
    submitted_at = models.DateTimeField(default=timezone.now)
    time_taken = models.IntegerField(blank=True, null=True, help_text="Time taken in seconds")
    submission_data = models.JSONField(help_text="Complete exam with questions and answers")
    is_graded = models.BooleanField(default=False)
    graded_at = models.DateTimeField(blank=True, null=True)
    total_points_earned = models.FloatField(blank=True, null=True)
    total_points_possible = models.FloatField(blank=True, null=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.exam_name} - {self.submitted_at.strftime('%Y-%m-%d %H:%M')}"

    @property
    def grade_percentage(self):
        if self.total_points_earned is not None and self.total_points_possible:
            return round((self.total_points_earned / self.total_points_possible) * 100, 1)
        return None


class QuestionGrade(models.Model):
    """Stores individual question grades from the grading webhook."""
    submission = models.ForeignKey(ExamSubmission, on_delete=models.CASCADE, related_name='grades')
    question_id = models.IntegerField(help_text="Question ID/order from the grading system")
    order = models.IntegerField(default=0)
    points_earned = models.FloatField(default=0)
    points_possible = models.FloatField(default=0)
    feedback = models.TextField(blank=True, null=True)
    correct_answer = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, default='success')
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order']
        unique_together = ['submission', 'order']

    def __str__(self):
        return f"Grade for Q{self.order} in {self.submission}"

    @property
    def is_correct(self):
        return self.points_earned == self.points_possible

    @property
    def percentage(self):
        if self.points_possible > 0:
            return round((self.points_earned / self.points_possible) * 100, 1)
        return 0


class ChatSession(models.Model):
    session_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    model_type = models.CharField(max_length=50, default='teacher')
    title = models.CharField(max_length=255, default='New Chat')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.model_type}"


class ChatMessage(models.Model):
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    sender = models.CharField(max_length=10)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.sender}: {self.content[:20]}"


class ExamRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('error', 'Error'),
    ]

    request_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    subject = models.TextField()
    num_questions = models.IntegerField(default=5)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    exam = models.ForeignKey(Exam, on_delete=models.SET_NULL, blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"ExamRequest {self.request_id} - {self.status}"


# ============================================
# TUTOR MODELS - Separate database (tutor_db)
# ============================================

class TutorChatSession(models.Model):
    """Chat sessions for the tutor - stored in separate tutor database."""
    session_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    title = models.CharField(max_length=255, default='New Chat')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Tutor: {self.title}"


class TutorChatMessage(models.Model):
    """Chat messages for the tutor - stored in separate tutor database."""
    session = models.ForeignKey(TutorChatSession, on_delete=models.CASCADE, related_name='messages')
    sender = models.CharField(max_length=10)  # 'user' or 'ai'
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Tutor {self.sender}: {self.content[:20]}"


# ============================================
# CALENDAR MODELS
# ============================================

class CalendarSource(models.Model):
    """External calendar sources (ICS URLs)."""
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=1000)
    color = models.CharField(max_length=7, default='#5a9ba8')  # Hex color
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_synced = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class CalendarEvent(models.Model):
    """Calendar events - both from external sources and manually created."""
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, null=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    all_day = models.BooleanField(default=False)
    location = models.CharField(max_length=500, blank=True, null=True)
    color = models.CharField(max_length=7, default='#5a9ba8')

    # Source tracking
    source = models.ForeignKey(CalendarSource, on_delete=models.CASCADE, blank=True, null=True, related_name='events')
    external_uid = models.CharField(max_length=500, blank=True, null=True)  # UID from ICS file
    is_manual = models.BooleanField(default=True)  # True if created manually

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"{self.title} - {self.start_time.strftime('%Y-%m-%d %H:%M')}"
