/* ==========================================================================
   The Time Parallax — reader behaviour
   Vanilla JS, no dependencies. Everything degrades gracefully: with
   JavaScript off the site is still a fully readable, navigable book.
   ========================================================================== */

(function () {
  'use strict';

  var SETTINGS_KEY = 'dwfe:settings';
  var PROGRESS_KEY = 'dwfe:progress';
  var root = document.documentElement;
  var live = document.getElementById('live-region');

  var DEFAULTS = {
    theme: 'system',
    font: 'serif',
    width: 'medium',
    align: 'start',
    fontSize: 1.15,
    lineHeight: 1.75,
    letterSpacing: 0,
    wordSpacing: 0,
    paragraphSpacing: 1.1,
    focus: false,
    calm: false
  };

  var THEME_ORDER = ['system', 'light', 'dark', 'sepia', 'contrast'];

  /* --- tiny storage helpers ---------------------------------------------- */

  function readStore(key, fallback) {
    try {
      var raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (err) {
      return fallback;
    }
  }

  function writeStore(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (err) { /* private mode, quota — not worth interrupting reading */ }
  }

  function announce(message) {
    if (!live || !message) return;
    live.textContent = '';
    window.setTimeout(function () { live.textContent = message; }, 40);
  }

  /* --- settings ----------------------------------------------------------- */

  var settings = Object.assign({}, DEFAULTS, readStore(SETTINGS_KEY, {}));

  function applySettings() {
    root.setAttribute('data-theme', settings.theme);
    root.setAttribute('data-font', settings.font);
    root.setAttribute('data-width', settings.width);
    root.setAttribute('data-align', settings.align);
    root.setAttribute('data-focus', settings.focus ? 'on' : 'off');
    root.setAttribute('data-calm', settings.calm ? 'on' : 'off');
    root.style.setProperty('--reader-font-size', settings.fontSize + 'rem');
    root.style.setProperty('--reader-line-height', String(settings.lineHeight));
    root.style.setProperty('--reader-letter-spacing', settings.letterSpacing + 'rem');
    root.style.setProperty('--reader-word-spacing', settings.wordSpacing + 'rem');
    root.style.setProperty('--reader-paragraph-spacing', settings.paragraphSpacing + 'rem');
    writeStore(SETTINGS_KEY, settings);
    syncControls();
  }

  function formatValue(name, value) {
    if (name === 'lineHeight') return Number(value).toFixed(2);
    return Math.round(value * 16) + 'px';
  }

  function syncControls() {
    document.querySelectorAll('[data-setting]').forEach(function (input) {
      var name = input.getAttribute('data-setting');
      var value = settings[name];
      if (input.type === 'radio') {
        input.checked = input.value === String(value);
      } else if (input.type === 'checkbox') {
        input.checked = Boolean(value);
      } else {
        input.value = value;
        var output = document.getElementById('out-' + input.id.replace(/^set-/, ''));
        if (output) output.textContent = formatValue(name, value);
      }
    });
  }

  function setSetting(name, value) {
    settings[name] = value;
    applySettings();
  }

  document.addEventListener('input', function (event) {
    var input = event.target.closest ? event.target.closest('[data-setting]') : null;
    if (!input) return;
    var name = input.getAttribute('data-setting');
    if (input.type === 'radio') {
      if (input.checked) setSetting(name, input.value);
    } else if (input.type === 'checkbox') {
      setSetting(name, input.checked);
    } else {
      setSetting(name, parseFloat(input.value));
    }
  });

  var resetButton = document.querySelector('[data-reset-settings]');
  if (resetButton) {
    resetButton.addEventListener('click', function () {
      settings = Object.assign({}, DEFAULTS);
      applySettings();
      announce(resetButton.textContent.trim());
    });
  }

  /* --- settings dialog ---------------------------------------------------- */

  var dialog = document.getElementById('settings-dialog');
  var openers = document.querySelectorAll('[data-open-settings]');

  function toggleDialog() {
    if (!dialog) return;
    if (dialog.open) {
      dialog.close();
    } else if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
  }

  openers.forEach(function (button) {
    button.addEventListener('click', toggleDialog);
  });

  /* --- first-visit language picker ---------------------------------------- */

  // The server renders it already open so it works without JavaScript; with
  // scripting we upgrade it to a real modal for the focus trap and backdrop.
  var languageDialog = document.getElementById('language-dialog');
  if (languageDialog && typeof languageDialog.showModal === 'function') {
    try {
      if (languageDialog.open) languageDialog.close();
      languageDialog.showModal();
      var firstOption = languageDialog.querySelector('.language-options a');
      if (firstOption) firstOption.focus();
    } catch (err) { /* leave it open and inline rather than losing the prompt */ }
  }

  /* --- language switcher -------------------------------------------------- */

  var languageSelect = document.querySelector('[data-language-select]');
  if (languageSelect) {
    languageSelect.addEventListener('change', function () {
      if (this.value) window.location.href = this.value;
    });
  }

  /* --- manual "check for new chapters" ------------------------------------ */

  document.querySelectorAll('[data-refresh]').forEach(function (button) {
    button.addEventListener('click', function () {
      var label = button.textContent;
      button.disabled = true;
      fetch('/api/refresh', { method: 'POST' })
        .then(function (response) { return response.json(); })
        .then(function () { window.location.reload(); })
        .catch(function () {
          button.disabled = false;
          button.textContent = label;
        });
    });
  });

  /* --- show the "last updated" stamp in the reader's own timezone ---------- */

  document.querySelectorAll('[data-localise-time]').forEach(function (node) {
    var stamp = node.getAttribute('datetime');
    if (!stamp) return;
    var when = new Date(stamp);
    if (isNaN(when.getTime())) return;
    var template = node.textContent.trim();
    var formatted = when.toLocaleString(document.documentElement.lang || undefined, {
      dateStyle: 'medium', timeStyle: 'short'
    });
    // Swap only the date portion, keeping the translated "Updated …" wording.
    node.textContent = template.replace(/\d.*$/, formatted);
  });

  /* --- reading progress and resume ---------------------------------------- */

  var article = document.querySelector('.reader');
  var progressWrap = document.querySelector('.progress-wrap');
  var progressBar = document.getElementById('reading-progress');
  var progress = readStore(PROGRESS_KEY, {});

  function progressKey(book, chapter, language) {
    return [language, book, chapter].join('/');
  }

  if (article && progressBar) {
    progressWrap.hidden = false;
    var book = article.getAttribute('data-book');
    var chapterSlug = article.getAttribute('data-chapter');
    var language = document.documentElement.lang;
    var key = progressKey(book, chapterSlug, language);
    var heading = document.querySelector('.chapter-head h1');

    var updateProgress = function () {
      var scrollable = document.documentElement.scrollHeight - window.innerHeight;
      var ratio = scrollable > 0 ? Math.min(1, Math.max(0, window.scrollY / scrollable)) : 1;
      var percent = Math.round(ratio * 100);
      progressBar.style.width = percent + '%';
      progressBar.setAttribute('aria-valuenow', String(percent));
      progress[key] = {
        ratio: ratio,
        title: heading ? heading.textContent.trim() : chapterSlug,
        book: article.getAttribute('data-book-title') || '',
        url: window.location.pathname,
        at: Date.now()
      };
    };

    var ticking = false;
    window.addEventListener('scroll', function () {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () {
        updateProgress();
        ticking = false;
      });
    }, { passive: true });

    window.addEventListener('beforeunload', function () { writeStore(PROGRESS_KEY, progress); });
    window.addEventListener('pagehide', function () { writeStore(PROGRESS_KEY, progress); });
    window.setInterval(function () { writeStore(PROGRESS_KEY, progress); }, 15000);

    // Offer to pick up where the reader left off, without hijacking the scroll.
    var saved = progress[key];
    if (saved && saved.ratio > 0.04 && saved.ratio < 0.95 && !window.location.hash) {
      var scrollable = document.documentElement.scrollHeight - window.innerHeight;
      window.scrollTo({ top: saved.ratio * scrollable, behavior: 'auto' });
    }
    updateProgress();
  }

  // Progress keys are "<language>/<book>/<chapter>", so a book's history is
  // everything whose middle segment matches.
  function entriesForBook(bookSlug) {
    var language = document.documentElement.lang;
    return Object.keys(progress)
      .filter(function (key) {
        var parts = key.split('/');
        // Only offer to resume reading the reader can actually read: a Turkish
        // page never points back at an English chapter.
        if (parts.length !== 3 || parts[0] !== language) return false;
        return !bookSlug || parts[1] === bookSlug;
      })
      .map(function (key) {
        var entry = progress[key];
        return entry && entry.url ? entry : null;
      })
      .filter(Boolean);
  }

  function mostRecent(entries, unfinishedOnly) {
    var best = null;
    entries.forEach(function (entry) {
      if (unfinishedOnly && entry.ratio >= 0.97) return;
      if (!best || entry.at > best.at) best = entry;
    });
    return best;
  }

  // Book page: surface the most recent unfinished chapter of this book.
  var resumeLink = document.getElementById('resume-link');
  if (resumeLink) {
    var pageBook = (window.location.pathname.split('/book/')[1] || '').split('/')[0];
    var newest = mostRecent(entriesForBook(pageBook || null), true);
    if (newest) {
      resumeLink.href = newest.url;
      resumeLink.hidden = false;
      resumeLink.title = newest.title;
      resumeLink.textContent = resumeLink.textContent.trim() + ' — ' + newest.title;

      // Mid-book, the action you want is "carry on", not "start". Swap the
      // emphasis and rename the other button for what it now does.
      var startLink = document.getElementById('start-link');
      if (startLink) {
        resumeLink.classList.remove('ghost-button');
        resumeLink.classList.add('primary-button');
        startLink.classList.remove('primary-button');
        startLink.classList.add('ghost-button');
        startLink.textContent = startLink.getAttribute('data-label-restart') || startLink.textContent;
        // Lead with the action they actually want, in reading order.
        startLink.parentNode.insertBefore(resumeLink, startLink);
      }
    }
  }

  // Library page: a "continue reading" card plus a progress bar per book.
  var continueRow = document.getElementById('continue-row');
  if (continueRow) {
    var latest = mostRecent(entriesForBook(null), true);
    if (latest) {
      var card = document.getElementById('continue-card');
      var percent = Math.round(latest.ratio * 100);
      card.href = latest.url;
      card.querySelector('[data-continue-title]').textContent = latest.title;
      card.querySelector('[data-continue-book]').textContent = latest.book || '';
      card.querySelector('[data-continue-fill]').style.width = percent + '%';
      card.querySelector('[data-continue-percent]').textContent = percent + '%';
      continueRow.hidden = false;
    }
  }

  document.querySelectorAll('[data-book-slug]').forEach(function (card) {
    var wrap = card.querySelector('[data-book-progress]');
    if (!wrap) return;
    var entries = entriesForBook(card.getAttribute('data-book-slug'));
    if (!entries.length) return;
    var recent = mostRecent(entries, false);
    var percent = Math.round(recent.ratio * 100);
    card.querySelector('[data-book-fill]').style.width = percent + '%';
    card.querySelector('[data-book-label]').textContent = recent.title + ' · ' + percent + '%';
    wrap.hidden = false;
  });

  document.querySelectorAll('.chapter-card').forEach(function (card) {
    var badge = card.querySelector('[data-resume-badge]');
    if (!badge) return;
    var url = card.getAttribute('href');
    var match = null;
    Object.keys(progress).forEach(function (key) {
      var entry = progress[key];
      if (entry && entry.url === url) match = entry;
    });
    if (match && match.ratio > 0.02) {
      badge.hidden = false;
      badge.textContent = Math.round(match.ratio * 100) + '%';
    }
  });

  /* --- focus mode: track the paragraph in the reading zone ----------------- */

  var paragraphs = Array.prototype.slice.call(document.querySelectorAll('.prose [data-para]'));

  if (paragraphs.length && 'IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          paragraphs.forEach(function (p) { p.classList.remove('is-current'); });
          entry.target.classList.add('is-current');
        }
      });
    }, { rootMargin: '-40% 0px -45% 0px', threshold: 0 });
    paragraphs.forEach(function (p) { observer.observe(p); });
  }

  /* --- read aloud (Web Speech API) ---------------------------------------- */

  var listenButton = document.querySelector('[data-listen]');
  if (listenButton) {
    var labelEl = listenButton.querySelector('[data-listen-label]');
    var labels = {
      listen: labelEl ? labelEl.textContent.trim() : 'Listen',
      stop: listenButton.getAttribute('data-label-stop') || '■'
    };
    var synth = window.speechSynthesis;
    var index = 0;
    var speaking = false;

    function clearHighlight() {
      paragraphs.forEach(function (p) { p.classList.remove('is-speaking'); });
    }

    function pickVoice() {
      var wanted = (document.querySelector('.prose') || document.documentElement).closest('[lang]');
      var code = (wanted ? wanted.lang : document.documentElement.lang || 'en').slice(0, 2);
      var voices = synth.getVoices() || [];
      return voices.filter(function (v) { return v.lang.toLowerCase().indexOf(code) === 0; })[0] || null;
    }

    function speakFrom(start) {
      if (start >= paragraphs.length) { stop(); return; }
      index = start;
      var node = paragraphs[index];
      var utterance = new window.SpeechSynthesisUtterance(node.textContent);
      var voice = pickVoice();
      if (voice) utterance.voice = voice;
      utterance.lang = (node.closest('[lang]') || document.documentElement).lang || 'en';
      utterance.rate = 1;
      utterance.onstart = function () {
        clearHighlight();
        node.classList.add('is-speaking');
        node.scrollIntoView({ block: 'center', behavior: settings.calm ? 'auto' : 'smooth' });
      };
      utterance.onend = function () {
        if (speaking) speakFrom(index + 1);
      };
      utterance.onerror = function () { stop(); };
      synth.speak(utterance);
    }

    function start() {
      if (!synth || !paragraphs.length) return;
      speaking = true;
      listenButton.setAttribute('aria-pressed', 'true');
      if (labelEl) labelEl.textContent = listenButton.getAttribute('data-stop-label') || '⏹';
      var current = paragraphs.findIndex ? paragraphs.findIndex(function (p) {
        return p.classList.contains('is-current');
      }) : 0;
      speakFrom(current > 0 ? current : 0);
    }

    function stop() {
      speaking = false;
      if (synth) synth.cancel();
      clearHighlight();
      listenButton.setAttribute('aria-pressed', 'false');
      if (labelEl) labelEl.textContent = labels.listen;
    }

    listenButton.setAttribute('aria-pressed', 'false');
    listenButton.addEventListener('click', function () {
      if (!('speechSynthesis' in window)) {
        announce(listenButton.getAttribute('data-unsupported') || 'Not supported');
        listenButton.disabled = true;
        return;
      }
      if (speaking) stop(); else start();
    });
    window.addEventListener('pagehide', stop);
    window.dwfeToggleSpeech = function () { listenButton.click(); };
  }

  /* --- new-chapter subscriptions ------------------------------------------- */

  // A subscription is a note in this browser: which books to watch and how
  // many chapters each had when last seen. Nothing is sent anywhere, so there
  // is no account to make and nothing to unsubscribe from by email. The cost
  // is that notifications can only be raised while the site is open — the page
  // says so before asking for permission, and new chapters are marked here on
  // the next visit regardless.
  var SUBS_KEY = 'dwfe:subscriptions';
  var POLL_MS = 5 * 60 * 1000;

  var phrases = (function () {
    var node = document.getElementById('dwfe-i18n');
    try {
      return node ? JSON.parse(node.textContent) : {};
    } catch (err) {
      return {};
    }
  })();

  function fill(template, values) {
    return String(template || '').replace(/\{(\w+)\}/g, function (whole, key) {
      return values[key] !== undefined ? values[key] : whole;
    });
  }

  var subscriptions = readStore(SUBS_KEY, {});

  function saveSubscriptions() { writeStore(SUBS_KEY, subscriptions); }

  function canNotify() {
    return typeof window.Notification === 'function';
  }

  function raiseNotification(book, chapters, added) {
    if (!canNotify() || window.Notification.permission !== 'granted') return;
    var latest = chapters[chapters.length - 1];
    var title = added === 1
      ? fill(phrases.one, { title: latest.title })
      : fill(phrases.many, { count: added });
    try {
      var note = new window.Notification(title, {
        body: fill(phrases.body, { book: book.title }),
        icon: '/static/img/favicon.svg',
        tag: 'dwfe-' + book.slug          // one book, one notification
      });
      note.onclick = function () {
        window.focus();
        window.location.href = latest.url;
      };
    } catch (err) { /* a browser may refuse outside a user gesture */ }
  }

  var banner = document.getElementById('new-chapters');

  function showBanner(added, latest) {
    if (!banner) return;
    banner.querySelector('[data-new-chapters-text]').textContent = added === 1
      ? phrases.bannerOne
      : fill(phrases.bannerMany, { count: added });
    banner.querySelector('[data-new-chapters-link]').href = latest.url;
    banner.hidden = false;
  }

  if (banner) {
    banner.querySelector('[data-new-chapters-dismiss]').addEventListener('click', function () {
      banner.hidden = true;
    });
  }

  var subscribeButton = document.querySelector('[data-subscribe]');
  var subscribeDialog = document.getElementById('subscribe-dialog');

  function paintSubscribeButton() {
    if (!subscribeButton) return;
    var slug = subscribeButton.getAttribute('data-book');
    var on = Boolean(subscriptions[slug]);
    subscribeButton.setAttribute('aria-pressed', on ? 'true' : 'false');
    subscribeButton.classList.toggle('is-subscribed', on);
    subscribeButton.querySelector('[data-subscribe-label]').textContent =
      subscribeButton.getAttribute(on ? 'data-label-off' : 'data-label-on');
    subscribeButton.hidden = false;   // only offered where the script runs
  }

  function subscribe() {
    var slug = subscribeButton.getAttribute('data-book');
    var title = subscribeButton.getAttribute('data-book-title');
    subscriptions[slug] = {
      lang: subscribeButton.getAttribute('data-lang'),
      count: parseInt(subscribeButton.getAttribute('data-count'), 10) || 0,
      title: title,
      at: Date.now()
    };
    saveSubscriptions();
    paintSubscribeButton();

    if (!canNotify()) {
      announce(phrases.unsupported);
    } else if (window.Notification.permission === 'denied') {
      announce(phrases.blocked);
    } else {
      announce(fill(phrases.subscribed, { book: title }));
    }
  }

  if (subscribeButton) {
    paintSubscribeButton();

    subscribeButton.addEventListener('click', function () {
      var slug = subscribeButton.getAttribute('data-book');
      if (subscriptions[slug]) {
        var title = subscriptions[slug].title;
        delete subscriptions[slug];
        saveSubscriptions();
        paintSubscribeButton();
        announce(fill(phrases.unsubscribed, { book: title }));
        return;
      }

      // Explain what the browser is about to ask before it asks.
      if (canNotify() && window.Notification.permission === 'default' && subscribeDialog) {
        if (typeof subscribeDialog.showModal === 'function') {
          subscribeDialog.showModal();
        } else {
          subscribeDialog.setAttribute('open', '');
        }
        return;
      }
      subscribe();
    });
  }

  if (subscribeDialog) {
    var confirmButton = subscribeDialog.querySelector('[data-subscribe-confirm]');
    if (confirmButton) {
      confirmButton.addEventListener('click', function () {
        subscribeDialog.close();
        try {
          var asked = window.Notification.requestPermission();
          if (asked && typeof asked.then === 'function') {
            asked.then(subscribe, subscribe);
          } else {
            subscribe();
          }
        } catch (err) {
          subscribe();
        }
      });
    }
  }

  function checkSubscriptions() {
    var slugs = Object.keys(subscriptions);
    if (!slugs.length || !window.fetch) return;

    fetch('/api/library', { headers: { Accept: 'application/json' } })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        var changed = false;
        (payload.books || []).forEach(function (book) {
          var sub = subscriptions[book.slug];
          if (!sub) return;
          var chapters = book.editions[sub.lang] || book.editions[Object.keys(book.editions)[0]];
          if (!chapters) return;

          var added = chapters.length - sub.count;
          if (added > 0) {
            raiseNotification(book, chapters, added);
            if (subscribeButton && subscribeButton.getAttribute('data-book') === book.slug) {
              showBanner(added, chapters[chapters.length - 1]);
            }
            sub.count = chapters.length;
            changed = true;
          } else if (added < 0) {
            sub.count = chapters.length;   // a chapter was withdrawn
            changed = true;
          }
        });
        if (changed) saveSubscriptions();
      })
      .catch(function () { /* offline: try again on the next tick */ });
  }

  checkSubscriptions();
  window.addEventListener('focus', checkSubscriptions);
  window.setInterval(checkSubscriptions, POLL_MS);

  /* --- keyboard shortcuts -------------------------------------------------- */

  function isTypingTarget(target) {
    if (!target) return false;
    var tag = (target.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'select' || tag === 'textarea' || target.isContentEditable;
  }

  document.addEventListener('keydown', function (event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (isTypingTarget(event.target)) return;

    var prev = document.querySelector('[data-prev-chapter]');
    var next = document.querySelector('[data-next-chapter]');
    var rtl = document.documentElement.dir === 'rtl';

    switch (event.key) {
      case 'ArrowLeft':
        if (rtl ? next : prev) { (rtl ? next : prev).click(); }
        break;
      case 'ArrowRight':
        if (rtl ? prev : next) { (rtl ? prev : next).click(); }
        break;
      case 's':
      case 'S':
        event.preventDefault();
        toggleDialog();
        break;
      case 'd':
      case 'D':
        var position = THEME_ORDER.indexOf(settings.theme);
        setSetting('theme', THEME_ORDER[(position + 1) % THEME_ORDER.length]);
        announce(settings.theme);
        break;
      case '+':
      case '=':
        setSetting('fontSize', Math.min(2, Math.round((settings.fontSize + 0.05) * 100) / 100));
        announce(formatValue('fontSize', settings.fontSize));
        break;
      case '-':
      case '_':
        setSetting('fontSize', Math.max(0.9, Math.round((settings.fontSize - 0.05) * 100) / 100));
        announce(formatValue('fontSize', settings.fontSize));
        break;
      case 'l':
      case 'L':
        if (window.dwfeToggleSpeech) window.dwfeToggleSpeech();
        break;
      default:
        break;
    }
  });

  applySettings();
})();
