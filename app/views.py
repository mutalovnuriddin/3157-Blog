import mimetypes
import uuid

from asgiref.sync import async_to_sync
from django.db import transaction
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from channels.layers import get_channel_layer
from django.http import FileResponse, JsonResponse
from django.db.models import Count, Prefetch, Q
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.utils import timezone
from .forms import ProfileuserCreateForm, ProfileLoginForm, UserUpdateForm, PostCreateForm, CommentForm
from django.contrib.auth.forms import PasswordChangeForm
from allauth.socialaccount.models import SocialAccount
from .chat_payloads import direct_message_payload, shared_post_payload
from .models import Post, Profile, Comment, Conversation, DirectMessage, Notification



def _avatar_urls(user, google_account=None):
    avatar = user.avatar
    default_avatar = user._meta.get_field('avatar').get_default()
    local_avatar_url = (
        avatar.url
        if avatar and avatar.name != default_avatar
        else None
    )
    google_avatar_url = (
        google_account.extra_data.get('picture')
        if google_account
        else None
    )
    if not google_avatar_url and avatar:
        google_avatar_url = avatar.url
    return local_avatar_url, google_avatar_url


def _avatar_url_for_user(user):
    google_account = user.socialaccount_set.filter(provider='google').first()
    local_avatar_url, google_avatar_url = _avatar_urls(user, google_account)
    return local_avatar_url or google_avatar_url


def _profile_connections(user):
    followers = list(
        Profile.objects.filter(following=user).order_by('username')
    )
    following = list(user.following.order_by('username'))
    connected_users = followers + following
    google_accounts = {
        account.user_id: account
        for account in SocialAccount.objects.filter(
            user_id__in={connected_user.pk for connected_user in connected_users},
            provider='google',
        )
    }
    for connected_user in connected_users:
        local_avatar_url, google_avatar_url = _avatar_urls(
            connected_user,
            google_accounts.get(connected_user.pk),
        )
        connected_user.display_avatar = local_avatar_url or google_avatar_url
        connected_user.profile_url = reverse(
            'public_profile',
            args=[connected_user.pk],
        )
    return followers, following


def _conversation_for_users(first_user, second_user):
    participant_a, participant_b = sorted(
        (first_user, second_user),
        key=lambda user: str(user.pk),
    )
    conversation, _ = Conversation.objects.get_or_create(
        participant_a=participant_a,
        participant_b=participant_b,
    )
    return conversation


def _chat_sidebar(user, active_conversation=None):
    conversations = list(
        Conversation.objects.filter(
            Q(participant_a=user) | Q(participant_b=user)
        )
        .select_related('participant_a', 'participant_b')
        .annotate(
            unread_count=Count(
                'messages',
                filter=Q(messages__is_read=False)
                & ~Q(messages__sender_id=user.pk),
            )
        )
        .prefetch_related(Prefetch(
            'messages',
            queryset=DirectMessage.objects.order_by('-created_at')[:1],
            to_attr='latest_messages',
        ))
        .order_by('-updated_at')
    )
    peers = [
        conversation.participant_for(user)
        for conversation in conversations
    ]
    peer_ids = {peer.pk for peer in peers}
    google_accounts = {
        account.user_id: account
        for account in SocialAccount.objects.filter(
            user_id__in=peer_ids,
            provider='google',
        )
    }
    items = []
    for conversation, peer in zip(conversations, peers):
        local_avatar_url, google_avatar_url = _avatar_urls(
            peer,
            google_accounts.get(peer.pk),
        )
        latest_message = (
            conversation.latest_messages[0]
            if conversation.latest_messages
            else None
        )
        items.append({
            'conversation': conversation,
            'peer': peer,
            'peer_avatar_url': local_avatar_url or google_avatar_url,
            'conversation_url': reverse(
                'chat_conversation',
                args=[conversation.pk],
            ),
            'is_active': (
                active_conversation is not None
                and conversation.pk == active_conversation.pk
            ),
            'is_online': cache.get(f"chat:presence:{peer.pk}", 0) > 0,
            'last_message': latest_message,
            'unread_count': conversation.unread_count,
        })
    return items


