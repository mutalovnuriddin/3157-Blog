(() => {
    let followModalOpener = null;

    const requestOptions = (form) => ({
        method: form.method || "POST",
        headers: {
            "X-Requested-With": "XMLHttpRequest",
            Accept: "application/json",
        },
        body: new FormData(form),
        credentials: "same-origin",
    });

    const setError = (form, message = "") => {
        const error = form.querySelector("[data-ajax-error]");
        if (!error) return;
        error.textContent = message;
        error.hidden = !message;
    };

    const firstValidationError = (errors) => {
        for (const fieldErrors of Object.values(errors || {})) {
            if (fieldErrors.length) return fieldErrors[0].message;
        }
        return "Amalni bajarib bo‘lmadi. Qaytadan urinib ko‘ring.";
    };

    const sendForm = async (form) => {
        const response = await fetch(form.action, requestOptions(form));
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) {
            throw new Error("Serverdan kutilmagan javob keldi. Sahifani yangilang.");
        }
        const data = await response.json();
        if (!response.ok) {
            throw new Error(firstValidationError(data.errors));
        }
        return data;
    };

    const updateLike = (form, data) => {
        const social = form.closest("[data-post-social]");
        const button = form.querySelector("[data-like-button]");
        const heart = button.querySelector(".social-heart");
        const label = button.querySelector(".social-action-label");

        button.classList.toggle("is-liked", data.liked);
        button.setAttribute("aria-pressed", String(data.liked));
        heart.textContent = data.liked ? "♥" : "♡";
        label.textContent = data.liked ? "Yoqdi" : "Yoqtirish";
        social.querySelector("[data-like-count]").textContent = data.likes_count;
    };

    const appendComment = (form, data) => {
        const social = form.closest("[data-post-social]");
        const list = social.querySelector(".post-comments");
        const comment = data.comment;
        const article = document.createElement("article");
        article.className = "post-comment";

        const avatar = document.createElement("a");
        avatar.className = "comment-avatar";
        avatar.href = comment.profile_url;
        avatar.setAttribute("aria-label", `${comment.username} profiliga o‘tish`);
        if (comment.avatar_url) {
            const image = document.createElement("img");
            image.src = comment.avatar_url;
            image.alt = "";
            avatar.append(image);
        } else {
            avatar.textContent = comment.initial;
        }

        const content = document.createElement("div");
        content.className = "comment-content";
        const meta = document.createElement("div");
        meta.className = "comment-meta";
        const author = document.createElement("a");
        author.href = comment.profile_url;
        author.textContent = comment.username;
        const time = document.createElement("time");
        time.dateTime = comment.created_at_iso;
        time.textContent = comment.created_at;
        meta.append(author, time);

        const text = document.createElement("p");
        text.textContent = comment.text;
        content.append(meta, text);
        article.append(avatar, content);
        list.append(article);
        social.querySelector("[data-comment-count]").textContent = data.comments_count;
        list.scrollTop = list.scrollHeight;
        form.reset();
    };

    const updateFollow = (form, data) => {
        const button = form.querySelector("[data-follow-button]");
        const followersCount = document.querySelector("[data-followers-count]");
        button.textContent = data.following
            ? (button.dataset.followingText || "Kuzatishni to‘xtatish")
            : (button.dataset.followText || "Kuzatish");
        button.classList.toggle("button-quiet", data.following);
        button.classList.toggle("button-primary", !data.following);
        button.classList.toggle("button-following", data.following);
        if (followersCount) followersCount.textContent = data.followers_count;
        const followersTabCount = document.querySelector("[data-followers-tab-count]");
        if (followersTabCount) followersTabCount.textContent = data.followers_count;
    };

    document.addEventListener("submit", async (event) => {
        const form = event.target.closest("form[data-ajax-action]");
        if (!form) return;
        event.preventDefault();
        setError(form);

        const button = form.querySelector('button[type="submit"]');
        if (button) button.disabled = true;
        form.setAttribute("aria-busy", "true");

        try {
            const data = await sendForm(form);
            switch (form.dataset.ajaxAction) {
                case "like":
                    updateLike(form, data);
                    break;
                case "comment":
                    appendComment(form, data);
                    break;
                case "follow":
                    updateFollow(form, data);
                    break;
            }
        } catch (error) {
            setError(form, error.message);
        } finally {
            if (button) button.disabled = false;
            form.removeAttribute("aria-busy");
        }
    });

    document.addEventListener("click", (event) => {
        const openButton = event.target.closest("[data-open-follow-modal]");
        if (openButton) {
            const modal = document.querySelector("[data-connections-modal]");
            const tabName = openButton.dataset.openFollowModal;
            const tab = modal.querySelector(`[data-follow-tab="${tabName}"]`);
            followModalOpener = openButton;
            modal.hidden = false;
            document.body.classList.add("modal-open");
            setActiveFollowTab(modal, tab);
            modal.querySelector("[data-close-follow-modal]").focus();
            return;
        }

        const closeButton = event.target.closest("[data-close-follow-modal]");
        if (closeButton) {
            closeFollowModal(closeButton.closest("[data-connections-modal]"));
            return;
        }

        const tab = event.target.closest("[data-follow-tab]");
        if (tab) {
            setActiveFollowTab(tab.closest("[data-connections-modal]"), tab);
            return;
        }

        const button = event.target.closest("[data-comment-toggle]");
        if (!button) return;

        const social = button.closest("[data-post-social]");
        const form = social.querySelector(".comment-form");
        const list = social.querySelector("[data-comments-list]");
        const isExpanded = button.getAttribute("aria-expanded") === "true";
        button.setAttribute("aria-expanded", String(!isExpanded));
        form.hidden = isExpanded;
        list.hidden = isExpanded;
        button.querySelector(".social-action-label").textContent =
            isExpanded ? "Izoh yozish" : "Yopish";
        if (!isExpanded) form.querySelector("textarea").focus();
    });

    const setActiveFollowTab = (modal, activeTab) => {
        modal.querySelectorAll("[data-follow-tab]").forEach((tab) => {
            const isActive = tab === activeTab;
            tab.classList.toggle("is-active", isActive);
            tab.setAttribute("aria-selected", String(isActive));
            tab.tabIndex = isActive ? 0 : -1;
        });
        modal.querySelectorAll("[data-follow-panel]").forEach((panel) => {
            panel.hidden = panel.dataset.followPanel !== activeTab.dataset.followTab;
        });
    };

    const closeFollowModal = (modal) => {
        if (!modal || modal.hidden) return;
        modal.hidden = true;
        document.body.classList.remove("modal-open");
        followModalOpener?.focus();
        followModalOpener = null;
    };

    document.addEventListener("keydown", (event) => {
        const modal = document.querySelector("[data-connections-modal]:not([hidden])");
        if (!modal) return;
        if (event.key === "Escape") {
            closeFollowModal(modal);
            return;
        }
        if (event.key !== "Tab") return;

        const focusable = [...modal.querySelectorAll(
            '.connections-close, [role="tab"]:not([disabled]), .connection-user[href]'
        )].filter((element) => !element.closest("[hidden]"));
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });
})();






