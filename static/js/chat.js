(() => {
    const chat = document.querySelector("[data-chat]");
    if (!chat) return;

    const filter = chat.querySelector("[data-chat-filter]");
    if (filter) {
        filter.addEventListener("input", () => {
            const query = filter.value.trim().toLowerCase();
            chat.querySelectorAll(".chat-conversation").forEach((item) => {
                item.hidden = !item.dataset.peerName.includes(query);
            });
        });
    }

    const socketPath = chat.dataset.socketPath;
    if (!socketPath) return;

    const messages = chat.querySelector("[data-chat-messages]");
    const form = chat.querySelector("[data-chat-form]");
    const input = chat.querySelector("[data-chat-input]");
    const sendButton = chat.querySelector("[data-chat-send]");
    const recordButton = chat.querySelector("[data-chat-record]");
    const emojiToggle = chat.querySelector("[data-emoji-toggle]");
    const emojiPicker = chat.querySelector("[data-emoji-picker]");
    const mediaPick = chat.querySelector("[data-media-pick]");
    const mediaInput = chat.querySelector("[data-media-input]");
    const mediaPreview = chat.querySelector("[data-media-preview]");
    const mediaPreviewContent = chat.querySelector("[data-media-preview-content]");
    const mediaSend = chat.querySelector("[data-media-send]");
    const mediaCancel = chat.querySelector("[data-media-cancel]");
    const recordingStatus = chat.querySelector("[data-chat-recording-status]");
    const errorBox = chat.querySelector("[data-chat-error]");
    const typingIndicator = chat.querySelector("[data-chat-typing]");
    const currentUserId = chat.dataset.currentUser;
    const activeConversationId = chat.dataset.activeConversation;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socketUrl = `${protocol}//${window.location.host}${socketPath}`;
    const socket = new WebSocket(socketUrl);
    let heartbeatTimer;
    let typingTimer;
    let typingStopTimer;
    let isTyping = false;
    let recorder;
    let recordingStream;
    let recordingChunks = [];
    let recordingStartedAt = 0;
    let recordingTimer;
    let audioUploading = false;
    let requestingMicrophone = false;
    let selectedMedia = null;
    let mediaPreviewUrl = null;
    let mediaUploading = false;
    const maxRecordingSeconds = 120;
    const maxAudioBytes = 10 * 1024 * 1024;

    const showError = (message = "") => {
        errorBox.textContent = message;
        errorBox.hidden = !message;
    };

    const scrollToLatest = () => {
        messages.scrollTop = messages.scrollHeight;
    };

    const setRecordingStatus = (text = "") => {
        recordingStatus.textContent = text;
        recordingStatus.hidden = !text;
    };

    const formatAudioTime = (seconds) => {
        if (!Number.isFinite(seconds)) return "0:00";
        const minutes = Math.floor(seconds / 60);
        const remainder = String(Math.floor(seconds % 60)).padStart(2, "0");
        return `${minutes}:${remainder}`;
    };

    const setupVoicePlayer = (audio) => {
        if (audio.dataset.playerReady) return;
        audio.dataset.playerReady = "true";
        audio.controls = false;
        const player = document.createElement("div");
        player.className = "chat-voice-player";
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "chat-voice-toggle";
        toggle.setAttribute("aria-label", "Ovozni tinglash");
        toggle.textContent = "▶";
        const progress = document.createElement("input");
        progress.className = "chat-voice-progress";
        progress.type = "range";
        progress.min = "0";
        progress.max = "1000";
        progress.value = "0";
        progress.setAttribute("aria-label", "Ovozli xabar holati");
        const time = document.createElement("span");
        time.className = "chat-voice-time";
        time.textContent = "0:00";
        player.append(toggle, progress, time);
        audio.before(player);

        const updateProgress = () => {
            const duration = audio.duration || 0;
            progress.value = String(duration ? (audio.currentTime / duration) * 1000 : 0);
            time.textContent = formatAudioTime(audio.currentTime);
        };
        toggle.addEventListener("click", () => {
            if (audio.paused) {
                chat.querySelectorAll(".chat-voice-message").forEach((otherAudio) => {
                    if (otherAudio !== audio) otherAudio.pause();
                });
                audio.play().catch(() => showError("Ovozli xabarni ijro qilib bo‘lmadi."));
            } else {
                audio.pause();
            }
        });
        audio.addEventListener("play", () => {
            toggle.textContent = "Ⅱ";
            toggle.setAttribute("aria-label", "Pauza");
        });
        audio.addEventListener("pause", () => {
            toggle.textContent = "▶";
            toggle.setAttribute("aria-label", "Ovozni tinglash");
        });
        audio.addEventListener("timeupdate", updateProgress);
        audio.addEventListener("loadedmetadata", () => {
            time.textContent = formatAudioTime(audio.duration);
        });
        audio.addEventListener("ended", () => {
            audio.currentTime = 0;
            updateProgress();
        });
        progress.addEventListener("input", () => {
            if (audio.duration) {
                audio.currentTime = (Number(progress.value) / 1000) * audio.duration;
            }
        });
        if (audio.readyState >= 1) {
            time.textContent = formatAudioTime(audio.duration);
            updateProgress();
        }
    };

    const updateRecordingTimer = () => {
        const seconds = Math.floor((Date.now() - recordingStartedAt) / 1000);
        const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
        const remainder = String(seconds % 60).padStart(2, "0");
        setRecordingStatus(`Yozilmoqda ${minutes}:${remainder} · Tugatish uchun mikrofonni bosing`);
        if (seconds >= maxRecordingSeconds) recorder.stop();
    };

    const uploadVoiceMessage = async (blob) => {
        if (blob.size > maxAudioBytes) {
            showError("Ovozli xabar hajmi 10 MB dan oshmasligi kerak.");
            setRecordingStatus();
            return;
        }
        if (socket.readyState !== WebSocket.OPEN) {
            showError("Chat serveriga ulanish uzildi. Qayta urinib ko‘ring.");
            setRecordingStatus();
            return;
        }

        audioUploading = true;
        recordButton.disabled = true;
        setRecordingStatus("Ovozli xabar yuborilmoqda...");
        const formData = new FormData();
        const extension = blob.type.includes("ogg") ? "ogg"
            : blob.type.includes("mp4") ? "m4a"
                : blob.type.includes("wav") ? "wav"
                    : blob.type.includes("mpeg") ? "mp3" : "webm";
        formData.append("audio", blob, `voice.${extension}`);

        try {
            const response = await fetch(chat.dataset.audioUploadUrl, {
                method: "POST",
                headers: {
                    "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
                },
                body: formData,
                credentials: "same-origin",
            });
            const result = response.headers.get("content-type")?.includes("application/json")
                ? await response.json()
                : {};
            if (!response.ok) throw new Error(result.error || "Ovozli xabar yuborilmadi.");
            showError();
        } catch (error) {
            showError(error.message || "Ovozli xabar yuborilmadi.");
        } finally {
            audioUploading = false;
            recordButton.disabled = socket.readyState !== WebSocket.OPEN;
            setRecordingStatus();
        }
    };

    const uploadSelectedMedia = async () => {
        if (!selectedMedia || mediaUploading || socket.readyState !== WebSocket.OPEN) return;
        mediaUploading = true;
        mediaPick.disabled = true;
        mediaSend.disabled = true;
        mediaCancel.disabled = true;
        const formData = new FormData();
        formData.append("media", selectedMedia);

        try {
            const response = await fetch(chat.dataset.audioUploadUrl, {
                method: "POST",
                headers: {
                    "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
                },
                body: formData,
                credentials: "same-origin",
            });
            const result = response.headers.get("content-type")?.includes("application/json")
                ? await response.json()
                : {};
            if (!response.ok) throw new Error(result.error || "Fayl yuborilmadi.");
            showError();
            clearMediaPreview();
        } catch (error) {
            showError(error.message || "Fayl yuborilmadi.");
        } finally {
            mediaUploading = false;
            mediaPick.disabled = false;
            mediaSend.disabled = !selectedMedia || socket.readyState !== WebSocket.OPEN;
            mediaCancel.disabled = false;
        }
    };

    function clearMediaPreview() {
        if (mediaPreviewUrl) URL.revokeObjectURL(mediaPreviewUrl);
        mediaPreviewUrl = null;
        selectedMedia = null;
        mediaInput.value = "";
        mediaPreviewContent.replaceChildren();
        mediaPreview.hidden = true;
        mediaSend.disabled = true;
    }

    const selectMedia = (file) => {
        if (!file) return;
        if (!file.type.startsWith("image/") && !file.type.startsWith("video/")) {
            showError("Faqat rasm yoki video tanlang.");
            mediaInput.value = "";
            return;
        }
        if (file.size > 20 * 1024 * 1024) {
            showError("Rasm yoki video hajmi 20 MB dan oshmasligi kerak.");
            mediaInput.value = "";
            return;
        }
        showError();
        clearMediaPreview();
        selectedMedia = file;
        mediaPreviewUrl = URL.createObjectURL(file);
        const preview = file.type.startsWith("video/")
            ? document.createElement("video")
            : document.createElement("img");
        preview.className = file.type.startsWith("video/")
            ? "chat-attachment-video"
            : "chat-attachment-image";
        preview.src = mediaPreviewUrl;
        if (preview instanceof HTMLVideoElement) {
            preview.controls = true;
            preview.muted = true;
            preview.playsInline = true;
        } else {
            preview.alt = "Yuboriladigan rasm";
        }
        const name = document.createElement("span");
        name.className = "chat-media-preview-name";
        name.textContent = file.name;
        mediaPreviewContent.append(preview, name);
        mediaPreview.hidden = false;
        mediaSend.disabled = socket.readyState !== WebSocket.OPEN;
    };

    const stopRecording = () => {
        if (recorder && recorder.state === "recording") recorder.stop();
    };

    const startRecording = async () => {
        if (requestingMicrophone || audioUploading) return;
        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
            showError("Brauzeringiz ovoz yozishni qo‘llab-quvvatlamaydi.");
            return;
        }
        requestingMicrophone = true;
        recordButton.disabled = true;
        try {
            recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mimeType = [
                "audio/webm;codecs=opus",
                "audio/ogg;codecs=opus",
                "audio/mp4",
            ].find((type) => MediaRecorder.isTypeSupported(type));
            recorder = mimeType
                ? new MediaRecorder(recordingStream, { mimeType })
                : new MediaRecorder(recordingStream);
            recordingChunks = [];
            recorder.addEventListener("dataavailable", (event) => {
                if (event.data.size) recordingChunks.push(event.data);
            });
            recorder.addEventListener("stop", () => {
                window.clearInterval(recordingTimer);
                recordingStream.getTracks().forEach((track) => track.stop());
                recordButton.classList.remove("is-recording");
                recordButton.setAttribute("aria-label", "Ovozli xabar yozish");
                recordButton.title = "Ovozli xabar yozish";
                uploadVoiceMessage(new Blob(recordingChunks, {
                    type: recorder.mimeType || "audio/webm",
                }));
            }, { once: true });
            recorder.start();
            recordingStartedAt = Date.now();
            recordButton.classList.add("is-recording");
            recordButton.setAttribute("aria-label", "Yozishni tugatib yuborish");
            recordButton.title = "Yozishni tugatib yuborish";
            updateRecordingTimer();
            recordingTimer = window.setInterval(updateRecordingTimer, 1000);
            requestingMicrophone = false;
            recordButton.disabled = false;
            showError();
        } catch {
            recordingStream?.getTracks().forEach((track) => track.stop());
            requestingMicrophone = false;
            recordButton.disabled = socket.readyState !== WebSocket.OPEN;
            setRecordingStatus();
            showError("Mikrofondan foydalanib bo‘lmadi. Ruxsatlarni tekshiring.");
        }
    };

    const updateConversationPreview = (message, conversationId) => {
        const item = chat.querySelector(
            `.chat-conversation[data-conversation-id="${conversationId}"]`
        );
        if (!item) return;
        const preview = item.querySelector("[data-conversation-preview]");
        const senderPrefix = message?.sender_id === currentUserId ? "Siz: " : "";
        const previewText = !message
            ? "Suhbatni boshlang"
            : message.shared_post
                ? "Post ulashildi"
            : message.is_audio
                ? "Ovozli xabar"
                : message.media_type
                    ? message.media_type.startsWith("video/") ? "Video" : "Rasm"
                    : message.text;
        preview.textContent = message ? `${senderPrefix}${previewText}` : previewText;
        const time = item.querySelector("time");
        time.textContent = message?.created_at || "";
    };

    const updateUnreadCount = (conversationId, count) => {
        if (!Number.isInteger(count)) return;
        const item = chat.querySelector(
            `.chat-conversation[data-conversation-id="${conversationId}"]`
        );
        const badge = item?.querySelector("[data-unread-badge]");
        if (!badge) return;
        badge.textContent = String(count);
        badge.hidden = count === 0;
        item.classList.toggle("has-unread", count > 0);
    };

    const ensureConversationItem = (event) => {
        let item = chat.querySelector(
            `.chat-conversation[data-conversation-id="${event.conversation_id}"]`
        );
        if (item || !event.peer_id || !event.conversation_url) return item;

        const list = chat.querySelector(".chat-conversation-list");
        list.querySelector(".chat-sidebar-empty")?.remove();
        item = document.createElement("a");
        item.className = "chat-conversation";
        item.href = event.conversation_url;
        item.dataset.conversationId = event.conversation_id;
        item.dataset.peerName = event.peer_username.toLowerCase();

        const avatar = document.createElement("span");
        avatar.className = "chat-avatar";
        if (event.peer_avatar_url) {
            const image = document.createElement("img");
            image.src = event.peer_avatar_url;
            image.alt = "";
            avatar.append(image);
        } else {
            avatar.textContent = event.peer_username.slice(0, 1).toUpperCase();
        }
        const presence = document.createElement("span");
        presence.className = "chat-online-dot";
        presence.dataset.peerPresence = event.peer_id;
        avatar.append(presence);

        const copy = document.createElement("span");
        copy.className = "chat-conversation-copy";
        const username = document.createElement("strong");
        username.textContent = event.peer_username;
        const preview = document.createElement("span");
        preview.dataset.conversationPreview = "";
        copy.append(username, preview);

        const badge = document.createElement("span");
        badge.className = "chat-unread-badge";
        badge.dataset.unreadBadge = "";
        badge.hidden = true;
        const time = document.createElement("time");
        time.className = "chat-conversation-time";
        item.append(avatar, copy, badge, time);
        list.prepend(item);
        const count = chat.querySelector(".chat-inbox-count");
        count.textContent = String(Number(count.textContent) + 1);
        return item;
    };

    const createMessageActions = (isMedia) => {
        const actions = document.createElement("div");
        actions.className = "chat-message-actions";
        const options = isMedia
            ? [["delete", "O‘chirish"]]
            : [["edit", "Tahrirlash"], ["delete", "O‘chirish"]];
        options.forEach(([action, label]) => {
            const button = document.createElement("button");
            button.type = "button";
            button.dataset.messageAction = action;
            button.textContent = label;
            actions.append(button);
        });
        return actions;
    };

    const createSharedPostCard = (post) => {
        const card = document.createElement("article");
        card.className = "shared-post-card";

        const header = document.createElement("header");
        header.className = "shared-post-author";
        const author = document.createElement("a");
        author.href = post.author_url;
        author.textContent = `@${post.author_username}`;
        const date = document.createElement("time");
        date.textContent = post.created_at;
        header.append(author, date);
        card.append(header);

        if (post.image_url || post.video_url) {
            const media = post.video_url
                ? document.createElement("video")
                : document.createElement("img");
            media.className = "shared-post-media";
            if (post.video_url) {
                media.controls = true;
                media.preload = "metadata";
                const source = document.createElement("source");
                source.src = post.video_url;
                media.append(source);
            } else {
                media.src = post.image_url;
                media.alt = "Ulashilgan post rasmi";
                media.loading = "lazy";
            }
            card.append(media);
        }

        const copy = document.createElement("div");
        copy.className = "shared-post-copy";
        if (post.title) {
            const title = document.createElement("h3");
            title.textContent = post.title;
            copy.append(title);
        }
        const description = document.createElement("p");
        description.textContent = post.description;
        copy.append(description);
        card.append(copy);

        const stats = document.createElement("div");
        stats.className = "shared-post-stats";
        const likes = document.createElement("span");
        likes.textContent = `♥ ${post.likes_count}`;
        const commentsCount = document.createElement("span");
        commentsCount.textContent = `Izohlar ${post.comments_count}`;
        stats.append(likes, commentsCount);
        card.append(stats);

        if (post.comments.length) {
            const comments = document.createElement("div");
            comments.className = "shared-post-comments";
            post.comments.forEach((comment) => {
                const line = document.createElement("p");
                const commentAuthor = document.createElement("a");
                commentAuthor.href = comment.author_url;
                commentAuthor.textContent = `@${comment.username}`;
                line.append(commentAuthor, document.createTextNode(` ${comment.text}`));
                comments.append(line);
            });
            card.append(comments);
        }
        const openPost = document.createElement("a");
        openPost.className = "shared-post-open";
        openPost.href = post.post_url;
        openPost.textContent = "Postni ko‘rish ↗";
        card.append(openPost);
        return card;
    };

    const appendMessage = (message) => {
        const emptyState = messages.querySelector("[data-chat-start-state]");
        if (emptyState) emptyState.remove();

        const article = document.createElement("article");
        article.className = "chat-message";
        if (message.sender_id === currentUserId) article.classList.add("is-mine");

        if (message.sender_id !== currentUserId) {
            const avatar = chat.querySelector(".chat-header-avatar img");
            const messageAvatar = document.createElement("span");
            messageAvatar.className = "chat-message-avatar";
            if (avatar) {
                const image = document.createElement("img");
                image.src = avatar.src;
                image.alt = "";
                messageAvatar.append(image);
            } else {
                messageAvatar.textContent =
                    chat.querySelector(".chat-header-user a").textContent.slice(0, 1).toUpperCase();
            }
            article.append(messageAvatar);
        }

        const content = document.createElement("div");
        content.className = "chat-message-content";
        if (message.shared_post) {
            content.append(createSharedPostCard(message.shared_post));
        } else if (message.is_audio) {
            const audio = document.createElement("audio");
            audio.className = "chat-voice-message";
            audio.preload = "metadata";
            audio.src = message.audio_url;
            content.append(audio);
            setupVoicePlayer(audio);
        } else if (message.media_type) {
            const media = message.media_type.startsWith("video/")
                ? document.createElement("video")
                : document.createElement("img");
            media.className = message.media_type.startsWith("video/")
                ? "chat-attachment-video"
                : "chat-attachment-image";
            media.src = message.media_url;
            if (media instanceof HTMLVideoElement) {
                media.controls = true;
                media.preload = "metadata";
                media.playsInline = true;
            } else {
                media.alt = "Yuborilgan rasm";
                media.loading = "lazy";
            }
            content.append(media);
        } else {
            const text = document.createElement("p");
            text.textContent = message.text;
            content.append(text);
        }
        const time = document.createElement("time");
        time.dateTime = message.created_at_iso;
        time.textContent = message.created_at;
        const meta = document.createElement("div");
        meta.className = "chat-message-meta";
        const edited = document.createElement("span");
        edited.dataset.messageEdited = "";
        edited.textContent = "Tahrirlangan";
        edited.hidden = true;
        meta.append(time, edited);
        content.append(meta);
        if (message.sender_id === currentUserId) {
            content.append(createMessageActions(
                message.is_audio || Boolean(message.media_type) || Boolean(message.shared_post)
            ));
        }
        article.dataset.messageId = message.id;
        article.append(content);
        messages.append(article);
        scrollToLatest();
    };

    messages.querySelectorAll(".chat-voice-message").forEach(setupVoicePlayer);
    ["😀", "😂", "🥰", "😍", "😊", "😉", "😎", "🤔", "😭", "😮",
        "😡", "👍", "👎", "👏", "🙏", "❤️", "🔥", "🎉", "✅", "👋"]
        .forEach((emoji) => {
            const button = document.createElement("button");
            button.type = "button";
            button.dataset.emoji = emoji;
            button.setAttribute("aria-label", emoji);
            button.textContent = emoji;
            emojiPicker.append(button);
        });

    emojiToggle.addEventListener("click", () => {
        emojiPicker.hidden = !emojiPicker.hidden;
    });
    emojiPicker.addEventListener("click", (event) => {
        const button = event.target.closest("[data-emoji]");
        if (!button) return;
        const start = input.selectionStart;
        const end = input.selectionEnd;
        input.setRangeText(button.dataset.emoji, start, end, "end");
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.focus();
        emojiPicker.hidden = true;
    });
    mediaPick.addEventListener("click", () => mediaInput.click());
    mediaInput.addEventListener("change", () => selectMedia(mediaInput.files[0]));
    mediaSend.addEventListener("click", uploadSelectedMedia);
    mediaCancel.addEventListener("click", clearMediaPreview);

    const closeEditor = (article) => {
        const editor = article.querySelector("[data-message-editor]");
        if (!editor) return;
        editor.remove();
        article.querySelector(".chat-message-content > p").hidden = false;
        article.querySelector(".chat-message-meta").hidden = false;
        article.querySelector(".chat-message-actions").hidden = false;
    };

    const startEditing = (article) => {
        if (article.querySelector("[data-message-editor]")) return;
        const content = article.querySelector(".chat-message-content");
        const text = content.querySelector(":scope > p");
        const actions = content.querySelector(".chat-message-actions");
        const editor = document.createElement("div");
        editor.className = "chat-message-editor";
        editor.dataset.messageEditor = "";
        const textarea = document.createElement("textarea");
        textarea.maxLength = 4000;
        textarea.value = text.textContent;
        const save = document.createElement("button");
        save.type = "button";
        save.dataset.messageEditorSave = "";
        save.textContent = "Saqlash";
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.dataset.messageEditorCancel = "";
        cancel.textContent = "Bekor qilish";
        editor.append(textarea, save, cancel);
        text.hidden = true;
        content.querySelector(".chat-message-meta").hidden = true;
        actions.hidden = true;
        content.append(editor);
        textarea.focus();
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    };

    messages.addEventListener("click", (event) => {
        const target = event.target.closest("button");
        if (!target) return;
        const article = target.closest("[data-message-id]");
        if (!article) return;

        if (target.dataset.messageAction === "edit") {
            startEditing(article);
            return;
        }
        if (target.dataset.messageAction === "delete") {
            if (socket.readyState === WebSocket.OPEN) {
                showError();
                socket.send(JSON.stringify({
                    type: "delete_message",
                    message_id: article.dataset.messageId,
                }));
            }
            return;
        }
        if (target.dataset.messageEditorCancel !== undefined) {
            closeEditor(article);
            return;
        }
        if (target.dataset.messageEditorSave !== undefined) {
            const textarea = article.querySelector("[data-message-editor] textarea");
            const text = textarea.value.trim();
            if (!text || socket.readyState !== WebSocket.OPEN) return;
            showError();
            target.disabled = true;
            socket.send(JSON.stringify({
                type: "edit_message",
                message_id: article.dataset.messageId,
                text,
            }));
        }
    });

    const setPresence = (isOnline) => {
        const status = chat.querySelector("[data-chat-presence-text]");
        const activeDot = chat.querySelector("[data-active-peer-presence]");
        status.textContent = isOnline ? "online" : "offline";
        status.classList.toggle("is-online", isOnline);
        activeDot.classList.toggle("is-online", isOnline);
        chat.querySelectorAll("[data-peer-presence]").forEach((dot) => {
            if (dot.dataset.peerPresence === chat.dataset.peerId) {
                dot.classList.toggle("is-online", isOnline);
            }
        });
    };

    const sendTyping = (typing) => {
        if (socket.readyState !== WebSocket.OPEN || isTyping === typing) return;
        isTyping = typing;
        socket.send(JSON.stringify({ type: "typing", typing }));
    };

    socket.addEventListener("open", () => {
        showError();
        heartbeatTimer = window.setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: "heartbeat" }));
            }
        }, 20000);
        input.disabled = false;
        recordButton.disabled = false;
        mediaSend.disabled = !selectedMedia;
        input.focus();
    });

    socket.addEventListener("message", (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch {
            showError("Chat serveridan noto‘g‘ri javob olindi.");
            return;
        }

        if (data.type === "message") {
            appendMessage(data.message);
            updateConversationPreview(data.message, activeConversationId);
            updateUnreadCount(activeConversationId, data.unread_count);
            typingIndicator.hidden = true;
            return;
        }
        if (data.type === "message_edited") {
            const article = [...messages.querySelectorAll("[data-message-id]")]
                .find((item) => item.dataset.messageId === data.message.id);
            if (article) {
                closeEditor(article);
                article.querySelector(".chat-message-content > p").textContent = data.message.text;
                article.querySelector("[data-message-edited]").hidden = false;
            }
            return;
        }
        if (data.type === "message_deleted") {
            const article = [...messages.querySelectorAll("[data-message-id]")]
                .find((item) => item.dataset.messageId === data.message_id);
            article?.remove();
            if (!messages.querySelector(".chat-message")) {
                const emptyState = document.createElement("div");
                emptyState.className = "chat-start-state";
                emptyState.dataset.chatStartState = "";
                emptyState.textContent = "Suhbatni boshlash uchun birinchi xabaringizni yuboring.";
                messages.append(emptyState);
            }
            return;
        }
        if (data.type === "presence") {
            setPresence(data.online);
            return;
        }
        if (data.type === "typing") {
            typingIndicator.hidden = !data.typing;
            if (data.typing) scrollToLatest();
            return;
        }
        if (data.type === "inbox") {
            ensureConversationItem(data);
            updateConversationPreview(data.message, data.conversation_id);
            updateUnreadCount(data.conversation_id, data.unread_count);
            return;
        }
        if (data.type === "inbox_update") {
            updateConversationPreview(data.message, data.conversation_id);
            return;
        }
        if (data.type === "error") {
            messages.querySelectorAll("[data-message-editor]").forEach((editor) => {
                closeEditor(editor.closest("[data-message-id]"));
            });
            showError(data.message);
        }
    });

    socket.addEventListener("close", (event) => {
        window.clearInterval(heartbeatTimer);
        input.disabled = true;
        sendButton.disabled = true;
        recordButton.disabled = true;
        mediaSend.disabled = true;
        stopRecording();
        if (event.code === 4401 || event.code === 4403) {
            showError("Chatga kirish uchun qayta kiring.");
        } else if (event.code !== 1000) {
            showError("Chatga ulanish uzildi. Sahifani yangilang va qayta urinib ko‘ring.");
        }
    });

    socket.addEventListener("error", () => {
        showError("Chat serveriga ulanib bo‘lmadi.");
    });

    input.addEventListener("input", () => {
        sendButton.disabled = input.value.trim().length === 0;
        sendTyping(input.value.trim().length > 0);
        window.clearTimeout(typingStopTimer);
        if (input.value.trim()) {
            typingStopTimer = window.setTimeout(() => sendTyping(false), 1200);
        }
    });

    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    recordButton.addEventListener("click", () => {
        if (audioUploading || requestingMicrophone) return;
        if (recorder?.state === "recording") {
            stopRecording();
        } else {
            startRecording();
        }
    });

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        const text = input.value.trim();
        if (!text || socket.readyState !== WebSocket.OPEN) return;
        showError();
        socket.send(JSON.stringify({ type: "message", text }));
        input.value = "";
        input.style.height = "";
        sendButton.disabled = true;
        sendTyping(false);
    });

    input.addEventListener("input", () => {
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight, 130)}px`;
    });

    scrollToLatest();
})();