def _post_share_recipients(user):
    recipients = list(
        user.following.filter(is_active=True).order_by('username')[:50]
    )
    google_accounts = {
        account.user_id: account
        for account in SocialAccount.objects.filter(
            user_id__in=[recipient.pk for recipient in recipients],
            provider='google',
        )
    }
    for recipient in recipients:
        local_avatar_url, google_avatar_url = _avatar_urls(
            recipient,
            google_accounts.get(recipient.pk),
        )
        recipient.share_avatar_url = local_avatar_url or google_avatar_url
    return recipients


def _posts_for_user(queryset, user):
    posts = list(
        queryset.annotate(likes_count=Count('likes')).prefetch_related(
            Prefetch('comments', queryset=Comment.objects.select_related('author'))
        )
    )
    liked_post_ids = set(
        Post.objects.filter(
            pk__in=[post.pk for post in posts],
            likes=user,
        ).values_list('pk', flat=True)
    )
    comment_author_ids = {
        comment.author_id
        for post in posts
        for comment in post.comments.all()
    }
    google_accounts = {
        account.user_id: account
        for account in SocialAccount.objects.filter(
            user_id__in=comment_author_ids,
            provider='google',
        )
    }
    for post in posts:
        post.is_liked = post.pk in liked_post_ids
        for comment in post.comments.all():
            local_avatar_url, google_avatar_url = _avatar_urls(
                comment.author,
                google_accounts.get(comment.author_id),
            )
            comment.author_avatar_url = local_avatar_url or google_avatar_url
    return posts


def _redirect_after_action(request):
    next_url = request.POST.get('next', '')
    if url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(reverse('home'))


