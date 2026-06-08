const root = document.documentElement;
const btn = document.getElementById('themeToggle');
const savedTheme = localStorage.getItem('theme');
if (savedTheme === 'light' || savedTheme === 'dark') root.dataset.theme = savedTheme;
if (root.dataset.theme !== 'light' && root.dataset.theme !== 'dark') root.dataset.theme = 'light';

const syncThemeToggle = () => {
  if (!btn) return;
  const isLight = root.dataset.theme === 'light';
  btn.setAttribute('aria-pressed', String(!isLight));
  btn.setAttribute('aria-label', isLight ? 'Switch to dark mode' : 'Switch to light mode');
  const icon = btn.querySelector('.theme-icon');
  const text = btn.querySelector('.theme-text');
  if (icon) icon.textContent = '💡';
  if (text) text.textContent = isLight ? 'Light' : 'Dark';
};

if (btn) {
  syncThemeToggle();
  btn.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', root.dataset.theme);
    syncThemeToggle();
  });
}


const languageSwitchers = document.querySelectorAll('.language-switcher');
languageSwitchers.forEach((switcher) => {
  const summary = switcher.querySelector('summary');
  if (summary) {
    summary.setAttribute('aria-haspopup', 'menu');
    summary.setAttribute('aria-expanded', String(switcher.open));
  }

  switcher.addEventListener('toggle', () => {
    if (summary) summary.setAttribute('aria-expanded', String(switcher.open));
    if (!switcher.open) return;
    languageSwitchers.forEach((otherSwitcher) => {
      if (otherSwitcher === switcher) return;
      otherSwitcher.open = false;
    });
  });

  switcher.querySelectorAll('.language-dropdown a').forEach((link) => {
    link.addEventListener('click', () => {
      switcher.open = false;
    });
  });
});

document.addEventListener('click', (event) => {
  languageSwitchers.forEach((switcher) => {
    if (switcher.contains(event.target)) return;
    switcher.open = false;
  });
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  languageSwitchers.forEach((switcher) => {
    switcher.open = false;
  });
});

const categoryMenus = document.querySelectorAll('.category-menu');
categoryMenus.forEach((menu) => {
  const button = menu.querySelector('.category-menu-button');
  if (!button) return;

  const dropdown = menu.querySelector('.category-dropdown');
  if (dropdown) dropdown.hidden = true;

  button.addEventListener('click', (event) => {
    event.stopPropagation();
    const isOpen = !menu.classList.contains('is-open');
    menu.classList.toggle('is-open', isOpen);
    button.setAttribute('aria-expanded', String(isOpen));
    if (dropdown) dropdown.hidden = !isOpen;

    categoryMenus.forEach((otherMenu) => {
      if (otherMenu === menu) return;
      otherMenu.classList.remove('is-open');
      const otherButton = otherMenu.querySelector('.category-menu-button');
      const otherDropdown = otherMenu.querySelector('.category-dropdown');
      if (otherButton) otherButton.setAttribute('aria-expanded', 'false');
      if (otherDropdown) otherDropdown.hidden = true;
    });
  });
});

document.addEventListener('click', (event) => {
  categoryMenus.forEach((menu) => {
    if (menu.contains(event.target)) return;
    menu.classList.remove('is-open');
    const button = menu.querySelector('.category-menu-button');
    const dropdown = menu.querySelector('.category-dropdown');
    if (button) button.setAttribute('aria-expanded', 'false');
    if (dropdown) dropdown.hidden = true;
  });
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  categoryMenus.forEach((menu) => {
    menu.classList.remove('is-open');
    const button = menu.querySelector('.category-menu-button');
    const dropdown = menu.querySelector('.category-dropdown');
    if (button) button.setAttribute('aria-expanded', 'false');
    if (dropdown) dropdown.hidden = true;
  });
});

const buildVreycPlaceholder = (className = '') => {
  const placeholder = document.createElement('div');
  placeholder.className = `image-placeholder ${className}`.trim();
  placeholder.textContent = 'VREYC';
  return placeholder;
};

