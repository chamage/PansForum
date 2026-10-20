/* Progressive enhancement & real-time live sync for PANS Agora (strictly CSP-safe, zero inline JS). */
(function () {
  "use strict";

  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const csrfToken = csrfMeta ? csrfMeta.getAttribute("content") : "";
  const isAuth = document.body.dataset.auth === "1";

  const drawer = document.getElementById("quick-drawer");
  const backdrop = document.getElementById("quick-backdrop");
  let activeDrawerUrl = null;
  let lastTriggerEl = null;

  // --------------------------------------------------------------------------
  // Toast helper for live notifications
  // --------------------------------------------------------------------------
  function showToast(text, level) {
    const container = document.getElementById("toast-container");
    if (!container || !text) return;
    const div = document.createElement("div");
    div.className = "toast toast--" + (level || "info");
    const span = document.createElement("span");
    span.textContent = text;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "toast__close";
    btn.setAttribute("data-dismiss", "");
    btn.setAttribute("aria-label", "Dismiss");
    btn.textContent = "×";
    div.appendChild(span);
    div.appendChild(btn);
    container.appendChild(div);
    window.setTimeout(() => {
      if (div.parentNode) div.remove();
    }, 6000);
  }

  // --------------------------------------------------------------------------
  // Quick-View Slide-Over Drawer
  // --------------------------------------------------------------------------
  async function openQuickView(url, triggerEl) {
    if (!drawer || !backdrop) {
      window.location.href = url;
      return;
    }
    activeDrawerUrl = url;
    if (triggerEl) lastTriggerEl = triggerEl;

    document.querySelectorAll(".thread-card.is-selected").forEach((c) => c.classList.remove("is-selected"));
    const parentCard = triggerEl ? triggerEl.closest(".thread-card") : null;
    if (parentCard) parentCard.classList.add("is-selected");

    backdrop.hidden = false;
    drawer.hidden = false;
    drawer.innerHTML =
      '<div class="drawer__bar">' +
      '  <div class="drawer__bar-left">' +
      '    <button type="button" class="btn btn--ghost btn--sm" data-drawer-close>✕ Close <span class="drawer__kbd">Esc</span></button>' +
      "  </div>" +
      '  <div class="drawer__bar-right">' +
      '    <a class="btn btn--primary btn--sm" href="' + encodeURI(url) + '">Open full thread ↗</a>' +
      "  </div>" +
      "</div>" +
      '<div class="drawer__scroll"><div class="card drawer__loading">Loading thread…</div></div>';

    // Force reflow so the slide-in and blur transitions play smoothly
    void drawer.offsetWidth;
    document.body.classList.add("has-drawer-open");
    backdrop.classList.add("is-open");
    drawer.classList.add("is-open");

    try {
      const resp = await fetch(url, {
        headers: { "X-Quick-View": "1", "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!resp.ok) throw new Error("Failed to load preview");
      const html = await resp.text();
      if (activeDrawerUrl === url) {
        drawer.innerHTML = html;
        const closeBtn = drawer.querySelector("[data-drawer-close]");
        if (closeBtn) closeBtn.focus();
      }
    } catch (_) {
      window.location.href = url;
    }
  }

  function closeQuickView() {
    if (!drawer || drawer.hidden) return;
    activeDrawerUrl = null;
    document.body.classList.remove("has-drawer-open");
    backdrop.classList.remove("is-open");
    drawer.classList.remove("is-open");
    document.querySelectorAll(".thread-card.is-selected").forEach((c) => c.classList.remove("is-selected"));

    window.setTimeout(() => {
      if (!activeDrawerUrl) {
        drawer.hidden = true;
        backdrop.hidden = true;
        drawer.innerHTML = "";
      }
    }, 240);

    if (lastTriggerEl && typeof lastTriggerEl.focus === "function") {
      lastTriggerEl.focus();
    }
  }

  // --------------------------------------------------------------------------
  // Global Keyboard Handler (Esc for drawer, Enter-to-send for chat)
  // --------------------------------------------------------------------------
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawer && !drawer.hidden) {
      e.preventDefault();
      closeQuickView();
      return;
    }

    if (e.key === "Enter" && !e.shiftKey && e.target && e.target.matches(".chat-form textarea")) {
      e.preventDefault();
      const form = e.target.closest("form");
      if (!form) return;
      const mediaInput = form.querySelector("[data-chat-media-input]");
      const hasFile = Boolean(mediaInput && mediaInput.files && mediaInput.files.length > 0);
      if (e.target.value.trim() || hasFile) {
        form.requestSubmit();
      }
    }
  });

  function clearChatMediaPreview(form) {
    const scope = form || document;
    const fileInput = scope.querySelector("[data-chat-media-input]");
    if (fileInput) fileInput.value = "";
    const bar = document.getElementById("chat-attachment-bar");
    if (bar) bar.hidden = true;
    const thumb = document.getElementById("chat-attachment-thumb");
    if (thumb) thumb.removeAttribute("src");
    const nameEl = document.getElementById("chat-attachment-name");
    if (nameEl) nameEl.textContent = "";
  }

  document.addEventListener("change", (e) => {
    if (e.target && e.target.matches("[data-chat-media-input]")) {
      const file = e.target.files && e.target.files[0];
      const bar = document.getElementById("chat-attachment-bar");
      const thumb = document.getElementById("chat-attachment-thumb");
      const nameEl = document.getElementById("chat-attachment-name");
      if (!file || !bar) {
        clearChatMediaPreview();
        return;
      }
      if (thumb) thumb.src = URL.createObjectURL(file);
      if (nameEl) nameEl.textContent = file.name;
      bar.hidden = false;
    }
  });

  // --------------------------------------------------------------------------
  // Global Click Handler (Toasts, Dropdowns, Quick-View, Chat GIFs)
  // --------------------------------------------------------------------------
  document.addEventListener("click", (e) => {
    // 1. Dismissible toast notifications
    const closeBtn = e.target.closest("[data-dismiss]");
    if (closeBtn) {
      const toast = closeBtn.closest(".toast");
      if (toast) toast.remove();
      return;
    }

    // 2. Clear selected chat media attachment
    const clearMediaBtn = e.target.closest("[data-clear-chat-media]");
    if (clearMediaBtn) {
      e.preventDefault();
      clearChatMediaPreview(clearMediaBtn.closest("form"));
      return;
    }

    // 3. Open inline edit form on a chat message bubble
    const editOpenBtn = e.target.closest("[data-chat-edit-open]");
    if (editOpenBtn) {
      e.preventDefault();
      const bubble = editOpenBtn.closest(".chat-bubble");
      if (bubble) {
        const editForm = bubble.querySelector("[data-chat-edit-form]");
        const contentEl = bubble.querySelector("[data-msg-content]");
        if (editForm) {
          editForm.hidden = false;
          if (contentEl) contentEl.hidden = true;
          const ta = editForm.querySelector("textarea");
          if (ta) {
            ta.focus();
            ta.setSelectionRange(ta.value.length, ta.value.length);
          }
        }
      }
      return;
    }

    // 4. Cancel inline edit form on a chat message bubble
    const editCancelBtn = e.target.closest("[data-chat-edit-cancel]");
    if (editCancelBtn) {
      e.preventDefault();
      const bubble = editCancelBtn.closest(".chat-bubble");
      if (bubble) {
        const editForm = bubble.querySelector("[data-chat-edit-form]");
        const contentEl = bubble.querySelector("[data-msg-content]");
        if (editForm) editForm.hidden = true;
        if (contentEl) contentEl.hidden = false;
      }
      return;
    }

    // 5. Close quick-view drawer
    if (e.target.closest("[data-drawer-close]")) {
      e.preventDefault();
      closeQuickView();
      return;
    }

    // 6. Sort comments inside the quick-view drawer
    const sortLink = e.target.closest("[data-drawer-sort]");
    if (sortLink && drawer && drawer.contains(sortLink)) {
      if (!e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && e.button === 0) {
        e.preventDefault();
        openQuickView(sortLink.getAttribute("data-drawer-sort"), lastTriggerEl);
        return;
      }
    }

    // 7. Open thread quick-view when clicking a thread title/comment pill or card body
    if (!e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && e.button === 0) {
      const qvLink = e.target.closest("[data-quick-view]");
      if (qvLink) {
        e.preventDefault();
        openQuickView(qvLink.getAttribute("data-quick-view"), qvLink);
        return;
      }

      // Clicking anywhere on the thread card (outside other links/buttons/forms)
      const qvCard = e.target.closest("[data-quick-view-card]");
      if (qvCard && !e.target.closest("a, button, form, input, details")) {
        openQuickView(qvCard.getAttribute("data-quick-view-card"), qvCard.querySelector("[data-quick-view]") || qvCard);
        return;
      }
    }

    // 8. Close open account <details> menu when clicking outside
    document.querySelectorAll("details.menu[open]").forEach((menu) => {
      if (!menu.contains(e.target)) menu.removeAttribute("open");
    });
  });

  // --------------------------------------------------------------------------
  // Real-Time Live Polling Engine & Discord-Style Typing Indicator
  // --------------------------------------------------------------------------
  let pollInFlight = false;
  let pendingForcePoll = false;
  let prevPendingFriends = null;
  let prevUnreadMessages = null;
  let lastChatTypedAt = 0;
  let lastTypingPingSentAt = 0;
  let typingIdleTimer = null;

  function sendTypingPing(partner, isTyping) {
    if (!partner || !isAuth) return;
    lastTypingPingSentAt = isTyping ? Date.now() : 0;
    const body = new URLSearchParams();
    body.set("typing", isTyping ? "1" : "0");
    fetch("/messages/" + encodeURIComponent(partner) + "/typing/", {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: body.toString(),
      credentials: "same-origin",
    }).catch(() => {});
  }

  document.addEventListener("input", (e) => {
    if (!e.target || !e.target.matches(".chat-form textarea")) return;
    const chatShell = document.querySelector("[data-chat-shell]");
    const partner = chatShell ? chatShell.dataset.chatPartner || chatShell.dataset.activePartner || "" : "";
    if (!partner) return;

    if (typingIdleTimer) {
      window.clearTimeout(typingIdleTimer);
      typingIdleTimer = null;
    }

    if (e.target.value.trim().length > 0) {
      lastChatTypedAt = Date.now();
      if (Date.now() - lastTypingPingSentAt > 1800) {
        sendTypingPing(partner, true);
      }
      typingIdleTimer = window.setTimeout(() => {
        lastChatTypedAt = 0;
        sendTypingPing(partner, false);
      }, 3500);
    } else {
      lastChatTypedAt = 0;
      sendTypingPing(partner, false);
    }
  });

  function setBadgeCount(selector, count) {
    document.querySelectorAll(selector).forEach((badge) => {
      const n = Number(count) || 0;
      badge.textContent = n > 0 ? String(n) : "";
      badge.hidden = n <= 0;
    });
  }

  function pluralize(count, singular, plural) {
    return count === 1 ? singular : plural;
  }

  function appendChatMessagesHtml(html) {
    const chatLog = document.getElementById("chat-log");
    if (!chatLog || !html) return;
    chatLog.querySelectorAll("[data-chat-empty], #chat-empty-state").forEach((el) => el.remove());

    const temp = document.createElement("div");
    temp.innerHTML = html;
    let appended = false;
    Array.from(temp.children).forEach((node) => {
      const sepId = node.dataset && node.dataset.sepFor;
      if (sepId) {
        if (!chatLog.querySelector(`[data-sep-for="${sepId}"]`) && !chatLog.querySelector(`[data-msg-id="${sepId}"]`)) {
          chatLog.appendChild(node);
        }
        return;
      }
      const msgId = node.dataset && node.dataset.msgId;
      if (msgId && !chatLog.querySelector(`[data-msg-id="${msgId}"]`)) {
        chatLog.appendChild(node);
        appended = true;
      }
    });
    if (appended) {
      chatLog.scrollTop = chatLog.scrollHeight;
    }
  }

  function replaceChatBubbleHtml(msgId, html, force) {
    const chatLog = document.getElementById("chat-log");
    if (!chatLog || !msgId || !html) return;
    const existing = chatLog.querySelector(`.chat-bubble[data-msg-id="${msgId}"]`);
    if (!existing) return;
    if (!force) {
      const openEdit = existing.querySelector("[data-chat-edit-form]:not([hidden])");
      if (openEdit) return;
    }
    const temp = document.createElement("div");
    temp.innerHTML = html;
    const newBubble = temp.querySelector(`.chat-bubble[data-msg-id="${msgId}"]`) || temp.firstElementChild;
    if (newBubble) {
      existing.replaceWith(newBubble);
    }
  }

  function expireOldChatEditButtons() {
    const nowSec = Math.floor(Date.now() / 1000);
    document.querySelectorAll("#chat-log .chat-bubble[data-msg-ts]").forEach((bubble) => {
      const ts = parseInt(bubble.dataset.msgTs, 10) || 0;
      if (ts > 0 && nowSec - ts > 900) {
        bubble.querySelectorAll("[data-chat-edit-open]").forEach((btn) => btn.remove());
      }
    });
  }

  async function pollLiveState(forceUpdate) {
    if (pollInFlight) {
      if (forceUpdate) pendingForcePoll = true;
      return;
    }
    if (!forceUpdate && document.hidden) return;
    pollInFlight = true;

    try {
      const params = new URLSearchParams();

      // 1. Chat state
      const chatShell = document.querySelector("[data-chat-shell]");
      if (chatShell) {
        expireOldChatEditButtons();
        params.set("chat_shell", "1");
        params.set("chat_tab", chatShell.dataset.chatTab || "inbox");
        const partner = chatShell.dataset.chatPartner || chatShell.dataset.activePartner || "";
        if (partner) {
          params.set("chat_partner", partner);
          let maxMsgId = 0;
          document.querySelectorAll("#chat-log [data-msg-id]").forEach((el) => {
            const id = parseInt(el.dataset.msgId, 10);
            if (id > maxMsgId) maxMsgId = id;
          });
          params.set("last_msg_id", String(maxMsgId));
          params.set("chat_msg_sig", forceUpdate ? "force" : chatShell.dataset.msgSig || "init");
          if (Date.now() - lastChatTypedAt < 3200) {
            params.set("typing", "1");
          }
        }
      }

      // 2. Friends page state
      const friendsRegion = document.getElementById("friends-live-region");
      if (friendsRegion) {
        params.set("friends_page", "1");
      }

      // 3. Profile page friend actions state
      const profileActions = document.querySelector("[data-profile-actions]");
      if (profileActions && profileActions.dataset.profileUsername) {
        params.set("profile_user", profileActions.dataset.profileUsername);
      }

      // 4. Visible thread IDs (for live score & comment count sync)
      const threadIdSet = new Set();
      document.querySelectorAll("[data-thread-id]").forEach((el) => {
        if (el.dataset.threadId) threadIdSet.add(el.dataset.threadId);
      });
      if (threadIdSet.size > 0) {
        params.set("thread_ids", Array.from(threadIdSet).slice(0, 40).join(","));
      }

      // 5. Feed list (for live new threads appearing at top of feed)
      const feedList = document.getElementById("feed-list");
      if (feedList && (feedList.dataset.page || "1") === "1") {
        params.set("feed", feedList.dataset.feed || "all");
        params.set("page", "1");
        if (feedList.dataset.community) {
          params.set("community", feedList.dataset.community);
        }
        let maxThreadId = 0;
        feedList.querySelectorAll(".thread-card[data-thread-id]").forEach((card) => {
          const tid = parseInt(card.dataset.threadId, 10);
          if (tid > maxThreadId) maxThreadId = tid;
        });
        params.set("max_thread_id", String(maxThreadId));
      }

      // 6. Open thread comments (either in drawer if open, or full thread page)
      let activeCommentsEl = null;
      if (drawer && !drawer.hidden) {
        activeCommentsEl = drawer.querySelector("[data-live-comments]");
      }
      if (!activeCommentsEl) {
        activeCommentsEl = document.querySelector("[data-live-comments]");
      }
      if (activeCommentsEl && activeCommentsEl.dataset.threadId) {
        params.set("open_thread_id", activeCommentsEl.dataset.threadId);
        params.set("csort", activeCommentsEl.dataset.csort || "best");
        params.set("comments_sig", forceUpdate ? "force" : activeCommentsEl.dataset.commentsSig || "init");
      }

      const resp = await fetch("/live/poll/?" + params.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!resp.ok) return;
      const data = await resp.json();

      // A. Update navbar badges & show subtle toast on new incoming items
      if (typeof data.pending_friends === "number") {
        if (prevPendingFriends !== null && data.pending_friends > prevPendingFriends && !friendsRegion) {
          showToast("You received a new friend request!", "info");
        }
        prevPendingFriends = data.pending_friends;
        setBadgeCount("[data-live-friends-badge]", data.pending_friends);
      }

      if (typeof data.unread_messages === "number") {
        if (prevUnreadMessages !== null && data.unread_messages > prevUnreadMessages && !chatShell) {
          showToast("New direct message received.", "info");
        }
        prevUnreadMessages = data.unread_messages;
        setBadgeCount("[data-live-messages-badge]", data.unread_messages);
      }

      // B. Update chat sidebar & active conversation
      if (typeof data.chat_sidebar_html === "string") {
        const sidebar = document.getElementById("chat-sidebar");
        if (sidebar && sidebar.innerHTML !== data.chat_sidebar_html) {
          sidebar.innerHTML = data.chat_sidebar_html;
        }
      }

      if (data.chat && chatShell) {
        const friendBadge = document.getElementById("chat-friend-badge");
        if (friendBadge) {
          friendBadge.hidden = !data.chat.is_friends;
        }

        const typingEl = document.getElementById("chat-typing-indicator");
        if (typingEl) {
          typingEl.hidden = !data.chat.partner_typing;
        }

        if (data.chat.new_messages_html) {
          appendChatMessagesHtml(data.chat.new_messages_html);
        }

        if (data.chat.updated_bubbles) {
          Object.keys(data.chat.updated_bubbles).forEach((mid) => {
            replaceChatBubbleHtml(mid, data.chat.updated_bubbles[mid], forceUpdate);
          });
        }
        if (data.chat.msg_sig) {
          chatShell.dataset.msgSig = data.chat.msg_sig;
        }

        if (data.chat.conv_state && chatShell.dataset.convState !== data.chat.conv_state) {
          const hadPrevState = Boolean(chatShell.dataset.convState);
          chatShell.dataset.convState = data.chat.conv_state;
          const bannerSlot = document.getElementById("chat-banner-slot");
          if (bannerSlot && typeof data.chat.banner_html === "string") {
            bannerSlot.innerHTML = data.chat.banner_html;
          }
          const footSlot = document.getElementById("chat-foot-slot");
          if (footSlot && typeof data.chat.foot_html === "string") {
            const existingForm = footSlot.querySelector("[data-chat-send-form]");
            const newHasForm = data.chat.foot_html.indexOf("data-chat-send-form") !== -1;
            if (existingForm && newHasForm) {
              // Preserve the active textarea and user's typing; only sync the submit button text if needed
              const tempFoot = document.createElement("div");
              tempFoot.innerHTML = data.chat.foot_html;
              const newBtn = tempFoot.querySelector("button[type='submit']");
              const curBtn = existingForm.querySelector("button[type='submit']");
              if (newBtn && curBtn) curBtn.textContent = newBtn.textContent;
            } else if (hadPrevState || forceUpdate || !existingForm) {
              footSlot.innerHTML = data.chat.foot_html;
            }
          }
        }
      }

      // C. Update friends page region
      if (friendsRegion && typeof data.friends_html === "string") {
        if (friendsRegion.innerHTML !== data.friends_html) {
          friendsRegion.innerHTML = data.friends_html;
        }
      }

      // D. Update profile friend actions & friend counter
      if (profileActions && typeof data.profile_actions_html === "string") {
        if (profileActions.innerHTML !== data.profile_actions_html) {
          profileActions.innerHTML = data.profile_actions_html;
        }
        if (typeof data.profile_friends_count === "number") {
          const statEl = document.querySelector("[data-profile-friends-stat]");
          if (statEl) {
            statEl.textContent =
              data.profile_friends_count + " " + pluralize(data.profile_friends_count, "friend", "friends");
          }
        }
      }

      // E. Update visible thread scores & comment counts
      if (data.threads) {
        Object.keys(data.threads).forEach((tid) => {
          const info = data.threads[tid];
          document.querySelectorAll(`form[data-vote-form][action="/t/${tid}/vote/"] [data-score]`).forEach((el) => {
            el.textContent = info.score;
          });
          document.querySelectorAll(`[data-thread-comment-count="${tid}"]`).forEach((el) => {
            el.textContent = info.comment_count + " " + pluralize(info.comment_count, "comment", "comments");
          });
        });
      }

      // F. Prepend new threads to feed
      if (feedList && data.new_threads_html) {
        const temp = document.createElement("div");
        temp.innerHTML = data.new_threads_html;
        const emptyFeed = document.getElementById("feed-empty");
        if (emptyFeed) emptyFeed.remove();

        const firstUnpinned =
          feedList.querySelector(".thread-card:not(.thread-card--pinned)") || feedList.firstElementChild;
        Array.from(temp.children).forEach((card) => {
          const tid = card.dataset && card.dataset.threadId;
          if (tid && !feedList.querySelector(`.thread-card[data-thread-id="${tid}"]`)) {
            if (firstUnpinned) {
              feedList.insertBefore(card, firstUnpinned);
            } else {
              feedList.appendChild(card);
            }
          }
        });
      }

      // G. Update open thread comments
      if (activeCommentsEl && data.comments_sig) {
        if (typeof data.comments_html === "string") {
          const activeEl = document.activeElement;
          const isTypingInComments =
            !forceUpdate &&
            activeEl &&
            activeEl.tagName === "TEXTAREA" &&
            activeCommentsEl.contains(activeEl) &&
            activeEl.value.trim().length > 0;

          if (!isTypingInComments) {
            activeCommentsEl.innerHTML = data.comments_html;
            activeCommentsEl.dataset.commentsSig = data.comments_sig;
          }
        } else {
          activeCommentsEl.dataset.commentsSig = data.comments_sig;
        }
      }
    } catch (_) {
      // Ignore transient network errors during background poll
    } finally {
      pollInFlight = false;
      if (pendingForcePoll) {
        pendingForcePoll = false;
        pollLiveState(true);
      }
    }
  }

  // Initialize badge baseline counts from DOM
  const initFriendsBadge = document.querySelector("[data-live-friends-badge]");
  if (initFriendsBadge) {
    prevPendingFriends = parseInt(initFriendsBadge.textContent, 10) || 0;
  }
  const initMsgsBadge = document.querySelector("[data-live-messages-badge]");
  if (initMsgsBadge) {
    prevUnreadMessages = parseInt(initMsgsBadge.textContent, 10) || 0;
  }

  // Poll every 1.5s when in chat for snappy typing indicators & messages, or 2.5s elsewhere
  const pollIntervalMs = document.querySelector("[data-chat-shell]") ? 1500 : 2500;
  window.setInterval(() => pollLiveState(false), pollIntervalMs);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) pollLiveState(false);
  });

  // --------------------------------------------------------------------------
  // Live Form Submissions (Chat, Friends, Comments, Voting)
  // --------------------------------------------------------------------------
  document.addEventListener("submit", async (e) => {
    const form = e.target;
    const msg = form.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) {
      e.preventDefault();
      return;
    }

    // 1. Live Chat Message Send (Text or Media Attachment)
    if (form.hasAttribute("data-chat-send-form")) {
      e.preventDefault();
      const textarea = form.querySelector("textarea[name='body']");
      const mediaInput = form.querySelector("[data-chat-media-input]");

      const hasText = Boolean(textarea && textarea.value.trim());
      const hasFile = Boolean(mediaInput && mediaInput.files && mediaInput.files.length > 0);
      if (!hasText && !hasFile) return;

      const formData = new FormData(form);
      const savedText = textarea ? textarea.value : "";
      if (textarea) textarea.value = "";
      clearChatMediaPreview(form);

      lastChatTypedAt = 0;
      if (typingIdleTimer) {
        window.clearTimeout(typingIdleTimer);
        typingIdleTimer = null;
      }

      try {
        const resp = await fetch(form.action, {
          method: "POST",
          headers: {
            "X-CSRFToken": csrfToken,
            "X-Live-Action": "1",
            "X-Requested-With": "XMLHttpRequest",
          },
          body: formData,
          credentials: "same-origin",
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) {
          if (textarea) textarea.value = savedText;
          if (data && (data.toast || data.error)) showToast(data.toast || data.error, "error");
          return;
        }
        if (data.message_html) {
          appendChatMessagesHtml(data.message_html);
        }
        await pollLiveState(true);
        const newTextarea = document.querySelector(".chat-form textarea");
        if (newTextarea) newTextarea.focus();
      } catch (_) {
        if (textarea) textarea.value = savedText;
        form.submit();
      }
      return;
    }

    // 1b. Live Chat Message Edit (within 15-minute window) or Delete
    if (form.hasAttribute("data-chat-edit-form") || form.hasAttribute("data-chat-delete-form")) {
      e.preventDefault();
      const body = new URLSearchParams(new FormData(form));
      try {
        const resp = await fetch(form.action, {
          method: "POST",
          headers: {
            "X-CSRFToken": csrfToken,
            "X-Live-Action": "1",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: body.toString(),
          credentials: "same-origin",
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) {
          if (data && (data.toast || data.error)) showToast(data.toast || data.error, "error");
          return;
        }
        if (data.msg_id && data.bubble_html) {
          replaceChatBubbleHtml(String(data.msg_id), data.bubble_html, true);
        }
        await pollLiveState(true);
      } catch (_) {
        form.submit();
      }
      return;
    }

    // 2. Live Chat Request Accept / Ignore
    if (form.hasAttribute("data-chat-action")) {
      e.preventDefault();
      const body = new URLSearchParams(new FormData(form));
      try {
        const resp = await fetch(form.action, {
          method: "POST",
          headers: {
            "X-CSRFToken": csrfToken,
            "X-Live-Action": "1",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: body.toString(),
          credentials: "same-origin",
        });
        const data = await resp.json();
        if (data && data.redirect) {
          window.location.href = data.redirect;
          return;
        }
        await pollLiveState(true);
      } catch (_) {
        form.submit();
      }
      return;
    }

    // 3. Live Friend Actions (Send, Accept, Decline, Cancel, Unfriend)
    if (form.hasAttribute("data-friend-action")) {
      e.preventDefault();
      const body = new URLSearchParams(new FormData(form));
      try {
        const resp = await fetch(form.action, {
          method: "POST",
          headers: {
            "X-CSRFToken": csrfToken,
            "X-Live-Action": "1",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: body.toString(),
          credentials: "same-origin",
        });
        if (resp.ok) {
          await pollLiveState(true);
          return;
        }
      } catch (_) {
        form.submit();
      }
      return;
    }

    // 4. Live Comment Submission (both in quick-view drawer and on full thread page)
    if (form.classList.contains("comment-form")) {
      e.preventDefault();
      const body = new URLSearchParams(new FormData(form));
      const inDrawer = Boolean(drawer && drawer.contains(form));
      try {
        const headers = {
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "XMLHttpRequest",
          "Content-Type": "application/x-www-form-urlencoded",
        };
        if (inDrawer) {
          headers["X-Quick-View"] = "1";
        } else {
          headers["X-Live-Action"] = "1";
        }
        const resp = await fetch(form.action, {
          method: "POST",
          headers: headers,
          body: body.toString(),
          credentials: "same-origin",
        });
        if (resp.ok) {
          if (inDrawer) {
            drawer.innerHTML = await resp.text();
            await pollLiveState(false);
          } else {
            const textarea = form.querySelector("textarea[name='body']");
            if (textarea) textarea.value = "";
            const details = form.closest("details.reply");
            if (details) details.removeAttribute("open");
            await pollLiveState(true);
          }
          return;
        }
      } catch (_) {
        form.submit();
      }
      return;
    }

    // 5. Live Comment Delete
    if (form.hasAttribute("data-comment-delete")) {
      e.preventDefault();
      const body = new URLSearchParams(new FormData(form));
      try {
        const resp = await fetch(form.action, {
          method: "POST",
          headers: {
            "X-CSRFToken": csrfToken,
            "X-Live-Action": "1",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: body.toString(),
          credentials: "same-origin",
        });
        if (resp.ok) {
          await pollLiveState(true);
          return;
        }
      } catch (_) {
        form.submit();
      }
      return;
    }
  });

  // --------------------------------------------------------------------------
  // AJAX voting with graceful fallback & card score sync
  // --------------------------------------------------------------------------
  document.addEventListener("submit", async (e) => {
    const form = e.target.closest("[data-vote-form]");
    if (!form) return;
    if (!isAuth) return; // let the form submit normally and redirect to login

    const submitter = e.submitter;
    if (!submitter || !submitter.value) return;
    e.preventDefault();

    const body = new URLSearchParams();
    body.set("value", submitter.value);

    try {
      const resp = await fetch(form.action, {
        method: "POST",
        headers: {
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "XMLHttpRequest",
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: body.toString(),
        credentials: "same-origin",
      });
      if (!resp.ok) return;
      const data = await resp.json();

      // Update all matching vote forms (e.g. both inside the drawer and on the feed card behind it)
      document.querySelectorAll(`form[data-vote-form][action="${form.getAttribute("action")}"]`).forEach((vf) => {
        const scoreEl = vf.querySelector("[data-score]");
        if (scoreEl) scoreEl.textContent = data.score;

        const upBtn = vf.querySelector(".vote__btn--up");
        const downBtn = vf.querySelector(".vote__btn--down");
        if (upBtn) {
          upBtn.classList.toggle("is-active", data.vote === 1);
          upBtn.setAttribute("aria-pressed", data.vote === 1 ? "true" : "false");
        }
        if (downBtn) {
          downBtn.classList.toggle("is-active", data.vote === -1);
          downBtn.setAttribute("aria-pressed", data.vote === -1 ? "true" : "false");
        }
      });
    } catch (_) {
      form.submit();
    }
  });

  // --------------------------------------------------------------------------
  // Live image preview on profile settings page
  // --------------------------------------------------------------------------
  document.querySelectorAll("input[type='file'][data-preview]").forEach((input) => {
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      const target = document.getElementById(input.dataset.preview);
      if (!file || !target) return;
      const url = URL.createObjectURL(file);
      target.src = url;
      target.classList.remove("is-empty");
      const fallback = target.parentElement.querySelector("[data-avatar-fallback]");
      if (fallback) fallback.style.display = "none";
    });
  });

  const bannerBox = document.querySelector("[data-banner-preview]");
  if (bannerBox) {
    document.querySelectorAll('input[name="banner_theme"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        bannerBox.className = "profile-preview__banner banner--" + radio.value;
      });
    });
  }

  // --------------------------------------------------------------------------
  // Initial scroll to bottom on chat page load
  // --------------------------------------------------------------------------
  const chatLog = document.getElementById("chat-log");
  if (chatLog) {
    chatLog.scrollTop = chatLog.scrollHeight;
  }
})();
