from django.contrib import admin
from .models import Exam, Question, Choice, Answer, ExamSubmission


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 2


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'time_limit', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'description')
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('question_text', 'exam', 'question_type', 'order')
    list_filter = ('question_type', 'exam')
    search_fields = ('question_text',)
    inlines = [ChoiceInline]


@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    list_display = ('choice_text', 'question', 'order')
    list_filter = ('question__exam',)


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ('exam', 'question', 'timestamp')
    list_filter = ('exam', 'timestamp')
    readonly_fields = ('timestamp',)


@admin.register(ExamSubmission)
class ExamSubmissionAdmin(admin.ModelAdmin):
    list_display = ('exam_name', 'submitted_at', 'time_taken')
    list_filter = ('submitted_at',)
    search_fields = ('exam_name', 'exam_description')
    readonly_fields = ('submitted_at', 'submission_data')

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ('exam_name', 'exam_description', 'time_taken')
        return self.readonly_fields
