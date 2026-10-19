import json
import uuid

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.cache import cache
from django.utils import timezone

from .chat_payloads import direct_message_payload
from .models import Conversation, DirectMessage


PRESENCE_TIMEOUT = 45
MAX_MESSAGE_LENGTH = 4000


def _message_payload(message):
    return direct_message_payload(message)


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        try:
            self.conversation_id = uuid.UUID(
                str(self.scope['url_route']['kwargs']['conversation_id'])
            )
        except (KeyError, ValueError):
            await self.close(code=4404)
            return

        participants = await self.get_conversation_participants(
            self.conversation_id,
            user.pk,
        )
        if not participants:
            await self.close(code=4403)
            return

        self.user_id = str(user.pk)
        self.peer_id = str(participants['peer_id'])
        self.room_group = f"chat_{self.conversation_id.hex}"
        self.peer_presence_group = f"presence_{self.peer_id}"
        self.user_inbox_group = f"inbox_{self.user_id}"
        self.presence_key = f"chat:presence:{self.user_id}"
        await self.mark_conversation_read()

        await self.channel_layer.group_add(self.room_group, self.channel_name)
        await self.channel_layer.group_add(
            self.peer_presence_group,
            self.channel_name,
        )
        await self.channel_layer.group_add(
            self.user_inbox_group,
            self.channel_name,
        )
        self.presence_count = await sync_to_async(
            self.register_presence,
            thread_sensitive=False,
        )()
        await self.accept()

        await self.channel_layer.group_send(
            f"presence_{self.user_id}",
            {
                'type': 'presence_changed',
                'user_id': self.user_id,
                'online': True,
            },
        )
        await self.send_json({
            'type': 'presence',
            'user_id': self.peer_id,
            'online': await sync_to_async(cache.get, thread_sensitive=False)(
                f"chat:presence:{self.peer_id}",
                0,
            ) > 0,
        })

    async def disconnect(self, close_code):
        if not hasattr(self, 'conversation_id'):
            return

        await self.channel_layer.group_discard(
            self.room_group,
            self.channel_name,
        )
        await self.channel_layer.group_discard(
            self.peer_presence_group,
            self.channel_name,
        )
        await self.channel_layer.group_discard(
            self.user_inbox_group,
            self.channel_name,
        )
        count = await sync_to_async(
            self.unregister_presence,
            thread_sensitive=False,
        )()
        if count == 0:
            await self.channel_layer.group_send(
                f"presence_{self.user_id}",
                {
                    'type': 'presence_changed',
                    'user_id': self.user_id,
                    'online': False,
                },
            )

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_json({'type': 'error', 'message': 'Noto‘g‘ri so‘rov.'})
            return

        if not isinstance(data, dict):
            await self.send_json({'type': 'error', 'message': 'Noto‘g‘ri so‘rov.'})
            return

        message_type = data.get('type')
        if message_type == 'heartbeat':
            await sync_to_async(
                cache.touch,
                thread_sensitive=False,
            )(self.presence_key, PRESENCE_TIMEOUT)
            await self.send_json({'type': 'heartbeat'})
            return

        if message_type == 'typing':
            await self.channel_layer.group_send(
                self.room_group,
                {
                    'type': 'typing_changed',
                    'user_id': self.user_id,
                    'typing': bool(data.get('typing')),
                },
            )
            return

        if message_type in ('edit_message', 'delete_message'):
            await self.handle_message_change(data, message_type)
            return

        if message_type != 'message':
            await self.send_json({
                'type': 'error',
                'message': 'Noma’lum amal.',
            })
            return

        text = data.get('text')
        if not isinstance(text, str):
            await self.send_json({
                'type': 'error',
                'message': 'Xabar matni noto‘g‘ri.',
            })
            return
        text = text.strip()
        if not text or len(text) > MAX_MESSAGE_LENGTH:
            await self.send_json({
                'type': 'error',
                'message': 'Xabar 1–4000 ta belgidan iborat bo‘lishi kerak.',
            })
            return

        message = await self.create_message(
            self.conversation_id,
            self.user_id,
            text,
        )
        payload = {
            'id': str(message['id']),
            'text': message['text'],
            'sender_id': self.user_id,
            'sender_username': message['sender_username'],
            'created_at': message['created_at'],
            'created_at_iso': message['created_at_iso'],
        }
        await self.channel_layer.group_send(
            self.room_group,
            {
                'type': 'chat_message',
                'message': payload,
            },
        )
        await self.channel_layer.group_send(
            f"inbox_{self.peer_id}",
            {
                'type': 'inbox_message',
                'conversation_id': str(self.conversation_id),
                'message': payload,
                'peer_username': message['sender_username'],
            },
        )

    async def handle_message_change(self, data, message_type):
        message_id = data.get('message_id')
        try:
            message_id = uuid.UUID(str(message_id))
        except (TypeError, ValueError):
            await self.send_json({
                'type': 'error',
                'message': 'Xabar topilmadi.',
            })
            return

        if message_type == 'edit_message':
            text = data.get('text')
            if not isinstance(text, str):
                await self.send_json({
                    'type': 'error',
                    'message': 'Xabar matni noto‘g‘ri.',
                })
                return
            text = text.strip()
            if not text or len(text) > MAX_MESSAGE_LENGTH:
                await self.send_json({
                    'type': 'error',
                    'message': 'Xabar 1–4000 ta belgidan iborat bo‘lishi kerak.',
                })
                return

            message = await self.edit_message(message_id, text)
            if message is None:
                await self.send_json({
                    'type': 'error',
                    'message': 'Bu xabarni tahrirlash mumkin emas.',
                })
                return
            await self.channel_layer.group_send(
                self.room_group,
                {
                    'type': 'message_edited',
                    'message': message['message'],
                },
            )
            preview_message = message['preview']
        else:
            result = await self.delete_message(message_id)
            if result is None:
                await self.send_json({
                    'type': 'error',
                    'message': 'Bu xabarni o‘chirish mumkin emas.',
                })
                return
            preview_message = result['message']
            await self.channel_layer.group_send(
                self.room_group,
                {
                    'type': 'message_deleted',
                    'message_id': str(message_id),
                },
            )

        inbox_event = {
            'type': 'inbox_update',
            'conversation_id': str(self.conversation_id),
            'message': preview_message,
        }
        await self.channel_layer.group_send(
            f"inbox_{self.user_id}",
            inbox_event,
        )
        await self.channel_layer.group_send(
            f"inbox_{self.peer_id}",
            inbox_event,
        )

    async def chat_message(self, event):
        message = event['message']
        unread_count = None
        if message['sender_id'] != self.user_id:
            unread_count = await self.mark_conversation_read()
        await self.send_json({
            'type': 'message',
            'message': message,
            'unread_count': unread_count,
        })

    async def message_edited(self, event):
        await self.send_json({
            'type': 'message_edited',
            'message': event['message'],
        })

    async def message_deleted(self, event):
        await self.send_json({
            'type': 'message_deleted',
            'message_id': event['message_id'],
        })

    async def typing_changed(self, event):
        if event['user_id'] == self.user_id:
            return
        await self.send_json({
            'type': 'typing',
            'user_id': event['user_id'],
            'typing': event['typing'],
        })

    async def presence_changed(self, event):
        if event['user_id'] != self.peer_id:
            return
        await self.send_json({
            'type': 'presence',
            'user_id': event['user_id'],
            'online': event['online'],
        })

    async def inbox_message(self, event):
        unread_count = await self.get_unread_count(
            event['conversation_id'],
            self.user_id,
        )
        await self.send_json({
            'type': 'inbox',
            'conversation_id': event['conversation_id'],
            'message': event['message'],
            'peer_username': event['peer_username'],
            'peer_id': event.get('peer_id'),
            'peer_avatar_url': event.get('peer_avatar_url'),
            'conversation_url': event.get('conversation_url'),
            'unread_count': unread_count,
        })

    async def inbox_update(self, event):
        await self.send_json({
            'type': 'inbox_update',
            'conversation_id': event['conversation_id'],
            'message': event['message'],
        })

    @database_sync_to_async
    def get_conversation_participants(self, conversation_id, user_id):
        conversation = (
            Conversation.objects
            .filter(pk=conversation_id)
            .only('participant_a_id', 'participant_b_id')
            .first()
        )
        if conversation is None:
            return None
        if str(conversation.participant_a_id) == str(user_id):
            return {'peer_id': conversation.participant_b_id}
        if str(conversation.participant_b_id) == str(user_id):
            return {'peer_id': conversation.participant_a_id}
        return None

    @database_sync_to_async
    def create_message(self, conversation_id, user_id, text):
        message = DirectMessage.objects.create(
            conversation_id=conversation_id,
            sender_id=user_id,
            text=text,
        )
        Conversation.objects.filter(pk=conversation_id).update(
            updated_at=timezone.now(),
        )
        return {
            **_message_payload(message),
            'sender_username': message.sender.username,
        }

    @database_sync_to_async
    def edit_message(self, message_id, text):
        message = DirectMessage.objects.filter(
            pk=message_id,
            conversation_id=self.conversation_id,
            sender_id=self.user_id,
            audio='',
            attachment='',
            shared_post__isnull=True,
        ).first()
        if message is None:
            return None
        message.text = text
        message.save(update_fields=['text', 'updated_at'])
        latest_message = (
            DirectMessage.objects.filter(conversation_id=self.conversation_id)
            .order_by('-created_at')
            .first()
        )
        return {
            'message': _message_payload(message),
            'preview': (
                _message_payload(latest_message)
                if latest_message is not None
                else None
            ),
        }

    @database_sync_to_async
    def delete_message(self, message_id):
        message = DirectMessage.objects.filter(
            pk=message_id,
            conversation_id=self.conversation_id,
            sender_id=self.user_id,
        ).first()
        if message is None:
            return None
        if message.audio:
            message.audio.delete(save=False)
        if message.attachment:
            message.attachment.delete(save=False)
        message.delete()
        latest_message = (
            DirectMessage.objects.filter(conversation_id=self.conversation_id)
            .order_by('-created_at')
            .first()
        )
        if latest_message is None:
            return {'message': None}
        return {'message': _message_payload(latest_message)}

    @database_sync_to_async
    def mark_conversation_read(self):
        DirectMessage.objects.filter(
            conversation_id=self.conversation_id,
            is_read=False,
        ).exclude(sender_id=self.user_id).update(is_read=True)
        return DirectMessage.objects.filter(
            conversation_id=self.conversation_id,
            is_read=False,
        ).exclude(sender_id=self.user_id).count()

    @database_sync_to_async
    def get_unread_count(self, conversation_id, user_id):
        return DirectMessage.objects.filter(
            conversation_id=conversation_id,
            is_read=False,
        ).exclude(sender_id=user_id).count()

    def register_presence(self):
        cache.add(self.presence_key, 0, PRESENCE_TIMEOUT)
        count = cache.incr(self.presence_key)
        cache.touch(self.presence_key, PRESENCE_TIMEOUT)
        return count

    def unregister_presence(self):
        count = cache.get(self.presence_key)
        if count is None:
            return 0
        try:
            count = cache.decr(self.presence_key)
        except ValueError:
            return 0
        if count <= 0:
            cache.delete(self.presence_key)
            return 0
        return count
