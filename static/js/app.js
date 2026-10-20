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

  const chatDock = document.getElementById("chat-dock");
  const chatDockPanel = document.getElementById("chat-dock-panel");
  const chatDockLauncher = document.getElementById("chat-dock-launcher");

  // --------------------------------------------------------------------------
  // Floating Quick-Chat Dock (Messenger / Reddit style popup)
  // --------------------------------------------------------------------------
  function toDockUrl(href) {
    if (!href) return "/messages/dock/";
    if (href.indexOf("/messages/dock/") === 0) return href;
    if (href.indexOf("/messages/?") === 0) {
      return "/messages/dock/" + href.slice("/messages/".length);
    }
    if (href === "/messages/" || href === "/messages") {
      return "/messages/dock/";
    }
    if (href.indexOf("/messages/") === 0) {
      return "/messages/dock/" + href.slice("/messages/".length);
    }
    return href;
  }

  async function openChatDock(url, skipFocus) {
    if (!chatDock || !chatDockPanel) return;
    const dockUrl = toDockUrl(url || sessionStorage.getItem("pans_dock_url") || "/messages/dock/");
    chatDockPanel.hidden = false;
    if (chatDockLauncher) chatDockLauncher.setAttribute("aria-expanded", "true");
    try {
      sessionStorage.setItem("pans_dock_open", "1");
      sessionStorage.setItem("pans_dock_url", dockUrl);
    } catch (_) {}

    if (!chatDockPanel.innerHTML.trim()) {
      chatDockPanel.innerHTML =
        '<div class="chat-dock__inner"><header class="chat-dock__head"><span class="chat-dock__title">💬 Quick Chat</span>' +
        '<button type="button" class="btn btn--ghost btn--sm" data-dock-close aria-label="Minimize chat">—</button></header>' +
        '<div class="chat-dock__body"><div class="chat-list__empty muted small">Loading chat…</div></div></div>';
    }

    try {
      const resp = await fetch(dockUrl, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!resp.ok) return;
      chatDockPanel.innerHTML = await resp.text();
      const logEl = chatDockPanel.querySelector("#chat-log");
      if (logEl) logEl.scrollTop = logEl.scrollHeight;
      if (!skipFocus) {
        const ta = chatDockPanel.querySelector(".chat-form textarea");
        if (ta) ta.focus();
      }
      pollLiveState(false);
    } catch (_) {}
  }

  function closeChatDock() {
    if (!chatDockPanel) return;
    chatDockPanel.hidden = true;
    chatDockPanel.innerHTML = "";
    if (chatDockLauncher) chatDockLauncher.setAttribute("aria-expanded", "false");
    try {
      sessionStorage.setItem("pans_dock_open", "0");
    } catch (_) {}
  }

  if (chatDock && chatDockPanel) {
    try {
      if (sessionStorage.getItem("pans_dock_open") === "1") {
        openChatDock(sessionStorage.getItem("pans_dock_url") || "/messages/dock/", true);
      }
    } catch (_) {}
  }

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

    // 4b. Floating Quick-Chat Dock controls & internal navigation
    const dockToggleBtn = e.target.closest("[data-dock-toggle]");
    if (dockToggleBtn) {
      e.preventDefault();
      if (chatDockPanel && !chatDockPanel.hidden) {
        closeChatDock();
      } else {
        openChatDock();
      }
      return;
    }

    if (e.target.closest("[data-dock-close]")) {
      e.preventDefault();
      closeChatDock();
      return;
    }

    const dockUrlBtn = e.target.closest("[data-dock-url]");
    if (dockUrlBtn) {
      e.preventDefault();
      openChatDock(dockUrlBtn.getAttribute("data-dock-url"));
      return;
    }

    if (chatDockPanel && chatDockPanel.contains(e.target)) {
      const dockChatLink = e.target.closest('a[href^="/messages/"]');
      if (dockChatLink && !dockChatLink.hasAttribute("data-dock-full")) {
        if (!e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && e.button === 0) {
          e.preventDefault();
          openChatDock(dockChatLink.getAttribute("href"));
          return;
        }
      }
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

      // 3. Profile page friend actions & stats state
      const profileActions = document.querySelector("[data-profile-actions]");
      const profileUsername = profileActions
        ? profileActions.dataset.profileUsername || profileActions.dataset.profileActions || ""
        : "";
      const profileFriendsGrid = document.getElementById("profile-friends-grid");
      if (profileUsername) {
        params.set("profile_user", profileUsername);
        if (profileFriendsGrid) {
          params.set("profile_friends_grid", "1");
        }
      }

      // 4. Visible thread IDs (for live score, comment count, title, excerpt & deletion sync)
      const threadIdSet = new Set();
      document.querySelectorAll("[data-thread-id], [data-thread-card]").forEach((el) => {
        const tid = el.dataset.threadId || el.dataset.threadCard;
        if (tid) threadIdSet.add(tid);
      });
      if (threadIdSet.size > 0) {
        params.set("thread_ids", Array.from(threadIdSet).slice(0, 40).join(","));
      }

      // 4b. Visible community slugs (for live member counts in cards & sidebars)
      const commSlugSet = new Set();
      document.querySelectorAll("[data-community-member-count], [data-community-count]").forEach((el) => {
        const s = el.dataset.communityMemberCount || el.dataset.communityCount;
        if (s) commSlugSet.add(s);
      });
      if (commSlugSet.size > 0) {
        params.set("community_slugs", Array.from(commSlugSet).slice(0, 30).join(","));
      }

      // 4c. Communities directory grid (/communities/)
      const communitiesGrid = document.getElementById("communities-live-grid");
      if (communitiesGrid) {
        params.set("communities_grid", "1");
        params.set("communities_sig", forceUpdate ? "force" : communitiesGrid.dataset.communitiesSig || "init");
      }

      // 4d. Community Management Dashboard (/c/<slug>/manage/)
      const manageShell = document.getElementById("community-manage-shell");
      if (manageShell && manageShell.dataset.manageCommunity) {
        params.set("manage_community", manageShell.dataset.manageCommunity);
      }

      // 5. Feed list (for live new threads appearing at top of home, community, or profile feed)
      const feedList = document.getElementById("feed-list");
      if (feedList) {
        const feedPage = feedList.dataset.livePage || feedList.dataset.page || "1";
        const feedType = feedList.dataset.liveFeed || feedList.dataset.feed || "all";
        const feedComm = feedList.dataset.liveCommunity || feedList.dataset.community || "";
        const feedProf = feedList.dataset.liveProfile || "";
        if (feedComm) {
          params.set("community", feedComm);
        }
        if (feedProf) {
          params.set("feed_profile", feedProf);
        }
        if (feedPage === "1") {
          params.set("feed", feedType);
          params.set("page", "1");
          let maxThreadId = 0;
          feedList.querySelectorAll(".thread-card[data-thread-id], .thread-card[data-thread-card]").forEach((card) => {
            const tid = parseInt(card.dataset.threadId || card.dataset.threadCard, 10);
            if (tid > maxThreadId) maxThreadId = tid;
          });
          params.set("max_thread_id", String(maxThreadId));
        }
      }

      // 6. Open thread comments (either in drawer if open, or full thread page)
      let activeCommentsEl = null;
      if (drawer && !drawer.hidden) {
        activeCommentsEl = drawer.querySelector("[data-live-comments]");
      }
      if (!activeCommentsEl) {
        activeCommentsEl = document.querySelector("[data-live-comments]");
      }
      const openThreadId = activeCommentsEl
        ? activeCommentsEl.dataset.liveComments || activeCommentsEl.dataset.threadId || ""
        : "";
      if (activeCommentsEl && openThreadId) {
        params.set("open_thread_id", openThreadId);
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

      // D. Update profile friend actions, counters & friends grid
      if (profileActions && typeof data.profile_actions_html === "string") {
        if (profileActions.innerHTML !== data.profile_actions_html) {
          profileActions.innerHTML = data.profile_actions_html;
        }
        if (typeof data.profile_friends_count === "number") {
          const statEl = document.querySelector("[data-profile-friends-stat]");
          if (statEl) {
            statEl.innerHTML =
              "<strong>" +
              data.profile_friends_count +
              "</strong> " +
              pluralize(data.profile_friends_count, "friend", "friends");
          }
        }
        if (typeof data.profile_threads_count === "number") {
          const tStatEl = document.querySelector("[data-profile-threads-stat]");
          if (tStatEl) {
            tStatEl.innerHTML =
              "<strong>" +
              data.profile_threads_count +
              "</strong> " +
              pluralize(data.profile_threads_count, "thread", "threads");
          }
        }
        if (typeof data.profile_comments_count === "number") {
          const cStatEl = document.querySelector("[data-profile-comments-stat]");
          if (cStatEl) {
            cStatEl.innerHTML =
              "<strong>" +
              data.profile_comments_count +
              "</strong> " +
              pluralize(data.profile_comments_count, "comment", "comments");
          }
        }
        if (profileFriendsGrid && typeof data.profile_friends_grid_html === "string") {
          if (profileFriendsGrid.innerHTML !== data.profile_friends_grid_html) {
            profileFriendsGrid.innerHTML = data.profile_friends_grid_html;
          }
        }
      }

      // E. Update visible thread scores, comment counts, titles, excerpts, pin/lock tags & remove deleted threads
      if (data.threads) {
        Object.keys(data.threads).forEach((tid) => {
          const info = data.threads[tid];
          document.querySelectorAll(`form[data-vote-form][action="/t/${tid}/vote/"] [data-score]`).forEach((el) => {
            el.textContent = info.score;
          });
          document.querySelectorAll(`[data-thread-comment-count="${tid}"]`).forEach((el) => {
            el.textContent = info.comment_count + " " + pluralize(info.comment_count, "comment", "comments");
          });
          if (info.title) {
            document.querySelectorAll(`[data-thread-title="${tid}"]`).forEach((el) => {
              if (el.textContent !== info.title) el.textContent = info.title;
            });
          }
          if (typeof info.excerpt === "string") {
            document.querySelectorAll(`[data-thread-excerpt="${tid}"]`).forEach((el) => {
              el.textContent = info.excerpt;
              el.hidden = !info.excerpt;
            });
          }
          if (typeof info.is_edited === "boolean") {
            document.querySelectorAll(`[data-thread-edited="${tid}"]`).forEach((el) => {
              el.hidden = !info.is_edited;
            });
          }
          if (typeof info.is_pinned === "boolean") {
            document.querySelectorAll(`[data-thread-pin-tag="${tid}"]`).forEach((el) => {
              el.hidden = !info.is_pinned;
            });
            document.querySelectorAll(`[data-thread-pin-btn="${tid}"]`).forEach((el) => {
              el.textContent = info.is_pinned ? "Unpin" : "Pin";
            });
            document
              .querySelectorAll(`.thread-card[data-thread-id="${tid}"], .thread-card[data-thread-card="${tid}"]`)
              .forEach((card) => {
                if (card.querySelector(`[data-thread-pin-tag="${tid}"]`)) {
                  card.classList.toggle("is-pinned", info.is_pinned);
                }
              });
          }
          if (typeof info.is_locked === "boolean") {
            document.querySelectorAll(`[data-thread-lock-tag="${tid}"]`).forEach((el) => {
              el.hidden = !info.is_locked;
            });
            document.querySelectorAll(`[data-thread-lock-btn="${tid}"]`).forEach((el) => {
              el.textContent = info.is_locked ? "Unlock" : "Lock";
            });
          }
        });
      }

      if (Array.isArray(data.deleted_thread_ids)) {
        data.deleted_thread_ids.forEach((tid) => {
          document
            .querySelectorAll(`.thread-card[data-thread-id="${tid}"], .thread-card[data-thread-card="${tid}"]`)
            .forEach((card) => card.remove());
        });
      }

      // E2. Update community member counts across cards & sidebars
      if (data.communities_counts) {
        Object.keys(data.communities_counts).forEach((slug) => {
          const mc = data.communities_counts[slug];
          document.querySelectorAll(`[data-community-member-count="${slug}"]`).forEach((el) => {
            el.textContent = mc + " " + pluralize(mc, "member", "members");
          });
          document.querySelectorAll(`[data-community-count="${slug}"]`).forEach((el) => {
            el.textContent = String(mc);
          });
        });
      }

      // E3. Update /communities/ directory grid
      if (communitiesGrid && data.communities_sig) {
        communitiesGrid.dataset.communitiesSig = data.communities_sig;
        if (typeof data.communities_grid_html === "string") {
          communitiesGrid.innerHTML = data.communities_grid_html;
        }
      }

      // E4. Update active community detail page
      if (data.community_info && data.community_info.slug) {
        if (data.community_info.is_banned) {
          window.location.reload();
          return;
        }
        const slug = data.community_info.slug;
        const mc = data.community_info.member_count;
        document.querySelectorAll(`[data-community-member-count="${slug}"]`).forEach((el) => {
          el.textContent = mc + " " + pluralize(mc, "member", "members");
        });
        if (typeof data.community_info.description === "string") {
          document.querySelectorAll(`[data-community-description="${slug}"]`).forEach((el) => {
            if (el.textContent !== data.community_info.description) {
              el.textContent = data.community_info.description;
            }
          });
        }
        if (typeof data.community_info.open_reports_count === "number") {
          setBadgeCount("[data-community-reports-badge]", data.community_info.open_reports_count);
        }
        const compSlot = document.getElementById("community-composer-slot");
        if (compSlot) {
          const newGhostState = data.community_info.is_ghosted ? "1" : "0";
          if (compSlot.dataset.ghostState && compSlot.dataset.ghostState !== newGhostState) {
            window.location.reload();
            return;
          }
        }
      }

      // E5. Update Community Management Dashboard (/c/<slug>/manage/)
      if (data.manage && manageShell) {
        const mSlug = data.manage.slug;
        if (typeof data.manage.member_count === "number") {
          document.querySelectorAll(`[data-community-member-count="${mSlug}"]`).forEach((el) => {
            el.textContent =
              data.manage.member_count + " " + pluralize(data.manage.member_count, "member", "members");
          });
        }
        if (typeof data.manage.mod_count === "number") {
          document.querySelectorAll(`[data-community-mod-count="${mSlug}"]`).forEach((el) => {
            el.textContent =
              data.manage.mod_count + " " + pluralize(data.manage.mod_count, "moderator", "moderators");
          });
        }
        const sancRegion = document.getElementById("mod-sanctions-region");
        if (sancRegion && typeof data.manage.sanctions_html === "string" && sancRegion.innerHTML !== data.manage.sanctions_html) {
          sancRegion.innerHTML = data.manage.sanctions_html;
        }
        const repRegion = document.getElementById("mod-reports-region");
        if (repRegion && typeof data.manage.reports_html === "string" && repRegion.innerHTML !== data.manage.reports_html) {
          repRegion.innerHTML = data.manage.reports_html;
        }
        const teamRegion = document.getElementById("mod-team-region");
        if (teamRegion && typeof data.manage.team_html === "string" && teamRegion.innerHTML !== data.manage.team_html) {
          teamRegion.innerHTML = data.manage.team_html;
        }
      }

      // F. Prepend new threads to feed (home, community, or profile)
      if (feedList && data.new_threads_html) {
        const temp = document.createElement("div");
        temp.innerHTML = data.new_threads_html;
        feedList.querySelectorAll("[data-feed-empty], #feed-empty").forEach((el) => el.remove());

        const firstUnpinned =
          feedList.querySelector(".thread-card:not(.is-pinned):not(.thread-card--pinned)") || feedList.firstElementChild;
        Array.from(temp.children).forEach((card) => {
          const tid = card.dataset && (card.dataset.threadId || card.dataset.threadCard);
          if (
            tid &&
            !feedList.querySelector(`.thread-card[data-thread-id="${tid}"], .thread-card[data-thread-card="${tid}"]`)
          ) {
            if (firstUnpinned) {
              feedList.insertBefore(card, firstUnpinned);
            } else {
              feedList.appendChild(card);
            }
          }
        });
      }

      // G. Update open thread state & comments
      if (data.open_thread_deleted || data.open_thread_banned) {
        if (drawer && !drawer.hidden) {
          closeDrawer();
          if (data.open_thread_deleted) showToast("This thread was deleted.", "info");
        } else {
          window.location.reload();
        }
        return;
      }

      if (data.open_thread_meta) {
        const tm = data.open_thread_meta;
        document.querySelectorAll(`[data-thread-body="${tm.id}"]`).forEach((el) => {
          el.hidden = !tm.has_body;
          if (tm.has_body && el.innerHTML !== tm.body_html) {
            el.innerHTML = tm.body_html;
          }
        });
        const boxSlot = document.getElementById("thread-comment-box-slot");
        if (boxSlot && boxSlot.dataset.boxState && boxSlot.dataset.boxState !== tm.box_state) {
          boxSlot.dataset.boxState = tm.box_state;
          if (tm.box_state === "ghost") {
            boxSlot.innerHTML = `<div class="alert alert--info">👻 You are in read-only mode in <strong>c/${tm.community_slug}</strong>. You can read posts and comments, but cannot reply or vote.</div>`;
          } else if (tm.box_state === "locked") {
            boxSlot.innerHTML = `<div class="alert alert--info">🔒 This thread is locked. You can read it, but new comments are turned off.</div>`;
          } else if (drawer && !drawer.hidden && activeDrawerUrl) {
            openDrawer(activeDrawerUrl);
          } else {
            window.location.reload();
          }
        }
      }

      if (data.comment_scores) {
        Object.keys(data.comment_scores).forEach((cid) => {
          const sc = data.comment_scores[cid];
          document.querySelectorAll(`form[data-vote-form][action="/comment/${cid}/vote/"] [data-score]`).forEach((el) => {
            el.textContent = sc;
          });
          document.querySelectorAll(`[data-comment-points="${cid}"]`).forEach((el) => {
            el.textContent = sc + " " + pluralize(sc, "point", "points");
          });
        });
      }

      if (activeCommentsEl && data.comments_sig) {
        if (typeof data.comments_html === "string") {
          const activeEl = document.activeElement;
          const hasOpenReply = Boolean(activeCommentsEl.querySelector("details.reply[open]"));
          const isTypingInComments =
            !forceUpdate &&
            (hasOpenReply ||
              (activeEl &&
                activeEl.tagName === "TEXTAREA" &&
                activeCommentsEl.contains(activeEl) &&
                activeEl.value.trim().length > 0));

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

  // Poll every 1.6s for snappy typing indicators, dock chat & feed updates
  window.setInterval(() => pollLiveState(false), 1600);
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
          if (chatDockPanel && chatDockPanel.contains(form)) {
            openChatDock(data.redirect);
          } else {
            window.location.href = data.redirect;
          }
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

    // 6. Live Community Join / Leave
    if (form.hasAttribute("data-community-join-form")) {
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
          if (data && data.error) showToast(data.error, "error");
          return;
        }
        if (data.slug && data.join_html) {
          document.querySelectorAll(`[data-join-slot="${data.slug}"]`).forEach((slot) => {
            slot.innerHTML = data.join_html;
          });
        }
        if (data.slug && typeof data.member_count === "number") {
          document.querySelectorAll(`[data-community-member-count="${data.slug}"]`).forEach((el) => {
            el.textContent = data.member_count + " " + pluralize(data.member_count, "member", "members");
          });
          document.querySelectorAll(`[data-community-count="${data.slug}"]`).forEach((el) => {
            el.textContent = String(data.member_count);
          });
        }
        await pollLiveState(true);
      } catch (_) {
        form.submit();
      }
      return;
    }

    // 7. Live Moderator Actions (Pin, Lock, Ban, Ghost, Un-ghost, Unban, Mod Team, Reports)
    if (form.hasAttribute("data-mod-action")) {
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
          if (data && (data.error || data.toast)) showToast(data.error || data.toast, "error");
          return;
        }
        if (data.redirect) {
          window.location.href = data.redirect;
          return;
        }
        form.querySelectorAll("input[type='text']").forEach((inp) => {
          inp.value = "";
        });
        if (data.toast) {
          showToast(data.toast, "info");
        }
        await pollLiveState(true);
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