def _is_ajax_request(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


# Create your views here.
@login_required(redirect_field_name=None)
def home_page(request):
    posts = _posts_for_user(
        Post.objects.select_related('author'),
        request.user,
    )
    author_ids = {post.author_id for post in posts}
    google_accounts = {
        account.user_id: account
        for account in SocialAccount.objects.filter(
            user_id__in=author_ids,
            provider='google',
        )
    }
    for post in posts:
        _, post.author_avatar_url = _avatar_urls(
            post.author,
            google_accounts.get(post.author_id),
        )
    return render(request, 'home.html', {
        'posts': posts,
        'comment_form': CommentForm(),
        'comment_form_avatar_url': _avatar_url_for_user(request.user),
        'share_recipients': _post_share_recipients(request.user),
    })



def register_page(request):
    if request.user.is_authenticated:
        return redirect('profile')
    if request.method == 'POST':
        form = ProfileuserCreateForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            # backend parametrini qo'shing:
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('profile')
    else:
        form = ProfileuserCreateForm()
    return render(request, 'register.html', {'form': form})

def login_page(request):
    if request.user.is_authenticated:
        return redirect('profile')
    if request.method == 'POST':
        form = ProfileLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('profile')
    else:
        form = ProfileLoginForm()
    return render(request, 'login.html', {'form': form})


@require_POST
def logout_page(request):
    logout(request)
    return redirect('login')



@login_required
def post_create_page(request):
    """Alohida sahifada yangi post ulashish."""
    if request.method == 'POST':
        post_form = PostCreateForm(request.POST, request.FILES)
        if post_form.is_valid():
            post = post_form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(
                request,
                'Post ulashildi — profilingizda ko‘rinadi.',
            )
            return redirect('profile')
    else:
        post_form = PostCreateForm()
    return render(request, 'create_post.html', {'post_form': post_form})


@login_required
def profile_page(request):
    google_account = request.user.socialaccount_set.filter(provider='google').first()
    local_avatar_url, google_avatar_url = _avatar_urls(request.user, google_account)
    followers, following = _profile_connections(request.user)

    return render(request, 'index.html', {
        'profile_user': request.user,
        'is_profile_owner': True,
        'local_avatar_url': local_avatar_url,
        'google_avatar_url': google_avatar_url,
        'comment_form': CommentForm(),
        'comment_form_avatar_url': local_avatar_url or google_avatar_url,
        'share_recipients': _post_share_recipients(request.user),
        'user_posts': _posts_for_user(
            Post.objects.filter(author=request.user),
            request.user,
        ),
        'followers': followers,
        'following_users': following,
        'followers_count': len(followers),
        'following_count': len(following),
    })


@login_required
def public_profile_page(request, user_id):
    profile_user = get_object_or_404(Profile, pk=user_id)
    if profile_user.pk == request.user.pk:
        return redirect('profile')
    google_account = profile_user.socialaccount_set.filter(provider='google').first()
    local_avatar_url, google_avatar_url = _avatar_urls(profile_user, google_account)
    followers, following = _profile_connections(profile_user)
    return render(request, 'index.html', {
        'profile_user': profile_user,
        'is_profile_owner': False,
        'local_avatar_url': local_avatar_url,
        'google_avatar_url': google_avatar_url,
        'user_posts': _posts_for_user(
            Post.objects.filter(author=profile_user),
            request.user,
        ),
        'followers': followers,
        'following_users': following,
        'followers_count': len(followers),
        'following_count': len(following),
        'is_following': request.user.following.filter(pk=profile_user.pk).exists(),
        'comment_form': CommentForm(),
        'comment_form_avatar_url': _avatar_url_for_user(request.user),
        'share_recipients': _post_share_recipients(request.user),
    })


@login_required
def start_chat_page(request, user_id):
    target_user = get_object_or_404(Profile, pk=user_id)
    if target_user.pk == request.user.pk:
        return redirect('chat_inbox')
    conversation = _conversation_for_users(request.user, target_user)
    return redirect('chat_conversation', conversation_id=conversation.pk)


@login_required
def chat_inbox_page(request):
    return render(request, 'chat.html', {
        'chat_items': _chat_sidebar(request.user),
        'active_conversation': None,
        'peer': None,
        'peer_avatar_url': None,
        'messages': [],
        'is_peer_online': False,
        'chat_socket_path': '',
    })


@login_required
def chat_conversation_page(request, conversation_id):
    conversation = get_object_or_404(
        Conversation.objects.select_related('participant_a', 'participant_b'),
        pk=conversation_id,
    )
    peer = conversation.participant_for(request.user)
    if peer is None:
        return redirect('chat_inbox')

    conversation.messages.filter(
        is_read=False,
    ).exclude(sender=request.user).update(is_read=True)
    peer_avatar_url = _avatar_url_for_user(peer)
    chat_messages = list(
        conversation.messages.select_related('sender', 'shared_post__author')
        .order_by('-created_at')[:100]
    )
    chat_messages.reverse()
    for message in chat_messages:
        if message.audio or message.attachment:
            message.media_url = reverse(
                'chat_audio_file',
                args=[conversation.pk, message.pk],
            )
        if message.attachment:
            message.media_type = (
                mimetypes.guess_type(message.attachment.name)[0] or ''
            )
        if message.shared_post_id:
            message.shared_post_data = shared_post_payload(message.shared_post)
    return render(request, 'chat.html', {
        'chat_items': _chat_sidebar(request.user, conversation),
        'active_conversation': conversation,
        'peer': peer,
        'peer_avatar_url': peer_avatar_url,
        'messages': chat_messages,
        'is_peer_online': cache.get(f"chat:presence:{peer.pk}", 0) > 0,
        'chat_socket_path': f'/ws/chat/{conversation.pk}/',
    })


@login_required
@require_POST
def chat_audio_upload_page(request, conversation_id):
    conversation = get_object_or_404(Conversation, pk=conversation_id)
    if conversation.participant_for(request.user) is None:
        return JsonResponse({'error': 'Suhbatga kirish huquqi yo‘q.'}, status=403)

    uploaded_file = request.FILES.get('audio') or request.FILES.get('media')
    if uploaded_file is None:
        return JsonResponse({'error': 'Fayl topilmadi.'}, status=400)
    if uploaded_file.size == 0 or uploaded_file.size > 20 * 1024 * 1024:
        return JsonResponse({
            'error': 'Fayl bo‘sh yoki hajmi 20 MB dan katta.',
        }, status=400)

    extensions = {
        'audio/webm': 'webm',
        'audio/ogg': 'ogg',
        'audio/mp4': 'm4a',
        'audio/mpeg': 'mp3',
        'audio/wav': 'wav',
        'audio/x-wav': 'wav',
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'image/gif': 'gif',
        'image/webp': 'webp',
        'video/mp4': 'mp4',
        'video/webm': 'webm',
        'video/quicktime': 'mov',
        'video/ogg': 'ogv',
    }
    content_type = (
        (uploaded_file.content_type or '')
        .split(';', 1)[0]
        .strip()
        .lower()
    )
    extension = extensions.get(content_type)
    if extension is None:
        return JsonResponse({
            'error': 'Bu rasm yoki video formati qo‘llab-quvvatlanmaydi.',
        }, status=400)

    message = DirectMessage(
        conversation=conversation,
        sender=request.user,
        text='',
    )
    is_audio = content_type.startswith('audio/')
    if is_audio:
        message.audio.save(
            f'{uuid.uuid4().hex}.{extension}',
            uploaded_file,
            save=False,
        )
    else:
        message.attachment.save(
            f'{uuid.uuid4().hex}.{extension}',
            uploaded_file,
            save=False,
        )
    message.save()
    Conversation.objects.filter(pk=conversation.pk).update(
        updated_at=timezone.now(),
    )

    payload = {
        'id': str(message.pk),
        'text': '',
        'is_audio': is_audio,
        'audio_url': reverse(
            'chat_audio_file',
            args=[conversation.pk, message.pk],
        ) if is_audio else None,
        'media_type': (
            content_type if content_type.startswith('image/')
            else content_type if content_type.startswith('video/')
            else None
        ),
        'media_url': reverse(
            'chat_audio_file',
            args=[conversation.pk, message.pk],
        ) if not is_audio else None,
        'sender_id': str(request.user.pk),
        'sender_username': request.user.username,
        'created_at': timezone.localtime(message.created_at).strftime('%H:%M'),
        'created_at_iso': message.created_at.isoformat(),
    }
    channel_layer = get_channel_layer()
    conversation_group = f'chat_{conversation.pk.hex}'
    async_to_sync(channel_layer.group_send)(
        conversation_group,
        {
            'type': 'chat_message',
            'message': payload,
        },
    )
    inbox_event = {
        'type': 'inbox_message',
        'conversation_id': str(conversation.pk),
        'message': payload,
        'peer_username': request.user.username,
    }
    peer = conversation.participant_for(request.user)
    async_to_sync(channel_layer.group_send)(f'inbox_{peer.pk}', inbox_event)
    async_to_sync(channel_layer.group_send)(f'inbox_{request.user.pk}', inbox_event)
    return JsonResponse({'message': payload}, status=201)


@login_required
def chat_audio_file_page(request, conversation_id, message_id):
    message = get_object_or_404(
        DirectMessage.objects.select_related('conversation'),
        pk=message_id,
        conversation_id=conversation_id,
    )
    if message.conversation.participant_for(request.user) is None:
        return JsonResponse({'error': 'Audio topilmadi.'}, status=404)

    file_field = message.audio or message.attachment
    if not file_field:
        return JsonResponse({'error': 'Fayl topilmadi.'}, status=404)

    audio_file = file_field.open('rb')
    content_type = mimetypes.guess_type(file_field.name)[0] or 'application/octet-stream'
    return FileResponse(audio_file, content_type=content_type)


@login_required
def share_user_search_page(request):
    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'users': []})

    users = list(
        Profile.objects.filter(
            username__icontains=query,
            is_active=True,
        )
        .exclude(pk=request.user.pk)
        .order_by('username')[:20]
    )
    google_accounts = {
        account.user_id: account
        for account in SocialAccount.objects.filter(
            user_id__in=[user.pk for user in users],
            provider='google',
        )
    }
    results = []
    for user in users:
        local_avatar_url, google_avatar_url = _avatar_urls(
            user,
            google_accounts.get(user.pk),
        )
        results.append({
            'id': str(user.pk),
            'username': user.username,
            'avatar_url': local_avatar_url or google_avatar_url,
        })
    return JsonResponse({'users': results})


