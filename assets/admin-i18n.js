(() => {
  const STORAGE_KEY = 'vreycAdminLanguage';
  const DEFAULT_LANGUAGE = 'az';
  const SUPPORTED_LANGUAGES = ['az', 'en'];

  const translations = {
    az: {
      // Admin navigation
      'Dashboard': 'İdarə paneli',
      'Articles': 'Xəbərlər',
      'Categories': 'Kateqoriyalar',
      'Media Library': 'Media kitabxanası',
      'AI Translations': 'AI tərcümələr',
      'SEO Diagnostics': 'SEO diaqnostika',
      'Settings': 'Parametrlər',

      // Required common actions and labels
      'View site': 'Sayta bax',
      'Logout': 'Çıxış',
      'Create article': 'Xəbər yarat',
      'Save': 'Yadda saxla',
      'Delete': 'Sil',
      'Edit': 'Redaktə et',
      'View': 'Bax',
      'Preview': 'Önizlə',
      'Copy URL': 'URL kopyala',
      'Apply filters': 'Filtrləri tətbiq et',
      'Reset': 'Sıfırla',
      'Search articles': 'Xəbərlərdə axtar',
      'All categories': 'Bütün kateqoriyalar',
      'All languages': 'Bütün dillər',
      'All statuses': 'Bütün statuslar',
      'Newest first': 'Ən yenilər əvvəl',
      'Published': 'Yayında',
      'Drafts': 'Qaralamalar',
      'Scheduled': 'Planlaşdırılmış',
      'Bulk action': 'Toplu əməliyyat',
      'Bulk action…': 'Toplu əməliyyat…',
      'Apply to selected': 'Seçilənlərə tətbiq et',

      // Frequently used admin text kept small and easy to expand.
      'Draft': 'Qaralama',
      'All': 'Hamısı',
      'Category': 'Kateqoriya',
      'Language': 'Dil',
      'Status': 'Status',
      'Sort': 'Sıralama',
      'From': 'Başlanğıc',
      'To': 'Son',
      'Per page': 'Səhifə üzrə',
      'Title': 'Başlıq',
      'Publish at': 'Yayın vaxtı',
      'Views': 'Baxışlar',
      'Updated': 'Yenilənib',
      'Homepage': 'Ana səhifə',
      'Languages': 'Dillər',
      'Narration': 'Səsləndirmə',
      'Actions': 'Əməliyyatlar',
      'Analytics': 'Analitika',
      'Publish': 'Yayınla',
      'Unpublish': 'Yayından çıxar',
      'New article': 'Yeni xəbər',
      'Edit article': 'Xəbəri redaktə et',
      'Back to articles': 'Xəbərlərə qayıt',
      'Save article': 'Xəbəri yadda saxla',
      'Save settings': 'Parametrləri yadda saxla',
      'Save SEO settings': 'SEO parametrlərini yadda saxla',
      'Apply': 'Tətbiq et',
      'Oldest first': 'Ən köhnələr əvvəl',
      'Most viewed': 'Ən çox baxılan',
      'Most recently updated': 'Ən son yenilənən',
      'Bulk publish': 'Toplu yayınla',
      'Bulk unpublish': 'Toplu yayından çıxar',
      'Bulk category change': 'Toplu kateqoriya dəyişikliyi',
      'Bulk delete': 'Toplu sil',
      'Choose category for category change': 'Kateqoriya dəyişikliyi üçün kateqoriya seçin',
      'Select all articles on page': 'Səhifədəki bütün xəbərləri seç',
      'Instant search by title, slug or content': 'Başlıq, slug və ya məzmunda ani axtarış',
      'Type DELETE for bulk delete': 'Toplu silmə üçün DELETE yazın',
      'Premium newsroom console': 'Premium xəbər otağı konsolu',
      'Article management': 'Xəbər idarəetməsi',
      'Editorial articles': 'Redaksiya xəbərləri',
      'AI translations': 'AI tərcümələr',
      'SEO diagnostics': 'SEO diaqnostika',
      'User & SEO settings': 'İstifadəçi və SEO parametrləri',
      'Media library': 'Media kitabxanası',
      'Category manager': 'Kateqoriya meneceri',
      'Copied!': 'Kopyalandı!',
      'Copied': 'Kopyalandı'
    },
    en: {}
  };

  const textNodeOriginals = new WeakMap();
  const translatedAttributes = ['placeholder', 'aria-label', 'title'];

  const normalizeLanguage = (value) => SUPPORTED_LANGUAGES.includes(value) ? value : DEFAULT_LANGUAGE;

  const getStoredLanguage = () => {
    try {
      return normalizeLanguage(window.localStorage.getItem(STORAGE_KEY) || DEFAULT_LANGUAGE);
    } catch (error) {
      return DEFAULT_LANGUAGE;
    }
  };

  const storeLanguage = (language) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, language);
    } catch (error) {
      // localStorage can be unavailable in restricted browser contexts; keep the in-page toggle working.
    }
  };

  const preserveSpacing = (original, translated) => {
    const leading = original.match(/^\s*/)?.[0] || '';
    const trailing = original.match(/\s*$/)?.[0] || '';
    return `${leading}${translated}${trailing}`;
  };

  const translateValue = (source, language) => {
    if (language === 'en') return source;
    return translations[language]?.[source.trim()] || source;
  };

  const shouldSkipNode = (node) => {
    const parent = node.parentElement;
    if (!parent) return true;
    return Boolean(parent.closest('script, style, textarea, code, pre, [contenteditable="true"], [data-i18n-skip]'));
  };

  const applyTextTranslations = (language) => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (shouldSkipNode(node) || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });

    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    nodes.forEach((node) => {
      if (!textNodeOriginals.has(node)) textNodeOriginals.set(node, node.nodeValue);
      const original = textNodeOriginals.get(node);
      const translated = translateValue(original, language);
      node.nodeValue = preserveSpacing(original, translated);
    });
  };

  const applyAttributeTranslations = (language) => {
    document.querySelectorAll('[placeholder], [aria-label], [title]').forEach((element) => {
      if (element.closest('[data-i18n-skip]')) return;
      translatedAttributes.forEach((attribute) => {
        if (!element.hasAttribute(attribute)) return;
        const dataAttribute = `i18nOriginal${attribute.replace(/(^|-)(\w)/g, (_, _dash, char) => char.toUpperCase())}`;
        if (!element.dataset[dataAttribute]) element.dataset[dataAttribute] = element.getAttribute(attribute);
        element.setAttribute(attribute, translateValue(element.dataset[dataAttribute], language));
      });
    });
  };

  const updateSwitcherState = (language) => {
    document.documentElement.lang = language;
    document.querySelectorAll('[data-admin-language-option]').forEach((button) => {
      const active = button.dataset.adminLanguageOption === language;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  };

  const applyLanguage = (language) => {
    const normalized = normalizeLanguage(language);
    applyTextTranslations(normalized);
    applyAttributeTranslations(normalized);
    updateSwitcherState(normalized);
    window.dispatchEvent(new CustomEvent('admin-language-change', { detail: { language: normalized } }));
  };

  const initializeSwitcher = () => {
    document.querySelectorAll('[data-admin-language-option]').forEach((button) => {
      button.addEventListener('click', () => {
        const language = normalizeLanguage(button.dataset.adminLanguageOption);
        storeLanguage(language);
        applyLanguage(language);
      });
    });
  };

  document.addEventListener('DOMContentLoaded', () => {
    initializeSwitcher();
    applyLanguage(getStoredLanguage());
  });

  window.VREYCAdminI18n = {
    applyLanguage,
    getLanguage: getStoredLanguage,
    translate: translateValue,
    translations
  };
})();
