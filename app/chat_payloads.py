import mimetypes

from django.urls import reverse
from django.utils import timezone


def shared_post_payload(post):
    comments = list(
        post.comments.select_related('author').order_by('-created_at')[:4]
    )
    return {
        'id': str(post.pk),
        'author_id': str(post.author_id),
        'author_username': post.author.username,
        'author_url': reverse('public_profile', args=[post.author_id]),
        'post_url': f"{reverse('home')}#post-{post.pk}",
        'created_at': timezone.localtime(post.created_at).strftime(
            '%d.%m.%Y · %H:%M'
        ),
        'title': post.title or '',
        'description': post.desc,
        'image_url': post.img.url if post.img else None,
        'video_url': post.video.url if post.video else None,
        'likes_count': post.likes.count(),
        'comments_count': post.comments.count(),
        'comments': [
            {
                'username': comment.author.username,
                'author_url': reverse(
                    'public_profile',
                    args=[comment.author_id],
                ),
                'text': comment.text,
            }
            for comment in comments
        ],
    }


def direct_message_payload(message):
    is_audio = bool(message.audio)
    attachment_name = message.attachment.name
    attachment_type = (
        mimetypes.guess_type(attachment_name)[0]
        if attachment_name
        else None
    )
    file_url = (
        reverse(
            'chat_audio_file',
            args=[message.conversation_id, message.pk],
        )
        if is_audio or attachment_name
        else None
    )
    return {
        'id': str(message.pk),
        'text': message.text,
        'is_audio': is_audio,
        'audio_url': file_url if is_audio else None,
        'media_type': attachment_type,
        'media_url': file_url if attachment_name else None,
        'shared_post': (
            shared_post_payload(message.shared_post)
            if message.shared_post_id
            else None
        ),
        'sender_id': str(message.sender_id),
        'created_at': timezone.localtime(message.created_at).strftime(
            '%H:%M'
        ),
        'created_at_iso': message.created_at.isoformat(),
    }