@login_required
@require_POST
def share_post_page(request):
    post = get_object_or_404(Post.objects.select_related('author'), pk=request.POST.get('post_id'))
    recipient_ids = request.POST.getlist('recipient_ids')
    if not recipient_ids or len(recipient_ids) > 20:
        return JsonResponse({
            'error': 'Bitta yoki undan ko‘p (20 tagacha) foydalanuvchini tanlang.',
        }, status=400)

    try:
        recipient_ids = list(dict.fromkeys(
            uuid.UUID(recipient_id) for recipient_id in recipient_ids
        ))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Foydalanuvchi tanlovi noto‘g‘ri.'}, status=400)

    if request.user.pk in recipient_ids:
        return JsonResponse({'error': 'Postni o‘zingizga yubora olmaysiz.'}, status=400)

    recipients = list(
        Profile.objects.filter(pk__in=recipient_ids, is_active=True)
    )
    if len(recipients) != len(recipient_ids):
        return JsonResponse({
            'error': 'Tanlangan foydalanuvchilardan biri topilmadi.',
        }, status=400)

    deliveries = []
    with transaction.atomic():
        for recipient in recipients:
            conversation = _conversation_for_users(request.user, recipient)
            message = DirectMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                shared_post=post,
            )
            Conversation.objects.filter(pk=conversation.pk).update(
                updated_at=timezone.now(),
            )
            deliveries.append((recipient, conversation, message))

    channel_layer = get_channel_layer()
    sender_avatar_url = _avatar_url_for_user(request.user)
    for recipient, conversation, message in deliveries:
        payload = direct_message_payload(message)
        payload['sender_username'] = request.user.username
        recipient_avatar_url = _avatar_url_for_user(recipient)
        message_event = {
            'type': 'chat_message',
            'message': payload,
        }
        async_to_sync(channel_layer.group_send)(
            f'chat_{conversation.pk.hex}',
            message_event,
        )
        async_to_sync(channel_layer.group_send)(
            f'inbox_{recipient.pk}',
            {
                'type': 'inbox_message',
                'conversation_id': str(conversation.pk),
                'message': payload,
                'peer_username': request.user.username,
                'peer_id': str(request.user.pk),
                'peer_avatar_url': sender_avatar_url,
                'conversation_url': reverse(
                    'chat_conversation',
                    args=[conversation.pk],
                ),
            },
        )
        async_to_sync(channel_layer.group_send)(
            f'inbox_{request.user.pk}',
            {
                'type': 'inbox_message',
                'conversation_id': str(conversation.pk),
                'message': payload,
                'peer_username': recipient.username,
                'peer_id': str(recipient.pk),
                'peer_avatar_url': recipient_avatar_url,
                'conversation_url': reverse(
                    'chat_conversation',
                    args=[conversation.pk],
                ),
            },
        )

    return JsonResponse({
        'sent_count': len(deliveries),
        'post': shared_post_payload(post),
    }, status=201)