document.querySelectorAll('img').forEach((image) => {
  image.addEventListener('error', () => {
    if (image.dataset.placeholderApplied === '1') return;
    image.dataset.placeholderApplied = '1';
    const compact = image.closest('.related-card') ? 'related-placeholder' : (image.closest('.article-image-frame') ? 'article-image-placeholder' : 'compact');
    image.replaceWith(buildVreycPlaceholder(compact));
  });
});

const nativeShareLinks = document.querySelectorAll('.js-native-share');
const canUseNativeShare = () => (
  typeof navigator !== 'undefined'
  && typeof navigator.share === 'function'
  && window.matchMedia('(max-width: 768px), (pointer: coarse)').matches
);

nativeShareLinks.forEach((link) => {
  link.addEventListener('click', async (event) => {
    if (!canUseNativeShare()) return;

    const shareData = {
      title: link.dataset.shareTitle || document.title,
      text: link.dataset.shareText || '',
      url: link.dataset.shareUrl || window.location.href,
    };

    if (typeof navigator.canShare === 'function' && !navigator.canShare(shareData)) return;

    event.preventDefault();
    try {
      await navigator.share(shareData);
    } catch (error) {
      if (error && error.name === 'AbortError') return;
      window.open(link.href, link.target || '_self', 'noopener');
    }
  });
});

const mobileMenuToggle = document.getElementById('mobileMenuToggle');
const mobileMenuPanel = mobileMenuToggle ? document.getElementById(mobileMenuToggle.getAttribute('aria-controls')) : null;
if (mobileMenuToggle && mobileMenuPanel) {
  mobileMenuPanel.hidden = true;
  mobileMenuToggle.addEventListener('click', () => {
    const isOpen = mobileMenuToggle.getAttribute('aria-expanded') === 'true';
    mobileMenuToggle.setAttribute('aria-expanded', String(!isOpen));
    mobileMenuPanel.hidden = isOpen;
  });
}

const newsletterForms = document.querySelectorAll('[data-newsletter-form]');
newsletterForms.forEach((form) => {
  const input = form.querySelector('input[name="email"]');
  const button = form.querySelector('button[type="submit"]');
  const message = form.querySelector('[data-newsletter-message]');
  const setMessage = (text, state) => {
    if (!message) return;
    message.textContent = text;
    form.classList.toggle('is-success', state === 'success');
    form.classList.toggle('is-error', state === 'error');
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!input || !input.checkValidity()) {
      if (input) input.reportValidity();
      setMessage(form.dataset.invalid || 'Please enter a valid email address.', 'error');
      return;
    }

    if (button) button.disabled = true;
    form.classList.remove('is-success', 'is-error');

    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { Accept: 'application/json' },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) {
        setMessage(data.message || form.dataset.invalid || 'Please enter a valid email address.', 'error');
        return;
      }
      input.value = '';
      setMessage(data.message || form.dataset.success || 'Subscription saved successfully.', 'success');
    } catch (error) {
      setMessage(form.dataset.error || 'Subscription could not be saved. Please try again.', 'error');
    } finally {
      if (button) button.disabled = false;
    }
  });
});

const youtubeShortFrames = document.querySelectorAll('[data-youtube-short]');
let youtubeIframeApiPromise;

const ensureYoutubeIframeApi = () => {
  if (window.YT && window.YT.Player) return Promise.resolve(window.YT);
  if (youtubeIframeApiPromise) return youtubeIframeApiPromise;

  youtubeIframeApiPromise = new Promise((resolve, reject) => {
    const previousCallback = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      if (typeof previousCallback === 'function') previousCallback();
      resolve(window.YT);
    };

    const existingScript = document.querySelector('script[src="https://www.youtube.com/iframe_api"]');
    if (!existingScript) {
      const script = document.createElement('script');
      script.src = 'https://www.youtube.com/iframe_api';
      script.async = true;
      script.onerror = () => reject(new Error('YouTube iframe API failed to load'));
      document.head.appendChild(script);
    }

    window.setTimeout(() => {
      if (!(window.YT && window.YT.Player)) reject(new Error('YouTube iframe API timed out'));
    }, 6000);
  });

  return youtubeIframeApiPromise;
};