const liveSearchForm = document.querySelector(".feed-search");
const searchInput = document.getElementById("userSearchInput");
const resultsBox = document.getElementById("liveSearchResults");
let debounceTimer;
let activeSearch;

const setSearchExpanded = (expanded) => {
    resultsBox.hidden = !expanded;
    searchInput.setAttribute("aria-expanded", String(expanded));
};

const renderSearchResults = (results) => {
    resultsBox.replaceChildren();
    if (!results.length) {
        const empty = document.createElement("p");
        empty.className = "live-search-empty";
        empty.textContent = "Foydalanuvchi topilmadi";
        resultsBox.append(empty);
        setSearchExpanded(true);
        return;
    }

    for (const user of results) {
        const item = document.createElement("a");
        item.className = "live-search-item";
        item.href = user.profile_url;
        item.setAttribute("role", "option");

        const avatar = document.createElement("span");
        avatar.className = "search-user-avatar";
        if (user.avatar_url) {
            const image = document.createElement("img");
            image.src = user.avatar_url;
            image.alt = "";
            avatar.append(image);
        } else {
            avatar.textContent = user.username.slice(0, 1).toUpperCase();
        }

        const copy = document.createElement("span");
        copy.className = "search-user-copy";
        const username = document.createElement("strong");
        username.textContent = `@${user.username}`;
        copy.append(username);
        if (user.full_name) {
            const fullName = document.createElement("span");
            fullName.textContent = user.full_name;
            copy.append(fullName);
        }
        item.append(avatar, copy);
        resultsBox.append(item);
    }
    setSearchExpanded(true);
};