@login_required
def profile_edit_view(request):
    profile_form = UserUpdateForm(instance=request.user)
    password_form = PasswordChangeForm(request.user)

    if request.method == 'POST':

        # Profil formasi yuborilgan
        if 'submit_profile' in request.POST:
            profile_form = UserUpdateForm(
                request.POST,
                request.FILES,
                instance=request.user
            )

            if profile_form.is_valid():
                profile_form.save()
                return redirect('profile')

        # Parol formasi yuborilgan
        elif 'submit_password' in request.POST:
            password_form = PasswordChangeForm(
                request.user,
                request.POST
            )

            if password_form.is_valid():
                user = password_form.save()

                update_session_auth_hash(
                    request,
                    user
                )

                return redirect('profile')

    avatar = request.user.avatar
    default_avatar = request.user._meta.get_field('avatar').get_default()
    if avatar and avatar.name != default_avatar:
        edit_avatar_url = avatar.url
    else:
        google_account = request.user.socialaccount_set.filter(provider='google').first()
        edit_avatar_url = (
            google_account.extra_data.get('picture')
            if google_account
            else None
        )
        if not edit_avatar_url and avatar:
            edit_avatar_url = avatar.url

    context = {
        'profile_form': profile_form,
        'password_form': password_form,
        'edit_avatar_url': edit_avatar_url,
    }

    return render(request, 'profile_edit.html', context)


