const root = document.documentElement;
const btn = document.getElementById('themeToggle');
if (btn) {
  btn.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('theme', root.dataset.theme);
  });
  const saved = localStorage.getItem('theme');
  if (saved) root.dataset.theme = saved;
}

const categoryMenus = document.querySelectorAll('.category-menu');
categoryMenus.forEach((menu) => {
  const button = menu.querySelector('.category-menu-button');
  if (!button) return;

  button.addEventListener('click', (event) => {
    event.stopPropagation();
    const isOpen = menu.classList.toggle('is-open');
    button.setAttribute('aria-expanded', String(isOpen));

    categoryMenus.forEach((otherMenu) => {
      if (otherMenu === menu) return;
      otherMenu.classList.remove('is-open');
      const otherButton = otherMenu.querySelector('.category-menu-button');
      if (otherButton) otherButton.setAttribute('aria-expanded', 'false');
    });
  });
});

document.addEventListener('click', (event) => {
  categoryMenus.forEach((menu) => {
    if (menu.contains(event.target)) return;
    menu.classList.remove('is-open');
    const button = menu.querySelector('.category-menu-button');
    if (button) button.setAttribute('aria-expanded', 'false');
  });
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  categoryMenus.forEach((menu) => {
    menu.classList.remove('is-open');
    const button = menu.querySelector('.category-menu-button');
    if (button) button.setAttribute('aria-expanded', 'false');
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

const marketWidget = document.querySelector('[data-market-widget]');
if (marketWidget) {
  const endpoint = marketWidget.dataset.marketEndpoint;
  const track = marketWidget.querySelector('[data-market-track]');
  const status = marketWidget.querySelector('[data-market-status]');
  const updateCards = (items = []) => {
    items.forEach((item) => {
      const card = track?.querySelector(`[data-symbol="${item.symbol}"]`);
      if (!card) return;
      const value = card.querySelector('[data-market-value]');
      const change = card.querySelector('[data-market-change]');
      if (value) value.textContent = item.value;
      if (change) {
        change.textContent = item.change;
        change.classList.toggle('is-negative', String(item.change || '').trim().startsWith('-'));
      }
    });
  };
  const refreshMarkets = async () => {
    if (!endpoint) return;
    try {
      const response = await fetch(endpoint, { headers: { Accept: 'application/json' }, cache: 'no-store' });
      if (!response.ok) throw new Error(`Market refresh failed: ${response.status}`);
      const payload = await response.json();
      updateCards(payload.items || []);
      if (status) {
        const sourceText = payload.source === 'provider' ? 'Live provider data' : 'Safe fallback data';
        status.textContent = `${sourceText} • ${new Date(payload.updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
      }
    } catch (error) {
      if (status) status.textContent = 'Safe fallback data • offline refresh ready';
    }
  };

  refreshMarkets();
  window.setInterval(refreshMarkets, 5 * 60 * 1000);
}