if (liveSearchForm && searchInput && resultsBox) {
    searchInput.addEventListener("input", () => {
        const query = searchInput.value.trim();
        clearTimeout(debounceTimer);
        if (activeSearch) activeSearch.abort();

        if (query.length < 2) {
            resultsBox.replaceChildren();
            setSearchExpanded(false);
            return;
        }

        debounceTimer = setTimeout(async () => {
            activeSearch = new AbortController();
            const searchUrl = new URL(liveSearchForm.action, window.location.href);
            searchUrl.searchParams.set("q", query);
            try {
                const response = await fetch(searchUrl, {
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        Accept: "application/json",
                    },
                    credentials: "same-origin",
                    signal: activeSearch.signal,
                });
                if (!response.ok) throw new Error("Qidiruvni bajarib bo‘lmadi.");
                const data = await response.json();
                renderSearchResults(data.results);
            } catch (error) {
                if (error.name === "AbortError") return;
                const message = document.createElement("p");
                message.className = "live-search-empty";
                message.textContent = error.message;
                resultsBox.replaceChildren(message);
                setSearchExpanded(true);
            }
        }, 250);
    });

    document.addEventListener("click", (event) => {
        if (!liveSearchForm.contains(event.target)) setSearchExpanded(false);
    });

    searchInput.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setSearchExpanded(false);
    });
}