@login_required
@require_POST
def like_post_page(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    if post.likes.filter(pk=request.user.pk).exists():
        post.likes.remove(request.user)
        is_liked = False
        Notification.objects.filter(recipient=post.author, sender=request.user, notification_type=Notification.LIKE, post=post).delete()
    else:
        post.likes.add(request.user)
        is_liked = True
        if post.author != request.user:
            Notification.objects.create(
                recipient=post.author,
                sender=request.user,
                notification_type=Notification.LIKE,
                post=post
            )

    if _is_ajax_request(request):
        return JsonResponse({
            'liked': is_liked,
            'likes_count': post.likes.count(),
        })
    return _redirect_after_action(request)


@login_required
@require_POST
def add_comment_page(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.post = post
        comment.author = request.user
        comment.save()

        # O'z postiga yozmasa, xabarnoma jo'natiladi
        if post.author != request.user:
            Notification.objects.create(
                recipient=post.author,
                sender=request.user,
                notification_type=Notification.COMMENT,
                post=post,
                comment=comment
            )

        if _is_ajax_request(request):
            avatar_url = _avatar_url_for_user(request.user)
            return JsonResponse({
                'comment': {
                    'id': str(comment.pk),
                    'text': comment.text,
                    'username': request.user.username,
                    'profile_url': reverse('public_profile', args=[request.user.pk]),
                    'avatar_url': avatar_url,
                    'initial': request.user.username[:1].upper(),
                    'created_at': timezone.localtime(comment.created_at).strftime(
                        '%d.%m.%Y · %H:%M'
                    ),
                    'created_at_iso': comment.created_at.isoformat(),
                },
                'comments_count': post.comments.count(),
            })
    else:
        if _is_ajax_request(request):
            return JsonResponse({
                'errors': form.errors.get_json_data(),
            }, status=400)
        messages.error(request, 'Izohni yuborishdan oldin matn kiriting.')
    return _redirect_after_action(request)

@login_required
@require_POST
def follow_toggle_page(request, user_id):
    target_user = get_object_or_404(Profile, pk=user_id)
    
    if target_user != request.user:
        if request.user.following.filter(id=target_user.id).exists():
            request.user.following.remove(target_user)
            is_following = False
            Notification.objects.filter(
                recipient=target_user,
                sender=request.user,
                notification_type=Notification.FOLLOW
            ).delete()
        else:
            request.user.following.add(target_user)
            is_following = True
            Notification.objects.create(
                recipient=target_user,
                sender=request.user,
                notification_type=Notification.FOLLOW
            )
    else:
        is_following = False

    if _is_ajax_request(request):
        return JsonResponse({
            'following': is_following,
            'followers_count': Profile.objects.filter(following=target_user).count(),
        })

    return _redirect_after_action(request)


@login_required
def search_users_page(request):
    query = request.GET.get('q', '').strip()
    users = []

    if query:
        search_filter = Q()
        for term in query.split():
            search_filter &= (
                Q(username__icontains=term) |
                Q(first_name__icontains=term) |
                Q(last_name__icontains=term)
            )
        users = Profile.objects.filter(search_filter).exclude(
            pk=request.user.pk
        )[:20]

        for user in users:
            user.display_avatar = _avatar_url_for_user(user)
            user.is_following = request.user.following.filter(pk=user.pk).exists()

        if _is_ajax_request(request):
            results = [
                {
                    'id': user.pk,
                    'username': user.username,
                    'full_name': user.get_full_name(),
                    'avatar_url': user.display_avatar,
                    'profile_url': reverse('public_profile', args=[user.pk]),
                    'is_following': user.is_following,
                }
                for user in users
            ]
            return JsonResponse({'results': results})
    return render(request, 'search_results.html', {
        'query': query,
        'users': users,
    })




@login_required
def notifications_page(request):
    notifications = list(
        Notification.objects.filter(
            recipient=request.user
        ).select_related('sender', 'post', 'comment')
    )

    sender_ids = {n.sender_id for n in notifications}

    # To'g'rilangan qator: user_id__in va provider='google'
    google_accounts = {
        account.user_id: account
        for account in SocialAccount.objects.filter(
            user_id__in=sender_ids,
            provider='google',
        )
    }

    for item in notifications:
        local_avatar, google_avatar = _avatar_urls(
            item.sender, 
            google_accounts.get(item.sender_id)
        )
        item.sender_avatar_url = local_avatar or google_avatar

    return render(request, 'notifications.html', {
        'notifications': notifications,
    })


@login_required
@require_POST
def make_all_notifications_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    if _is_ajax_request(request):
        return JsonResponse({'status': 'ok'})
    return redirect('notifications')
