import tempfile
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from allauth.socialaccount.models import SocialAccount
from PIL import Image

from app.models import Conversation, DirectMessage, Notification
from app.routing import websocket_urlpatterns


class ProfileFlowTests(TestCase):
	def setUp(self):
		self.media_dir = tempfile.TemporaryDirectory()
		self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
		self.settings_override.enable()
		self.addCleanup(self.settings_override.disable)
		self.addCleanup(self.media_dir.cleanup)

	def test_root_redirects_anonymous_user_to_login(self):
		response = self.client.get('/')

		self.assertRedirects(response, reverse('login'))

	def test_profile_redirects_anonymous_user_to_login(self):
		response = self.client.get(reverse('profile'))

		self.assertRedirects(response, f"{reverse('login')}?next={reverse('profile')}")

	def test_authenticated_user_cannot_open_auth_pages(self):
		user = get_user_model().objects.create_user(username='tester', password='Kz!v2pL8#rQ4')
		self.client.force_login(user)

		for route_name in ('login', 'register'):
			with self.subTest(route=route_name):
				response = self.client.get(reverse(route_name))
				self.assertRedirects(response, reverse('profile'))

	def test_registration_saves_uploaded_avatar(self):
		image_file = BytesIO()
		Image.new('RGB', (1, 1), color='green').save(image_file, format='PNG')
		avatar = SimpleUploadedFile(
			'avatar.png',
			image_file.getvalue(),
			content_type='image/png',
		)
		response = self.client.post(reverse('register'), {
			'username': 'newuser',
			'email': 'newuser@example.com',
			'phone_number': '+998901234567',
			'bio': 'Salom',
			'password1': 'Kz!v2pL8#rQ4',
			'password2': 'Kz!v2pL8#rQ4',
			'avatar': avatar,
		})

		self.assertRedirects(response, reverse('profile'))
		user = get_user_model().objects.get(username='newuser')
		self.assertEqual(user.avatar.name, 'avatars/avatar.png')
		self.assertTrue(Path(self.media_dir.name, user.avatar.name).is_file())

	def test_profile_uses_google_avatar_when_user_has_default_avatar(self):
		user = get_user_model().objects.create_user(username='googleuser', password='Kz!v2pL8#rQ4')
		SocialAccount.objects.create(
			user=user,
			provider='google',
			uid='google-user-id',
			extra_data={'picture': 'https://example.com/google-avatar.jpg'},
		)
		self.client.force_login(user)

		response = self.client.get(reverse('profile'))

		self.assertContains(response, 'src="https://example.com/google-avatar.jpg"')
		self.assertNotContains(response, 'src="/media/avatars/user.png"')

	def test_profile_keeps_default_avatar_when_google_picture_is_missing(self):
		user = get_user_model().objects.create_user(username='googleuser', password='Kz!v2pL8#rQ4')
		SocialAccount.objects.create(
			user=user,
			provider='google',
			uid='google-user-id',
			extra_data={},
		)
		self.client.force_login(user)

		response = self.client.get(reverse('profile'))

		self.assertContains(response, 'src="/media/avatars/user.png"')
	def test_profile_prefers_user_uploaded_avatar_to_google_avatar(self):
		user = get_user_model().objects.create_user(username='googleuser', password='Kz!v2pL8#rQ4')
		user.avatar.save(
			'custom-avatar.png',
			SimpleUploadedFile('custom-avatar.png', b'image data', content_type='image/png'),
		)
		SocialAccount.objects.create(
			user=user,
			provider='google',
			uid='google-user-id',
			extra_data={'picture': 'https://example.com/google-avatar.jpg'},
		)
		self.client.force_login(user)

		response = self.client.get(reverse('profile'))

		self.assertContains(response, 'src="/media/avatars/custom-avatar.png"')
		self.assertNotContains(response, 'https://example.com/google-avatar.jpg')

	def test_post_create_page_renders_and_saves_post(self):
		user = get_user_model().objects.create_user(username='poster', password='Kz!v2pL8#rQ4')
		self.client.force_login(user)

		page_response = self.client.get(reverse('post_create'))
		self.assertEqual(page_response.status_code, 200)
		self.assertContains(page_response, 'Postni ulashish')
		self.assertContains(page_response, '3157 Blog')

		create_response = self.client.post(reverse('post_create'), {
			'title': 'Birinchi taassurot',
			'desc': 'Bugun juda yaxshi kun bo‘ldi.',
		})

		self.assertRedirects(create_response, reverse('profile'))
		self.assertTrue(user.post_set.exists())
		self.assertEqual(user.post_set.first().author, user)

	def test_post_create_requires_login(self):
		response = self.client.get(reverse('post_create'))

		self.assertRedirects(
			response,
			f"{reverse('login')}?next={reverse('post_create')}",
		)

	def test_profile_can_create_post_and_home_displays_it(self):
		user = get_user_model().objects.create_user(username='poster', password='Kz!v2pL8#rQ4')
		self.client.force_login(user)

		create_response = self.client.post(reverse('post_create'), {
			'title': 'Birinchi taassurot',
			'desc': 'Bugun juda yaxshi kun bo‘ldi.',
		})

		self.assertRedirects(create_response, reverse('profile'))
		self.assertTrue(user.post_set.exists())
		self.assertEqual(user.post_set.first().author, user)

		home_response = self.client.get(reverse('home'))
		self.assertContains(home_response, 'Birinchi taassurot')
		self.assertContains(home_response, 'poster')
		self.assertNotContains(home_response, 'Postni ulashish')

	def test_home_uses_each_google_authors_avatar_and_links_to_profile(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		author = get_user_model().objects.create_user(username='googleposter', password='Kz!v2pL8#rQ4')
		SocialAccount.objects.create(
			user=author,
			provider='google',
			uid='google-poster-id',
			extra_data={'picture': 'https://example.com/poster-avatar.jpg'},
		)
		author.post_set.create(title='Google posti', desc='Muallif posti')
		self.client.force_login(viewer)

		response = self.client.get(reverse('home'))

		self.assertContains(response, 'src="https://example.com/poster-avatar.jpg"')
		self.assertContains(
			response,
			f'href="{reverse("public_profile", args=[author.pk])}">googleposter</a>',
		)

	def test_public_profile_shows_authors_posts_without_post_form(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		author = get_user_model().objects.create_user(
			username='poster',
			password='Kz!v2pL8#rQ4',
			bio='Post yozishni yaxshi ko‘raman',
		)
		author.post_set.create(title='Profil posti', desc='Muallif sahifasidagi post')
		self.client.force_login(viewer)

		response = self.client.get(reverse('public_profile', args=[author.pk]))

		self.assertContains(response, 'Profil posti')
		self.assertContains(response, 'Muallif sahifasidagi post')
		self.assertContains(response, 'Post yozishni yaxshi ko‘raman')
		self.assertNotContains(response, 'Postni ulashish')

	def test_like_post_can_be_added_and_removed(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		author = get_user_model().objects.create_user(username='author', password='Kz!v2pL8#rQ4')
		post = author.post_set.create(desc='Like testi')
		self.client.force_login(viewer)
		url = reverse('like_post', args=[post.pk])

		response = self.client.post(url, {'next': reverse('home')})
		self.assertRedirects(response, reverse('home'))
		self.assertTrue(post.likes.filter(pk=viewer.pk).exists())
		self.assertTrue(Notification.objects.filter(
			recipient=author,
			sender=viewer,
			notification_type=Notification.LIKE,
			post=post,
		).exists())
		self.assertContains(self.client.get(reverse('home')), 'data-like-count>1</span>')
		self.assertContains(self.client.get(reverse('home')), 'aria-pressed="true"')

		response = self.client.post(url, {'next': reverse('home')})
		self.assertRedirects(response, reverse('home'))
		self.assertFalse(post.likes.filter(pk=viewer.pk).exists())

	def test_like_ajax_returns_updated_state_and_count(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		author = get_user_model().objects.create_user(username='author', password='Kz!v2pL8#rQ4')
		post = author.post_set.create(desc='AJAX like testi')
		self.client.force_login(viewer)
		url = reverse('like_post', args=[post.pk])

		response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json(), {'liked': True, 'likes_count': 1})
		self.assertTrue(post.likes.filter(pk=viewer.pk).exists())

		response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

		self.assertEqual(response.json(), {'liked': False, 'likes_count': 0})
		self.assertFalse(post.likes.filter(pk=viewer.pk).exists())

	def test_comment_post_creates_comment_and_returns_to_profile_feed(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		author = get_user_model().objects.create_user(username='author', password='Kz!v2pL8#rQ4')
		post = author.post_set.create(desc='Comment testi')
		SocialAccount.objects.create(
			user=viewer,
			provider='google',
			uid='google-commenter-id',
			extra_data={'picture': 'https://example.com/commenter-avatar.jpg'},
		)
		self.client.force_login(viewer)

		response = self.client.post(
			reverse('add_comment', args=[post.pk]),
			{'text': 'Yaxshi post!', 'next': reverse('public_profile', args=[author.pk])},
		)

		self.assertRedirects(response, reverse('public_profile', args=[author.pk]))
		comment = post.comments.get()
		self.assertEqual(comment.author, viewer)
		self.assertEqual(comment.text, 'Yaxshi post!')
		profile_response = self.client.get(reverse('public_profile', args=[author.pk]))
		self.assertContains(profile_response, 'Yaxshi post!')
		self.assertContains(profile_response, 'src="https://example.com/commenter-avatar.jpg"')
		self.assertContains(profile_response, '<textarea')
		self.assertContains(profile_response, 'comment-form-avatar')
		self.assertContains(profile_response, 'data-comment-toggle')
		self.assertContains(profile_response, 'data-comments-list hidden')

	def test_comment_ajax_returns_new_comment_and_count(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		author = get_user_model().objects.create_user(username='author', password='Kz!v2pL8#rQ4')
		post = author.post_set.create(desc='AJAX comment testi')
		self.client.force_login(viewer)

		response = self.client.post(
			reverse('add_comment', args=[post.pk]),
			{'text': '  Yaxshi fikr  '},
			HTTP_X_REQUESTED_WITH='XMLHttpRequest',
		)

		self.assertEqual(response.status_code, 200)
		data = response.json()
		self.assertEqual(data['comments_count'], 1)
		self.assertEqual(data['comment']['text'], 'Yaxshi fikr')
		self.assertEqual(data['comment']['username'], 'viewer')
		self.assertTrue(data['comment']['created_at_iso'])
		self.assertEqual(post.comments.count(), 1)

	def test_invalid_comment_ajax_returns_validation_error_without_creating_comment(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		author = get_user_model().objects.create_user(username='author', password='Kz!v2pL8#rQ4')
		post = author.post_set.create(desc='AJAX invalid comment testi')
		self.client.force_login(viewer)

		response = self.client.post(
			reverse('add_comment', args=[post.pk]),
			{'text': '   '},
			HTTP_X_REQUESTED_WITH='XMLHttpRequest',
		)

		self.assertEqual(response.status_code, 400)
		self.assertIn('text', response.json()['errors'])
		self.assertEqual(post.comments.count(), 0)

	def test_follow_toggle_updates_profile_state_and_counts(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		target = get_user_model().objects.create_user(username='target', password='Kz!v2pL8#rQ4')
		self.client.force_login(viewer)
		follow_url = reverse('follow_toggle', args=[target.pk])

		response = self.client.post(follow_url, {'next': reverse('public_profile', args=[target.pk])})
		self.assertRedirects(response, reverse('public_profile', args=[target.pk]))
		self.assertTrue(viewer.following.filter(pk=target.pk).exists())
		profile_response = self.client.get(reverse('public_profile', args=[target.pk]))
		self.assertContains(profile_response, 'Kuzatilyapti')
		self.assertContains(
			profile_response,
			'<strong data-followers-count>1</strong> kuzatuvchi',
		)

		self.client.post(follow_url, {'next': reverse('public_profile', args=[target.pk])})
		self.assertFalse(viewer.following.filter(pk=target.pk).exists())

	def test_follow_ajax_returns_updated_state_and_follower_count(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		target = get_user_model().objects.create_user(username='target', password='Kz!v2pL8#rQ4')
		self.client.force_login(viewer)
		url = reverse('follow_toggle', args=[target.pk])

		response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json(), {'following': True, 'followers_count': 1})
		self.assertTrue(viewer.following.filter(pk=target.pk).exists())

		response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

		self.assertEqual(response.json(), {'following': False, 'followers_count': 0})
		self.assertFalse(viewer.following.filter(pk=target.pk).exists())

	def test_notifications_show_social_activity_and_link_to_the_post(self):
		author = get_user_model().objects.create_user(username='post_author', password='Kz!v2pL8#rQ4')
		actor = get_user_model().objects.create_user(username='activity_user', password='Kz!v2pL8#rQ4')
		post = author.post_set.create(title='Bildirishnoma posti', desc='Aniq postga olib borishi kerak')
		self.client.force_login(actor)

		self.client.post(reverse('like_post', args=[post.pk]))
		self.client.post(reverse('add_comment', args=[post.pk]), {'text': 'Ajoyib post!'})
		self.client.post(reverse('follow_toggle', args=[author.pk]))

		self.client.force_login(author)
		response = self.client.get(reverse('notifications'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'activity_user')
		self.assertContains(response, 'like bosdi')
		self.assertContains(response, 'izoh qoldirdi')
		self.assertContains(response, 'Ajoyib post!')
		self.assertContains(response, 'kuzatishni boshladi')
		self.assertContains(
			response,
			f'href="{reverse("profile")}#post-{post.pk}"',
		)
		self.assertEqual(
			Notification.objects.filter(recipient=author, is_read=False).count(),
			3,
		)
		self.client.post(reverse('mark_notifications_read'))
		self.assertEqual(
			Notification.objects.filter(recipient=author, is_read=False).count(),
			0,
		)

	def test_profile_shows_post_link_and_only_own_posts(self):
		user = get_user_model().objects.create_user(username='poster', password='Kz!v2pL8#rQ4')
		other_user = get_user_model().objects.create_user(username='another', password='Kz!v2pL8#rQ4')
		user.post_set.create(title='Mening postim', desc='Shaxsiy post')
		other_user.post_set.create(title='Boshqa post', desc='Boshqa foydalanuvchi posti')
		self.client.force_login(user)

		response = self.client.get(reverse('profile'))

		self.assertContains(response, reverse('post_create'))
		self.assertNotContains(response, 'post-form-fields')
		self.assertContains(response, 'profile-post-grid')
		self.assertContains(response, 'data-followers-count')
		self.assertContains(response, 'Mening postim')
		self.assertNotContains(response, 'Boshqa post')

	def test_profile_shows_followers_and_following_in_modal_panels(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		profile_user = get_user_model().objects.create_user(username='profileuser', password='Kz!v2pL8#rQ4')
		follower = get_user_model().objects.create_user(username='follower', password='Kz!v2pL8#rQ4')
		followed = get_user_model().objects.create_user(username='followed', password='Kz!v2pL8#rQ4')
		follower.following.add(profile_user)
		profile_user.following.add(followed)
		self.client.force_login(viewer)

		response = self.client.get(reverse('public_profile', args=[profile_user.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'data-open-follow-modal="followers"')
		self.assertContains(response, 'data-open-follow-modal="following"')
		self.assertContains(response, '@follower')
		self.assertContains(response, '@followed')
		self.assertContains(response, 'aria-modal="true"')
		self.assertContains(response, 'followers-panel')
		self.assertContains(response, 'following-panel')

	def test_search_page_shows_search_prompt_without_query(self):
		user = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		self.client.force_login(user)

		response = self.client.get(reverse('search_users'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Kimni izlayapsiz?')
		self.assertContains(response, 'name="q"')

	def test_search_page_displays_matching_users_and_follow_state(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		target = get_user_model().objects.create_user(
			username='ali_dev',
			first_name='Ali',
			last_name='Valiyev',
			password='Kz!v2pL8#rQ4',
		)
		viewer.following.add(target)
		self.client.force_login(viewer)

		response = self.client.get(reverse('search_users'), {'q': 'ali'})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '@ali_dev')
		self.assertContains(response, 'Ali Valiyev')
		self.assertContains(response, 'Kuzatilyapti')
		self.assertContains(response, reverse('public_profile', args=[target.pk]))

		full_name_response = self.client.get(
			reverse('search_users'),
			{'q': 'ali valiyev'},
		)
		self.assertContains(full_name_response, '@ali_dev')

	def test_live_search_returns_matching_users_as_json(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		target = get_user_model().objects.create_user(username='ali_dev', password='Kz!v2pL8#rQ4')
		self.client.force_login(viewer)

		response = self.client.get(
			reverse('search_users'),
			{'q': 'ali'},
			HTTP_X_REQUESTED_WITH='XMLHttpRequest',
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['results'][0]['username'], 'ali_dev')
		self.assertIn('profile_url', response.json()['results'][0])

	def test_search_page_shows_empty_state_when_no_users_match(self):
		viewer = get_user_model().objects.create_user(username='viewer', password='Kz!v2pL8#rQ4')
		self.client.force_login(viewer)

		response = self.client.get(reverse('search_users'), {'q': 'missing-user'})

		self.assertContains(response, 'Foydalanuvchi topilmadi')

	def test_profile_edit_page_renders_forms_and_google_avatar(self):
		user = get_user_model().objects.create_user(username='googleuser', password='Kz!v2pL8#rQ4')
		SocialAccount.objects.create(
			user=user,
			provider='google',
			uid='google-user-id',
			extra_data={'picture': 'https://example.com/google-avatar.jpg'},
		)
		self.client.force_login(user)

		response = self.client.get(reverse('profile_edit'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Shaxsiy ma’lumotlar')
		self.assertContains(response, 'Parolni o‘zgartirish')
		self.assertContains(response, 'src="https://example.com/google-avatar.jpg"')

	def test_profile_edit_page_shows_default_avatar_without_google_picture(self):
		user = get_user_model().objects.create_user(username='newuser', password='Kz!v2pL8#rQ4')
		self.client.force_login(user)

		response = self.client.get(reverse('profile_edit'))

		self.assertContains(response, 'src="/media/avatars/user.png"')


class ChatFlowTests(TransactionTestCase):
	def setUp(self):
		self.first_user = get_user_model().objects.create_user(
			username='first_user',
			password='Kz!v2pL8#rQ4',
		)
		self.second_user = get_user_model().objects.create_user(
			username='second_user',
			password='Kz!v2pL8#rQ4',
		)
		participant_a, participant_b = sorted(
			(self.first_user, self.second_user),
			key=lambda user: str(user.pk),
		)
		self.conversation = Conversation.objects.create(
			participant_a=participant_a,
			participant_b=participant_b,
		)

	def test_post_share_creates_chat_message_and_renders_post_details(self):
		post = self.first_user.post_set.create(
			title='Ulashilgan sarlavha',
			desc='Ulashilgan post tavsifi',
		)
		post.likes.add(self.second_user)
		post.comments.create(author=self.second_user, text='Ajoyib post!')
		self.client.force_login(self.first_user)

		response = self.client.post(
			reverse('share_post'),
			{
				'post_id': str(post.pk),
				'recipient_ids': [str(self.second_user.pk)],
			},
			HTTP_X_REQUESTED_WITH='XMLHttpRequest',
		)

		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.json()['sent_count'], 1)
		message = DirectMessage.objects.get(
			conversation=self.conversation,
			sender=self.first_user,
		)
		self.assertEqual(message.shared_post, post)
		self.assertEqual(message.text, '')

		self.client.force_login(self.second_user)
		chat_response = self.client.get(
			reverse('chat_conversation', args=[self.conversation.pk]),
		)
		self.assertContains(chat_response, 'shared-post-card')
		self.assertContains(chat_response, 'Ulashilgan sarlavha')
		self.assertContains(chat_response, 'Ulashilgan post tavsifi')
		self.assertContains(chat_response, '♥ 1')
		self.assertContains(chat_response, 'Ajoyib post!')

	def test_post_share_rejects_self_and_invalid_recipients(self):
		post = self.first_user.post_set.create(desc='Ulashish validatsiyasi')
		self.client.force_login(self.first_user)

		self_response = self.client.post(
			reverse('share_post'),
			{
				'post_id': str(post.pk),
				'recipient_ids': [str(self.first_user.pk)],
			},
		)
		invalid_response = self.client.post(
			reverse('share_post'),
			{
				'post_id': str(post.pk),
				'recipient_ids': ['not-a-user-id'],
			},
		)

		self.assertEqual(self_response.status_code, 400)
		self.assertEqual(invalid_response.status_code, 400)
		self.assertFalse(DirectMessage.objects.filter(shared_post=post).exists())

	def test_post_share_user_search_excludes_self_and_inactive_users(self):
		active_user = get_user_model().objects.create_user(
			username='target_user',
			password='Kz!v2pL8#rQ4',
		)
		get_user_model().objects.create_user(
			username='inactive_target',
			password='Kz!v2pL8#rQ4',
			is_active=False,
		)
		self.client.force_login(self.first_user)

		response = self.client.get(
			reverse('share_user_search'),
			{'q': 'target'},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			[user['id'] for user in response.json()['users']],
			[str(active_user.pk)],
		)
		response = self.client.get(
			reverse('share_user_search'),
			{'q': 'first'},
		)
		self.assertEqual(response.json()['users'], [])

	def test_start_chat_creates_conversation_and_only_participants_can_view(self):
		self.client.force_login(self.first_user)

		response = self.client.get(
			reverse('start_chat', args=[self.second_user.pk]),
		)

		self.assertRedirects(
			response,
			reverse('chat_conversation', args=[self.conversation.pk]),
		)
		chat_response = self.client.get(
			reverse('chat_conversation', args=[self.conversation.pk]),
		)
		self.assertContains(chat_response, 'second_user')

		outsider = get_user_model().objects.create_user(
			username='outsider',
			password='Kz!v2pL8#rQ4',
		)
		self.client.force_login(outsider)
		response = self.client.get(
			reverse('chat_conversation', args=[self.conversation.pk]),
		)
		self.assertRedirects(response, reverse('chat_inbox'))

	def test_chat_audio_upload_saves_audio_and_rejects_non_participants(self):
		with tempfile.TemporaryDirectory() as media_dir:
			with override_settings(MEDIA_ROOT=media_dir):
				self.client.force_login(self.first_user)
				response = self.client.post(
					reverse('chat_audio_upload', args=[self.conversation.pk]),
					{
						'audio': SimpleUploadedFile(
							'voice.webm',
							b'webm audio bytes',
							content_type='audio/webm;codecs=opus',
						),
					},
				)

				self.assertEqual(response.status_code, 201)
				message = DirectMessage.objects.get(
					conversation=self.conversation,
				)
				self.assertTrue(message.audio.name.startswith('chat/audio/'))
				self.assertEqual(message.text, '')
				self.assertTrue(Path(media_dir, message.audio.name).is_file())
				audio_url = response.json()['message']['audio_url']
				audio_response = self.client.get(audio_url)
				self.assertEqual(audio_response.status_code, 200)
				audio_response.close()

				outsider = get_user_model().objects.create_user(
					username='outsider',
					password='Kz!v2pL8#rQ4',
				)
				self.client.force_login(outsider)
				response = self.client.post(
					reverse('chat_audio_upload', args=[self.conversation.pk]),
					{
						'audio': SimpleUploadedFile(
							'voice.webm',
							b'webm audio bytes',
							content_type='audio/webm',
						),
					},
				)
				self.assertEqual(response.status_code, 403)
				self.assertEqual(self.client.get(audio_url).status_code, 404)

	def test_chat_image_upload_waits_for_post_and_serves_only_to_participants(self):
		with tempfile.TemporaryDirectory() as media_dir:
			with override_settings(MEDIA_ROOT=media_dir):
				self.client.force_login(self.first_user)
				response = self.client.post(
					reverse('chat_audio_upload', args=[self.conversation.pk]),
					{
						'media': SimpleUploadedFile(
							'photo.png',
							b'image bytes',
							content_type='image/png',
						),
					},
				)
				self.assertEqual(response.status_code, 201)
				self.assertEqual(response.json()['message']['media_type'], 'image/png')
				message = DirectMessage.objects.get(
					conversation=self.conversation,
				)
				self.assertTrue(message.attachment.name.startswith('chat/media/'))
				media_url = response.json()['message']['media_url']
				media_response = self.client.get(media_url)
				self.assertEqual(media_response.status_code, 200)
				media_response.close()

				outsider = get_user_model().objects.create_user(
					username='media_outsider',
					password='Kz!v2pL8#rQ4',
				)
				self.client.force_login(outsider)
				self.assertEqual(self.client.get(media_url).status_code, 404)

	def test_chat_sidebar_counts_unread_messages_per_conversation_and_marks_open_chat_read(self):
		third_user = get_user_model().objects.create_user(
			username='third_user',
			password='Kz!v2pL8#rQ4',
		)
		second_conversation = Conversation.objects.create(
			participant_a=min(
				(self.first_user, third_user),
				key=lambda user: str(user.pk),
			),
			participant_b=max(
				(self.first_user, third_user),
				key=lambda user: str(user.pk),
			),
		)
		first_unread = DirectMessage.objects.create(
			conversation=self.conversation,
			sender=self.second_user,
			text='Birinchi xabar',
		)
		second_unread = DirectMessage.objects.create(
			conversation=self.conversation,
			sender=self.second_user,
			text='Ikkinchi xabar',
		)
		other_conversation_message = DirectMessage.objects.create(
			conversation=second_conversation,
			sender=third_user,
			text='Boshqa suhbatdagi xabar',
		)
		self.client.force_login(self.first_user)

		inbox_response = self.client.get(reverse('chat_inbox'))

		self.assertContains(inbox_response, 'data-unread-badge>2</span>')
		self.assertContains(inbox_response, 'data-unread-badge>1</span>')

		chat_response = self.client.get(
			reverse('chat_conversation', args=[self.conversation.pk]),
		)

		first_unread.refresh_from_db()
		second_unread.refresh_from_db()
		other_conversation_message.refresh_from_db()
		self.assertTrue(first_unread.is_read)
		self.assertTrue(second_unread.is_read)
		self.assertFalse(other_conversation_message.is_read)
		self.assertContains(chat_response, 'Birinchi xabar')
		self.assertContains(chat_response, 'Ikkinchi xabar')

	def test_websocket_saves_and_broadcasts_message_to_both_participants(self):
		path = f'/ws/chat/{self.conversation.pk}/'
		application = URLRouter(websocket_urlpatterns)

		async def connect_as(user):
			communicator = WebsocketCommunicator(application, path)
			communicator.scope['user'] = user
			connected, _ = await communicator.connect()
			self.assertTrue(connected)
			return communicator

		async def receive_type(communicator, expected_type):
			for _ in range(5):
				event = await communicator.receive_json_from(timeout=1)
				if event.get('type') == expected_type:
					return event
			self.fail(f'{expected_type} WebSocket event was not received')

		async def exercise_chat():
			first = await connect_as(self.first_user)
			second = await connect_as(self.second_user)
			try:
				await first.send_json_to({
					'type': 'typing',
					'typing': True,
				})
				typing_event = await receive_type(second, 'typing')
				self.assertTrue(typing_event['typing'])

				await first.send_json_to({
					'type': 'message',
					'text': 'Salom, chat!',
				})
				first_event = await receive_type(first, 'message')
				second_event = await receive_type(second, 'message')
				self.assertEqual(first_event['message']['text'], 'Salom, chat!')
				self.assertEqual(second_event['message']['sender_username'], 'first_user')
			finally:
				await first.disconnect()
				await second.disconnect()

		async_to_sync(exercise_chat)()
		self.assertEqual(
			DirectMessage.objects.filter(conversation=self.conversation).count(),
			1,
		)
		self.assertTrue(
			DirectMessage.objects.get(conversation=self.conversation).is_read,
		)

	def test_websocket_edits_and_deletes_own_messages_in_real_time(self):
		path = f'/ws/chat/{self.conversation.pk}/'
		application = URLRouter(websocket_urlpatterns)

		async def connect_as(user):
			communicator = WebsocketCommunicator(application, path)
			communicator.scope['user'] = user
			connected, _ = await communicator.connect()
			self.assertTrue(connected)
			return communicator

		async def receive_type(communicator, expected_type):
			for _ in range(10):
				event = await communicator.receive_json_from(timeout=1)
				if event.get('type') == expected_type:
					return event
			self.fail(f'{expected_type} WebSocket event was not received')

		async def exercise_chat():
			first = await connect_as(self.first_user)
			second = await connect_as(self.second_user)
			try:
				await first.send_json_to({
					'type': 'message',
					'text': 'Eski matn',
				})
				message_event = await receive_type(first, 'message')
				await receive_type(second, 'message')
				message_id = message_event['message']['id']

				await first.send_json_to({
					'type': 'edit_message',
					'message_id': message_id,
					'text': 'Yangi matn',
				})
				first_edit = await receive_type(first, 'message_edited')
				second_edit = await receive_type(second, 'message_edited')
				self.assertEqual(first_edit['message']['text'], 'Yangi matn')
				self.assertEqual(second_edit['message']['text'], 'Yangi matn')

				await second.send_json_to({
					'type': 'edit_message',
					'message_id': message_id,
					'text': 'Ruxsatsiz tahrir',
				})
				error = await receive_type(second, 'error')
				self.assertIn('tahrirlash mumkin emas', error['message'])

				await second.send_json_to({
					'type': 'delete_message',
					'message_id': message_id,
				})
				error = await receive_type(second, 'error')
				self.assertIn('o‘chirish mumkin emas', error['message'])

				await first.send_json_to({
					'type': 'delete_message',
					'message_id': message_id,
				})
				first_delete = await receive_type(first, 'message_deleted')
				second_delete = await receive_type(second, 'message_deleted')
				self.assertEqual(first_delete['message_id'], message_id)
				self.assertEqual(second_delete['message_id'], message_id)
			finally:
				await first.disconnect()
				await second.disconnect()
			return message_id

		message_id = async_to_sync(exercise_chat)()
		self.assertFalse(DirectMessage.objects.filter(
			pk=message_id,
			conversation=self.conversation,
		).exists())

	def test_websocket_rejects_anonymous_and_non_participant_users(self):
		application = URLRouter(websocket_urlpatterns)

		async def rejected_as(user):
			communicator = WebsocketCommunicator(
				application,
				f'/ws/chat/{self.conversation.pk}/',
			)
			communicator.scope['user'] = user
			connected, _ = await communicator.connect()
			self.assertFalse(connected)

		outsider = get_user_model().objects.create_user(
			username='outsider',
			password='Kz!v2pL8#rQ4',
		)
		async_to_sync(rejected_as)(AnonymousUser())
		async_to_sync(rejected_as)(outsider)
