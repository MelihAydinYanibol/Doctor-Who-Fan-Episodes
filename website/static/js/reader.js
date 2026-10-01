/* ==========================================================================
   The Time Parallax — reader behaviour
   Vanilla JS, no dependencies. Everything degrades gracefully: with
   JavaScript off the site is still a fully readable, navigable book.
   ========================================================================== */

(function () {
  'use strict';

  var SETTINGS_KEY = 'dwfe:settings';
  var SETTINGS_AT_KEY = 'dwfe:settings-at';
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

  function announce(message) {
    if (!live || !message) return;
    live.textContent = '';
    window.setTimeout(function () { live.textContent = message; }, 40);
  }

  /* --- settings ----------------------------------------------------------- */

  var settings = Object.assign({}, DEFAULTS, readStore(SETTINGS_KEY, {}));
  // When the reader last changed a setting, so sync knows whose to keep.
  var settingsAt = readStore(SETTINGS_AT_KEY, 0);

  function touchSettings() {
    settingsAt = Date.now();
    writeStore(SETTINGS_AT_KEY, settingsAt);
    if (window.dwfeSyncSoon) window.dwfeSyncSoon();
  }

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
    touchSettings();
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
      touchSettings();
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

  // Everything below that reads `progress` waits for renderProgress(), which
  // runs once the first sync has answered (or straight away without sync), so
  // a place saved on another device is what the page shows and resumes.
  function trackChapter() {
    if (!article || !progressBar) return;
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
      // Restoring a saved position is not reading. Keep its timestamp unless
      // the reader actually moved, or a fresh page load would outrank a
      // further position synced from another device.
      var previous = progress[key];
      if (previous && Math.abs(previous.ratio - ratio) < 0.01) return;
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

    var saveProgress = function () {
      writeStore(PROGRESS_KEY, progress);
      if (window.dwfeSyncSoon) window.dwfeSyncSoon();
    };
    window.addEventListener('beforeunload', function () { writeStore(PROGRESS_KEY, progress); });
    window.addEventListener('pagehide', function () { writeStore(PROGRESS_KEY, progress); });
    window.setInterval(saveProgress, 15000);

    // Offer to pick up where the reader left off, without hijacking the scroll.
    var saved = progress[key];
    // Sync can delay this a moment; never yank a reader who already scrolled.
    if (saved && saved.ratio > 0.04 && saved.ratio < 0.95 && !window.location.hash && window.scrollY < 40) {
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
        // A shallow copy so the key travels with the entry without being
        // written back into storage.
        return entry && entry.url ? Object.assign({ key: key }, entry) : null;
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

  function renderProgress() {
    trackChapter();
    renderResume();
    renderShelf();
  }

  // Book page: surface the most recent unfinished chapter of this book.
  function renderResume() {
    var resumeLink = document.getElementById('resume-link');
    if (resumeLink) {
      var pageBook = (window.location.pathname.split('/book/')[1] || '').split('/')[0];
      var newest = mostRecent(entriesForBook(pageBook || null), true);
      if (newest) {
        resumeLink.href = newest.url;
        resumeLink.hidden = false;
        resumeLink.title = newest.title;
        // "Continue reading — Chapter 2" reads quicker than the chapter's name,
        // and keeps the button to a predictable width. The number comes from the
        // slug, so positions saved before this existed still work. Chapter 0 is
        // the unnumbered primer, so it goes by its title like any other.
        var numbered = /(?:^|\/)chapter-(\d+)$/.exec(newest.key || '');
        var where = numbered && Number(numbered[1]) !== 0
          ? fill(phrases.chapterNumber, { number: numbered[1] })
          : newest.title;
        resumeLink.textContent = resumeLink.textContent.trim() + ' — ' + where;

        // Mid-book, the action you want is "carry on", not "start". Swap the
        // emphasis, rename the other button for what it now does, and move it
        // out of the way to the end.
        var startLink = document.getElementById('start-link');
        if (startLink) {
          var actions = startLink.parentNode;
          resumeLink.classList.remove('ghost-button');
          resumeLink.classList.add('primary-button');
          startLink.classList.remove('primary-button');
          startLink.classList.add('ghost-button');
          startLink.textContent = startLink.getAttribute('data-label-restart') || startLink.textContent;
          actions.insertBefore(resumeLink, actions.firstChild);
          actions.appendChild(startLink);

          // Opening chapter one makes it the place "continue" returns to, so
          // check that is what they meant.
          var restartDialog = document.getElementById('restart-dialog');
          if (restartDialog && typeof restartDialog.showModal === 'function') {
            var body = restartDialog.querySelector('[data-restart-body]');
            if (body) body.textContent = fill(phrases.restartBody, { chapter: where });
            startLink.addEventListener('click', function (event) {
              event.preventDefault();
              restartDialog.showModal();
            });
          }
        }
      }
    }
  }

  // Library page: a "continue reading" card plus a progress bar per book.
  function renderShelf() {
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
  }

  /* --- cross-device sync ---------------------------------------------------- */

  // An 8-digit code stands in for an account. It lives in a cookie so the
  // server's /sync/<code> link (what the QR code points at) can set it too.
  // Every push sends this device's progress and settings and gets back the
  // merge of every device on the code: newest wins per chapter, and the most
  // recently changed settings win as a whole.
  var SYNC_COOKIE = 'dwfe_sync';
  var SYNC_AT_KEY = 'dwfe:sync-at';
  var SYNC_FIRST_WAIT_MS = 2500;   // how long the page waits before showing progress anyway
  var SYNC_MIN_GAP_MS = 20000;     // pull at most this often on focus

  function readCookie(name) {
    var found = null;
    String(document.cookie || '').split(';').forEach(function (part) {
      var pair = part.trim().split('=');
      if (pair[0] === name) found = decodeURIComponent(pair.slice(1).join('='));
    });
    return found;
  }

  function writeCookie(name, value) {
    var secure = window.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = value === null
      ? name + '=; Max-Age=0; Path=/; SameSite=Lax'
      : name + '=' + encodeURIComponent(value) + '; Max-Age=' + (60 * 60 * 24 * 400) + '; Path=/; SameSite=Lax' + secure;
  }

  function normaliseCode(raw) {
    var digits = String(raw || '').replace(/[\s-]/g, '');
    return /^\d{8}$/.test(digits) ? digits : null;
  }

  function formatCode(code) {
    return code.slice(0, 4) + ' ' + code.slice(4);
  }

  var syncCode = normaliseCode(readCookie(SYNC_COOKIE));
  var lastPushed = null;     // the payload last accepted, to skip no-op pushes
  var lastPullAt = 0;
  var pushTimer = null;

  function syncPayload() {
    return JSON.stringify({
      progress: progress,
      settings: { at: settingsAt, values: settings }
    });
  }

  // Fold the server's merged document into this device.
  var remoteMovedProgress = false;   // did the last sync bring in reading from elsewhere?

  function applyRemote(doc) {
    var changed = false;
    var remote = (doc && doc.progress) || {};
    Object.keys(remote).forEach(function (key) {
      var mine = progress[key];
      if (!mine || remote[key].at > mine.at) {
        progress[key] = remote[key];
        changed = true;
      }
    });
    if (changed) writeStore(PROGRESS_KEY, progress);
    remoteMovedProgress = changed;

    var theirs = doc && doc.settings;
    if (theirs && theirs.values && theirs.at > settingsAt) {
      settings = Object.assign({}, DEFAULTS, theirs.values);
      settingsAt = theirs.at;
      writeStore(SETTINGS_AT_KEY, settingsAt);
      applySettings();
    }
    writeStore(SYNC_AT_KEY, Date.now());
    paintSyncStatus();
  }

  function forgetCode(message) {
    syncCode = null;
    lastPushed = null;
    writeCookie(SYNC_COOKIE, null);
    paintSyncButton();
    if (message) announce(message);
  }

  // Push this device's state and take back the merge. Resolves to true on
  // success; never rejects, since a failed sync must not break reading.
  function pushSync(force) {
    if (!syncCode || !window.fetch) return Promise.resolve(false);
    var body = syncPayload();
    lastPullAt = Date.now();
    if (!force && body === lastPushed) return Promise.resolve(true);
    var code = syncCode;
    return fetch('/api/sync/' + code, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body,
      credentials: 'same-origin'
    })
      .then(function (response) {
        if (response.status === 404) {
          // The code is gone from the server: stop trying, keep local data.
          if (code === syncCode) forgetCode(phrases.syncUnknown);
          return false;
        }
        if (!response.ok) return false;
        return response.json().then(function (doc) {
          if (code !== syncCode) return false;
          applyRemote(doc);
          lastPushed = syncPayload();
          return true;
        });
      })
      .catch(function () { return false; });
  }

  // Coalesce bursts of changes (a dragged slider, a scroll) into one push.
  window.dwfeSyncSoon = function () {
    if (!syncCode) return;
    window.clearTimeout(pushTimer);
    pushTimer = window.setTimeout(function () { pushSync(false); }, 1500);
  };

  // Leaving the page: hand the last position over without waiting for a reply.
  window.addEventListener('pagehide', function () {
    if (!syncCode || !navigator.sendBeacon) return;
    var body = syncPayload();
    if (body === lastPushed) return;
    try {
      navigator.sendBeacon('/api/sync/' + syncCode, new Blob([body], { type: 'text/plain;charset=UTF-8' }));
    } catch (err) { /* best effort */ }
  });

  // Coming back to a tab may mean another device has moved on meanwhile.
  function pullIfStale() {
    if (!syncCode || Date.now() - lastPullAt < SYNC_MIN_GAP_MS) return;
    pushSync(true);
  }
  window.addEventListener('focus', pullIfStale);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') pullIfStale();
  });

  // First sync, then draw the progress UI — whichever comes first of the
  // answer and a short timeout, so a slow network never hides the page.
  (function () {
    var drawn = false;
    function draw() {
      if (drawn) return;
      drawn = true;
      renderProgress();
    }
    if (syncCode) {
      pushSync(true).then(draw);
      window.setTimeout(draw, SYNC_FIRST_WAIT_MS);
    } else {
      draw();
    }
  })();

  /* --- sync dialog --------------------------------------------------------- */

  var syncDialog = document.getElementById('sync-dialog');
  var syncButton = document.querySelector('[data-open-sync]');

  function paintSyncButton() {
    if (!syncButton) return;
    syncButton.hidden = false;
    syncButton.classList.toggle('is-synced', Boolean(syncCode));
    var dot = syncButton.querySelector('[data-sync-dot]');
    if (dot) dot.hidden = !syncCode;
  }

  function paintSyncStatus() {
    if (!syncDialog) return;
    var status = syncDialog.querySelector('[data-sync-status]');
    if (!status) return;
    var at = readStore(SYNC_AT_KEY, 0);
    status.textContent = at
      ? fill(phrases.syncLast, {
        when: new Date(at).toLocaleString(document.documentElement.lang || undefined, {
          dateStyle: 'medium', timeStyle: 'short'
        })
      })
      : phrases.syncNever;
  }

  if (syncDialog && syncButton) {
    var steps = syncDialog.querySelectorAll('[data-sync-step]');
    var codeInput = syncDialog.querySelector('[data-sync-code-input]');
    var errorBox = syncDialog.querySelector('[data-sync-error]');
    var scanButton = syncDialog.querySelector('[data-sync-scan]');
    var scanner = syncDialog.querySelector('[data-sync-scanner]');
    var video = syncDialog.querySelector('[data-sync-video]');
    var copyButton = syncDialog.querySelector('[data-sync-copy]');
    var scanLabel = scanButton ? scanButton.textContent.trim() : '';
    var copyLabel = copyButton ? copyButton.textContent.trim() : '';
    var stream = null;

    var showStep = function (name) {
      steps.forEach(function (step) {
        step.hidden = step.getAttribute('data-sync-step') !== name;
      });
      if (name !== 'enter') stopScan();
      if (name === 'linked' && syncCode) {
        syncDialog.querySelector('[data-sync-code]').textContent = formatCode(syncCode);
        var qr = syncDialog.querySelector('[data-sync-qr]');
        // If the image cannot load, the typed code still works: hide the
        // broken-image box rather than leave it in the way.
        qr.hidden = false;
        qr.onerror = function () { qr.hidden = true; };
        qr.src = '/api/sync/' + syncCode + '/qr.svg';
        qr.alt = fill(qr.getAttribute('data-alt-template'), { code: formatCode(syncCode) });
        paintSyncStatus();
      }
      if (name === 'enter') {
        showError('');
        if (codeInput) window.setTimeout(function () { codeInput.focus(); }, 30);
      }
    };

    var showError = function (message) {
      if (errorBox) errorBox.textContent = message || '';
      if (codeInput) codeInput.setAttribute('aria-invalid', message ? 'true' : 'false');
    };

    var openSync = function (step) {
      showStep(step || (syncCode ? 'linked' : 'choose'));
      if (syncDialog.open) return;
      if (typeof syncDialog.showModal === 'function') syncDialog.showModal();
      else syncDialog.setAttribute('open', '');
    };

    // Linking a device pulls in progress the page has not drawn yet, so
    // reload into the confirmation rather than redraw everything by hand.
    var reloadLinked = function () {
      var url = new URL(window.location.href);
      url.searchParams.set('sync', 'linked');
      window.location.replace(url.toString());
    };

    var join = function (raw) {
      var code = normaliseCode(raw);
      if (!code) { showError(phrases.syncInvalid); return; }
      showError('');
      fetch('/api/sync/' + code, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
        .then(function (response) {
          if (response.status === 404) { showError(phrases.syncUnknown); return; }
          if (!response.ok) { showError(phrases.syncFailed); return; }
          syncCode = code;
          writeCookie(SYNC_COOKIE, code);
          // Send what this device has read before the page reloads, so
          // nothing read here is lost to the other devices.
          return pushSync(true).then(reloadLinked);
        })
        .catch(function () { showError(phrases.syncFailed); });
    };

    syncButton.addEventListener('click', function () { openSync(); });

    syncDialog.querySelectorAll('[data-sync-show]').forEach(function (button) {
      button.addEventListener('click', function () { showStep(button.getAttribute('data-sync-show')); });
    });

    syncDialog.querySelector('[data-sync-create]').addEventListener('click', function () {
      var button = this;
      button.disabled = true;
      fetch('/api/sync', { method: 'POST', headers: { Accept: 'application/json' }, credentials: 'same-origin' })
        .then(function (response) {
          if (!response.ok) throw new Error('create failed');
          return response.json();
        })
        .then(function (doc) {
          syncCode = doc.code;
          writeCookie(SYNC_COOKIE, syncCode);
          paintSyncButton();
          showStep('linked');
          announce(phrases.syncCreated);
          return pushSync(true);
        })
        .catch(function () { announce(phrases.syncFailed); })
        .then(function () { button.disabled = false; });
    });

    syncDialog.querySelector('[data-sync-enter-form]').addEventListener('submit', function (event) {
      event.preventDefault();
      join(codeInput.value);
    });

    syncDialog.querySelector('[data-sync-now]').addEventListener('click', function () {
      var button = this;
      button.disabled = true;
      pushSync(true).then(function (ok) {
        button.disabled = false;
        if (!ok && syncCode) announce(phrases.syncFailed);
        // Reading from another device arrived: redraw the page from it.
        if (ok && remoteMovedProgress) window.location.reload();
      });
    });

    if (copyButton) {
      copyButton.addEventListener('click', function () {
        if (!syncCode || !navigator.clipboard) return;
        navigator.clipboard.writeText(syncCode).then(function () {
          copyButton.textContent = copyButton.getAttribute('data-label-done');
          announce(copyButton.textContent);
          window.setTimeout(function () { copyButton.textContent = copyLabel; }, 2000);
        }, function () { /* clipboard refused; the code is on screen anyway */ });
      });
      if (!navigator.clipboard) copyButton.hidden = true;
    }

    syncDialog.querySelector('[data-sync-disconnect]').addEventListener('click', function () {
      forgetCode(phrases.syncUnlinked);
      showStep('choose');
    });

    /* QR scanning uses the browser's own BarcodeDetector (Chrome on Android,
       for one). Where it is missing the button stays hidden and the hint
       points at the phone's camera app, which opens the QR link directly. */
    var detector = null;
    try {
      if ('BarcodeDetector' in window && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        detector = new window.BarcodeDetector({ formats: ['qr_code'] });
      }
    } catch (err) { detector = null; }

    function stopScan() {
      if (stream) {
        stream.getTracks().forEach(function (track) { track.stop(); });
        stream = null;
      }
      if (video) video.srcObject = null;
      if (scanner) scanner.hidden = true;
      if (scanButton) scanButton.textContent = scanLabel;
    }

    function codeFromScan(text) {
      var match = /\/sync\/(\d{8})(?:[/?#]|$)/.exec(text) || /^\s*(\d{4}\s?\d{4})\s*$/.exec(text);
      return match ? normaliseCode(match[1]) : null;
    }

    function scanFrame() {
      if (!stream) return;
      detector.detect(video).then(function (found) {
        var code = null;
        (found || []).forEach(function (item) { code = code || codeFromScan(item.rawValue || ''); });
        if (code) {
          stopScan();
          codeInput.value = formatCode(code);
          join(code);
        } else {
          window.setTimeout(scanFrame, 250);
        }
      }, function () { window.setTimeout(scanFrame, 500); });
    }

    if (scanButton && detector) {
      scanButton.hidden = false;
      scanButton.addEventListener('click', function () {
        if (stream) { stopScan(); return; }
        showError('');
        navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
          .then(function (media) {
            stream = media;
            video.srcObject = media;
            scanner.hidden = false;
            scanButton.textContent = scanButton.getAttribute('data-label-stop');
            return video.play();
          })
          .then(scanFrame)
          .catch(function () {
            stopScan();
            showError(phrases.syncScanFailed);
          });
      });
    }

    syncDialog.addEventListener('close', stopScan);

    paintSyncButton();

    // Arriving from the QR link or after joining: say so, then tidy the URL.
    var params = new URLSearchParams(window.location.search);
    var arrived = params.get('sync');
    if (arrived) {
      params.delete('sync');
      var query = params.toString();
      window.history.replaceState(null, '', window.location.pathname + (query ? '?' + query : '') + window.location.hash);
      if (arrived === 'linked' && syncCode) {
        announce(phrases.syncLinked);
        openSync('linked');
      } else if (arrived === 'unknown') {
        openSync('enter');
        showError(phrases.syncUnknown);
      }
    }
  }

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
    // Highlighted means "this is on", so the label has to describe the state
    // too. A highlighted "Stop notifying me" reads as an instruction to stop.
    subscribeButton.querySelector('[data-subscribe-label]').textContent =
      subscribeButton.getAttribute(on ? 'data-label-state' : 'data-label-on');
    // What the click will do belongs in the tooltip, not the label.
    if (on) {
      subscribeButton.title = subscribeButton.getAttribute('data-label-off');
    } else {
      subscribeButton.removeAttribute('title');
    }
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