(() => {
    const modal = document.querySelector("[data-share-modal]");
    if (!modal) return;

    const search = modal.querySelector("[data-share-search]");
    const users = modal.querySelector("[data-share-users]");
    const followingHeading = modal.querySelector(".share-post-section-title");
    const results = modal.querySelector("[data-share-search-results]");
    const sendButton = modal.querySelector("[data-share-send]");
    const error = modal.querySelector("[data-share-error]");
    const selectionCount = modal.querySelector("[data-share-selection-count]");
    const selected = new Set();
    let activePostId = "";
    let searchTimer;
    let searchController;
    let opener;

    const updateSelection = () => {
        modal.querySelectorAll("[data-share-recipient]").forEach((checkbox) => {
            checkbox.checked = selected.has(checkbox.value);
        });
        sendButton.disabled = selected.size === 0;
        selectionCount.textContent = selected.size
            ? `${selected.size} ta foydalanuvchi tanlandi`
            : "Foydalanuvchi tanlanmadi";
    };

    const createUserRow = (user) => {
        const label = document.createElement("label");
        label.className = "share-post-user";
        label.dataset.shareUser = "";
        label.dataset.userId = user.id;
        label.dataset.username = user.username.toLowerCase();

        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = user.id;
        checkbox.dataset.shareRecipient = "";

        const avatar = document.createElement("span");
        avatar.className = "share-post-avatar";
        if (user.avatar_url) {
            const image = document.createElement("img");
            image.src = user.avatar_url;
            image.alt = "";
            avatar.append(image);
        } else {
            avatar.textContent = user.username.slice(0, 1).toUpperCase();
        }

        const username = document.createElement("span");
        username.className = "share-post-user-name";
        username.textContent = `@${user.username}`;
        label.append(checkbox, avatar, username);
        checkbox.checked = selected.has(user.id);
        return label;
    };

    const closeModal = () => {
        modal.hidden = true;
        document.body.classList.remove("share-modal-open");
        selected.clear();
        search.value = "";
        results.replaceChildren();
        results.hidden = true;
        error.hidden = true;
        updateSelection();
        opener?.focus();
        opener = null;
    };

    document.addEventListener("click", (event) => {
        const shareButton = event.target.closest("[data-share-post]");
        if (shareButton) {
            opener = shareButton;
            activePostId = shareButton.dataset.sharePost;
            selected.clear();
            modal.querySelectorAll("[data-share-recipient]").forEach((checkbox) => {
                checkbox.checked = false;
            });
            search.value = "";
            users.hidden = false;
            followingHeading.hidden = false;
            users.querySelectorAll("[data-share-user]").forEach((user) => {
                user.hidden = false;
            });
            results.replaceChildren();
            results.hidden = true;
            error.hidden = true;
            updateSelection();
            modal.hidden = false;
            document.body.classList.add("share-modal-open");
            search.focus();
            return;
        }
        if (event.target.closest("[data-share-close]")) {
            closeModal();
        }
    });

    modal.addEventListener("change", (event) => {
        const checkbox = event.target.closest("[data-share-recipient]");
        if (!checkbox) return;
        if (checkbox.checked) selected.add(checkbox.value);
        else selected.delete(checkbox.value);
        if (selected.size > 20) {
            selected.delete(checkbox.value);
            checkbox.checked = false;
            error.textContent = "Bir vaqtda 20 tagacha foydalanuvchiga yuborish mumkin.";
            error.hidden = false;
        } else {
            error.hidden = true;
        }
        updateSelection();
    });

    search.addEventListener("input", () => {
        const query = search.value.trim();
        clearTimeout(searchTimer);
        searchController?.abort();
        users.querySelectorAll("[data-share-user]").forEach((user) => {
            user.hidden = Boolean(query) && !user.dataset.username.includes(query.toLowerCase());
        });
        followingHeading.hidden = Boolean(query);
        users.hidden = Boolean(query);
        if (query.length < 2) {
            results.replaceChildren();
            results.hidden = true;
            return;
        }

        searchTimer = window.setTimeout(async () => {
            searchController = new AbortController();
            const url = new URL(modal.dataset.userSearchEndpoint, window.location.href);
            url.searchParams.set("q", query);
            try {
                const response = await fetch(url, {
                    headers: { Accept: "application/json" },
                    credentials: "same-origin",
                    signal: searchController.signal,
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "Qidiruvni bajarib bo‘lmadi.");
                results.replaceChildren();
                data.users.forEach((user) => results.append(createUserRow(user)));
                if (!data.users.length) {
                    const empty = document.createElement("p");
                    empty.className = "share-post-empty";
                    empty.textContent = "Foydalanuvchi topilmadi.";
                    results.append(empty);
                }
                results.hidden = false;
            } catch (requestError) {
                if (requestError.name === "AbortError") return;
                error.textContent = requestError.message;
                error.hidden = false;
            }
        }, 250);
    });

    sendButton.addEventListener("click", async () => {
        if (!selected.size || !activePostId) return;
        sendButton.disabled = true;
        error.hidden = true;
        const body = new FormData(modal.querySelector("[data-share-csrf]"));
        body.set("post_id", activePostId);
        selected.forEach((id) => body.append("recipient_ids", id));
        try {
            const response = await fetch(modal.dataset.shareEndpoint, {
                method: "POST",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    Accept: "application/json",
                },
                body,
                credentials: "same-origin",
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Postni yuborib bo‘lmadi.");
            const sentCount = data.sent_count;
            const shareButton = opener;
            closeModal();
            shareButton?.setAttribute(
                "aria-label",
                `Post ${sentCount} ta foydalanuvchiga yuborildi`
            );
        } catch (sendError) {
            error.textContent = sendError.message;
            error.hidden = false;
            sendButton.disabled = selected.size === 0;
        }
    });

    document.addEventListener("keydown", (event) => {
        if (!modal.hidden && event.key === "Escape") closeModal();
    });
})();