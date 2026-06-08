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
