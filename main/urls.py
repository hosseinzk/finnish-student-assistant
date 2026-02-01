from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name="home"),
    path('api/webhook/', views.webhook, name="webhook"),
    path('api/save-answer/', views.save_answer, name="save_answer"),
    path('create-exam', views.createExam, name="create_exam"),
    path('exam-history/', views.exam_history, name="exam_history"),
    path('exam-review/<int:submission_id>/', views.exam_review, name="exam_review"),
    path('exam/<int:exam_id>/', views.exam, name="exam"),
    path('exam/<int:exam_id>/start/', views.start_exam, name="start_exam"),
    path('exam/<int:exam_id>/end/', views.end_exam, name="end_exam"),
    path('teacher/', views.ai_teacher, name="teacher"),
    path('tutor/', views.tutor, name="tutor"),
    path('calendar/', views.calendar_view, name="calendar"),
    path('api/create-chat/', views.create_chat, name="create_chat"),
    path('api/rename-chat/<str:session_id>/', views.rename_chat, name="rename_chat"),
    path('api/delete-chat/<str:session_id>/', views.delete_chat, name="delete_chat"),
    path('api/send-message/', views.send_message, name="send_message"),
    path('api/ai-webhook/<str:session_id>/', views.ai_webhook, name="ai_webhook"),
    path('api/get-messages/<str:session_id>/', views.get_messages, name="get_messages"),
    path('api/get-all-chats/', views.get_all_chats, name="get_all_chats"),
    path('api/request-exam/', views.request_exam, name="request_exam"),
    path('api/exam-webhook/<str:request_id>/', views.exam_webhook, name="exam_webhook"),
    path('api/exam-request-status/<str:request_id>/', views.get_exam_request_status, name="exam_request_status"),
    path('api/cancel-exam-request/', views.cancel_exam_request, name="cancel_exam_request"),
    path('api/grading-webhook/', views.grading_webhook, name="grading_webhook"),

    # Tutor API endpoints (separate database)
    path('api/tutor/create-chat/', views.tutor_create_chat, name="tutor_create_chat"),
    path('api/tutor/rename-chat/<str:session_id>/', views.tutor_rename_chat, name="tutor_rename_chat"),
    path('api/tutor/delete-chat/<str:session_id>/', views.tutor_delete_chat, name="tutor_delete_chat"),
    path('api/tutor/send-message/', views.tutor_send_message, name="tutor_send_message"),
    path('api/tutor/get-messages/<str:session_id>/', views.tutor_get_messages, name="tutor_get_messages"),
    path('api/tutor/get-all-chats/', views.tutor_get_all_chats, name="tutor_get_all_chats"),

    # Calendar API endpoints
    path('api/calendar/events/', views.calendar_get_events, name="calendar_get_events"),
    path('api/calendar/events/create/', views.calendar_create_event, name="calendar_create_event"),
    path('api/calendar/events/<int:event_id>/', views.calendar_update_event, name="calendar_update_event"),
    path('api/calendar/events/<int:event_id>/delete/', views.calendar_delete_event, name="calendar_delete_event"),
    path('api/calendar/sources/', views.calendar_get_sources, name="calendar_get_sources"),
    path('api/calendar/sources/add/', views.calendar_add_source, name="calendar_add_source"),
    path('api/calendar/sources/<int:source_id>/', views.calendar_update_source, name="calendar_update_source"),
    path('api/calendar/sources/<int:source_id>/delete/', views.calendar_delete_source, name="calendar_delete_source"),
    path('api/calendar/sources/<int:source_id>/sync/', views.calendar_sync_source, name="calendar_sync_source"),
]