const keepYoutubeThumbnail = (frame, url, thumbnail) => {
  frame.dataset.loaded = '0';
  frame.dataset.playerReady = '0';
  const link = frame.querySelector('.youtube-load-button');
  if (link && url) link.href = url;
  const image = frame.querySelector('.youtube-thumbnail');
  if (image && thumbnail) image.src = thumbnail;
  frame.querySelectorAll('iframe').forEach((iframe) => iframe.remove());
};

const loadYoutubeCandidate = (frame, candidate, allowFallback = true) => {
  if (!frame || !candidate.src || frame.dataset.loading === candidate.src) return;
  frame.dataset.loading = candidate.src;
  frame.dataset.playerReady = '0';
  frame.classList.toggle('youtube-lazy-frame--video', candidate.kind !== 'short');

  const holder = document.createElement('div');
  const holderId = `youtube-player-${candidate.id}-${Date.now()}`;
  holder.id = holderId;
  frame.appendChild(holder);

  const fail = () => {
    holder.remove();
    frame.dataset.loading = '';
    if (allowFallback && candidate.kind === 'short' && frame.dataset.fallbackSrc && frame.dataset.fallbackVideoId && frame.dataset.fallbackVideoId !== candidate.id) {
      const link = frame.querySelector('.youtube-load-button');
      const image = frame.querySelector('.youtube-thumbnail');
      if (link && frame.dataset.fallbackUrl) link.href = frame.dataset.fallbackUrl;
      if (image && frame.dataset.fallbackThumbnail) image.src = frame.dataset.fallbackThumbnail;
      loadYoutubeCandidate(frame, {
        id: frame.dataset.fallbackVideoId,
        src: frame.dataset.fallbackSrc,
        url: frame.dataset.fallbackUrl,
        kind: frame.dataset.fallbackKind || 'video',
      }, false);
      return;
    }
    keepYoutubeThumbnail(frame, candidate.url, candidate.thumbnail || frame.dataset.fallbackThumbnail || '');
  };

  ensureYoutubeIframeApi().then((YT) => {
    const player = new YT.Player(holderId, {
      videoId: candidate.id,
      playerVars: {
        autoplay: 1,
        mute: 1,
        playsinline: 1,
        rel: 0,
        modestbranding: 1,
      },
      events: {
        onReady: (event) => {
          try {
            event.target.mute();
            event.target.playVideo();
          } catch (error) {
            // Keep the thumbnail visible if playback cannot start.
          }
        },
        onStateChange: (event) => {
          if (![YT.PlayerState.PLAYING, YT.PlayerState.BUFFERING].includes(event.data)) return;
          frame.dataset.loaded = '1';
          frame.dataset.playerReady = '1';
          frame.dataset.loading = '';
          const preview = frame.querySelector('.youtube-load-button');
          if (preview) preview.remove();
        },
        onError: fail,
      },
    });

    window.setTimeout(() => {
      if (frame.dataset.playerReady !== '1') {
        try { player.destroy(); } catch (error) { /* no-op */ }
        fail();
      }
    }, 8000);
  }).catch(fail);
};

const loadYoutubeShortFrame = (frame) => {
  if (!frame || frame.dataset.loaded === '1' || frame.dataset.loading) return;
  loadYoutubeCandidate(frame, {
    id: frame.dataset.videoId,
    src: frame.dataset.embedSrc,
    url: frame.dataset.url,
    kind: frame.dataset.kind || 'short',
    thumbnail: frame.querySelector('.youtube-thumbnail')?.getAttribute('src') || '',
  });
};

youtubeShortFrames.forEach((frame) => {
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries, activeObserver) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        loadYoutubeShortFrame(frame);
        activeObserver.unobserve(frame);
      });
    }, { rootMargin: '240px 0px' });
    observer.observe(frame);
    return;
  }

  window.setTimeout(() => loadYoutubeShortFrame(frame), 1200);
});
